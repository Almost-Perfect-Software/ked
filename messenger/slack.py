
import os
import logging
import threading
import re
import json
from collections import defaultdict
from typing import Any, Dict, List

from utils.ked_utils import normalize_registry_tags, truncate_text

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from base.ked_base import BaseMessenger, BaseRegistry
from base import ked_helm_deployer

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("Slack Agent")
MAX_ACTIONS_ELEMENTS = 25


class SlackMessenger(BaseMessenger):
    def __init__(self, config: Dict[str, Any], registry: BaseRegistry):
        super().__init__(config, registry)
        self.DEPLOY_TIMEOUT = int(self.config.get("deploy_timeout") or os.environ.get("DEPLOY_TIMEOUT") or "60")
        self.TAG_PATTERN_MATCH = (
            self.config.get("tag_pattern_match")
            or os.environ.get("TAG_PATTERN_MATCH")
            or os.environ.get("tag_pattern_match")
            or r"^(.*)-(\d+\.\d+\.\d+(?:-\w+)?)$"
        )
        self.SLACK_CHANNEL = self.config.get("slack", {}).get("channel") or os.environ.get("SLACK_CHANNEL")
        self.SLACK_BOT_TOKEN = self.config.get("slack", {}).get("bot_token") or os.environ.get("SLACK_BOT_TOKEN")
        self.SLACK_APP_TOKEN = self.config.get("slack", {}).get("app_token") or os.environ.get("SLACK_APP_TOKEN")
        self.SLACK_MSG_MAX_SIZE = self.config.get("slack", {}).get("msg_max_size") or os.environ.get("SLACK_MSG_MAX_SIZE")
        self.ENVIRONMENT = self.config.get("environment") or os.environ.get("ENVIRONMENT") or "default"

        # Initialize the Slack Bolt app
        self.slack_app = App(token=self.SLACK_BOT_TOKEN)
        self.active_timers: Dict[str, threading.Timer] = {}

        # Register handlers
        self._register_handlers()

    def _clear_timer(self, timer_key: str) -> None:
        timer = self.active_timers.pop(timer_key, None)
        if timer:
            timer.cancel()

    @staticmethod
    def _chunk_buttons(buttons: List[Dict[str, Any]], chunk_size: int = MAX_ACTIONS_ELEMENTS) -> List[List[Dict[str, Any]]]:
        return [buttons[i:i + chunk_size] for i in range(0, len(buttons), chunk_size)]


    def _register_handlers(self):
        env = self.ENVIRONMENT

        @self.slack_app.command(f"/deploy-{env}")
        def handle_deploy_command(ack, respond, command):
            try:
                ack()
            except Exception as ack_error:
                logger.error(f"Failed to acknowledge /deploy-{env}: {ack_error}")
                return respond(truncate_text(f":x: Failed to acknowledge command.", self.SLACK_MSG_MAX_SIZE))

            try:
                repo_name = command.get("text", "").strip()
                repos = getattr(self.registry, "REPOSITORIES", [])
                if not repo_name:
                    return respond(blocks=self.build_repo_selection_blocks(sorted(repos)), response_type="ephemeral")

                if repo_name not in repos:
                    return respond(truncate_text(f":x: The repository `{repo_name}` is not in the available list.", self.SLACK_MSG_MAX_SIZE))

                images = self.registry.get_repository_images(repo_name)
                if not images:
                    return respond(truncate_text(f":information_source: The repository `{repo_name}` has no images.", self.SLACK_MSG_MAX_SIZE))

                blocks = self.build_image_blocks(repo_name, images)
                max_blocks = 45
                if len(blocks) > max_blocks:
                    blocks = blocks[:max_blocks]
                    blocks.append(self.info_block(f"Showing only the first {max_blocks} tags."))

                if not blocks:
                    return respond(blocks=[self.info_block("No valid image tags found (excluding 'latest').")])

                return respond(blocks=blocks)

            except Exception as deploy_error:
                logger.exception(f"Deploy command handler failed: {deploy_error}")
                return respond(truncate_text(f":x: Unexpected error: `{deploy_error}`", self.SLACK_MSG_MAX_SIZE))

        @self.slack_app.event("app_home_opened")
        def handle_app_home_opened_events(body):
            logger.info(f"App Home opened by user: {body.get('event', {}).get('user')}")

        @self.slack_app.action(re.compile(r"^select_repo_\d+$"))
        def handle_repository_selection(ack, body, respond):
            ack()
            repo_name = body["actions"][0]["value"]
            logger.info(f"User selected repository: {repo_name}")

            try:
                images_or_tags = self.registry.get_repository_images(repo_name)
                flat_tags = normalize_registry_tags(images_or_tags)
                if not flat_tags:
                    return respond(truncate_text(f":information_source: No images found for `{repo_name}`.", self.SLACK_MSG_MAX_SIZE))

                service_tags: Dict[str, List[str]] = defaultdict(list)
                for tag_str in flat_tags:
                    if not isinstance(tag_str, str):
                        continue
                    if "latest" in tag_str.lower():
                        continue
                    match = re.match(self.TAG_PATTERN_MATCH, tag_str)
                    if not match:
                        logger.debug(f"Skipping tag '{tag_str}' as it does not match TAG_PATTERN_MATCH: {self.TAG_PATTERN_MATCH}")
                        continue
                    service_name = match.group(1)
                    service_tags[service_name].append(tag_str)

                if not service_tags:
                    return respond(truncate_text(
                        f":information_source: No tags in `{repo_name}` match the configured pattern `{self.TAG_PATTERN_MATCH}`.", self.SLACK_MSG_MAX_SIZE))

                if len(service_tags) == 1:
                    only_service = list(service_tags.keys())[0]
                    return respond(blocks=self.build_tag_blocks(repo_name, only_service, service_tags[only_service]))

                buttons = []
                for i, group in enumerate(sorted(service_tags)):
                    buttons.append({
                        "type": "button",
                        "text": {"type": "plain_text", "text": group},
                        "value": json.dumps({"repo": repo_name, "service": group}),
                        "action_id": f"select_service_{i}"
                    })

                blocks = [
                    {"type": "section", "text": {"type": "mrkdwn", "text": f"*Select a service group in `{repo_name}` to view tags (matching pattern):*"}}
                ]
                blocks.extend([{"type": "actions", "elements": chunk} for chunk in self._chunk_buttons(buttons)])
                return respond(blocks=blocks)

            except Exception as err:
                logger.error(f"Error in handle_repository_selection for '{repo_name}': {err}")
                return respond(truncate_text(f":x: Failed to fetch images due to: {err}", self.SLACK_MSG_MAX_SIZE))

        @self.slack_app.action(re.compile(r"^select_service_\d+$"))
        def handle_service_selection(ack, body, respond):
            ack()
            payload = json.loads(body["actions"][0]["value"])
            repo_name = payload["repo"]
            service = payload["service"]

            logger.info(f"User selected service: {service} in repo: {repo_name}")

            try:
                tags = self.registry.get_repository_tags(repo_name)
                service_tags = []
                for tag in tags:
                    if not isinstance(tag, str):
                        continue
                    if "latest" in tag.lower():
                        continue
                    m = re.match(self.TAG_PATTERN_MATCH, tag)
                    if not m:
                        logger.debug(f"Skipping tag '{tag}' in service selection; does not match pattern: {self.TAG_PATTERN_MATCH}")
                        continue
                    if m.group(1) != service:
                        continue
                    service_tags.append(tag)
                if not service_tags:
                    return respond(truncate_text(
                        f":information_source: No tags for `{service}` in `{repo_name}` match the configured pattern `{self.TAG_PATTERN_MATCH}`.", self.SLACK_MSG_MAX_SIZE))
                blocks = self.build_tag_blocks(repo_name, service, service_tags)
                return respond(blocks=blocks)
            except Exception as err:
                logger.error(f"Error in handle_service_selection: {err}")
                return respond(truncate_text(f":x: Failed to list tags due to: {err}", self.SLACK_MSG_MAX_SIZE))

        @self.slack_app.action("deploy_action")
        def handle_deploy_action(ack, body):
            ack()
            try:
                user = body["user"]["id"]
                channel_id = body["channel"]["id"]
                action_value = body["actions"][0]["value"]
                payload = json.loads(action_value)

                repo_name = payload["repo"]
                image_tag = payload["tag"]

                timer_key = f"{repo_name}:{image_tag}"
                self._clear_timer(timer_key)

                message_ts = body.get("message", {}).get("ts")
                initial_block = [self.build_status_block(
                    ":athletic_shoe:",
                    f"*Deployment Initiated:*\nRepository: `{repo_name}`\nTag: `{image_tag}`\nInitiated by: <@{user}>"
                )]

                if message_ts:
                    self.slack_app.client.chat_update(
                        channel=channel_id,
                        ts=message_ts,
                        text=truncate_text("Deployment Initiated.", self.SLACK_MSG_MAX_SIZE),
                        blocks=initial_block,
                    )
                else:
                    logger.warning("No 'ts' found — posting a new message instead of updating")
                    response = self.slack_app.client.chat_postMessage(
                        channel=channel_id,
                        text=truncate_text("Deployment Initiated.", self.SLACK_MSG_MAX_SIZE),
                        blocks=initial_block,
                    )
                    message_ts = response["ts"]

                result = ked_helm_deployer.dummy_deploy_function(self.config, repo_name, image_tag)
                status_label = "Success" if result["success"] else "Failed"
                icon = ":white_check_mark:" if result["success"] else ":x:"

                result_message = (
                    f"*{status_label}!* Deployment status for {repo_name}:{image_tag}\n"
                    f"*Details:* {result['message'].rstrip('.')}\n"
                    f"Deployed by <@{user}>."
                )

                self.slack_app.client.chat_update(
                    channel=channel_id,
                    ts=message_ts,
                    text=truncate_text("Deployment Result", self.SLACK_MSG_MAX_SIZE),
                    blocks=[self.build_status_block(icon, result_message)],
                )

            except ValueError as ve:
                logger.error(f"Deploy action error: {ve}")
                self.slack_app.client.chat_postMessage(
                    channel=body["channel"]["id"],
                    text=truncate_text("Deployment Failed.", self.SLACK_MSG_MAX_SIZE),
                    blocks=[self.build_status_block(":x:", "Deployment failed due to missing message timestamp.")],
                )
            except Exception as deploy_err:
                logger.error(f"Deploy action error: {deploy_err}")
                self.slack_app.client.chat_postMessage(
                    channel=body["channel"]["id"],
                    text=truncate_text("Deployment Failed.", self.SLACK_MSG_MAX_SIZE),
                    blocks=[self.build_status_block(":x:", f"Deployment failed due to: `{deploy_err}`")],
                )

        @self.slack_app.action("skip_action")
        def handle_skip_action(ack, body):
            ack()
            try:
                user = body["user"]["id"]
                channel_id = body["channel"]["id"]
                message_ts = body["message"]["ts"]

                payload = json.loads(body["actions"][0]["value"])
                repo_name = payload["repo"]
                image_tag = payload["tag"]

                timer_key = f"{repo_name}:{image_tag}"
                self._clear_timer(timer_key)

                logger.info(f"Deployment skipped by <@{user}> for {repo_name}:{image_tag}")
                self.slack_app.client.chat_update(
                    channel=channel_id,
                    ts=message_ts,
                    text=truncate_text("Deployment Skipped.", self.SLACK_MSG_MAX_SIZE),
                    blocks=[self.build_status_block(":x:", f"*Deployment for {repo_name}:{image_tag} was skipped by <@{user}>.*")],
                )

            except Exception as skip_err:
                logger.error(f"Skip handler error: {skip_err}")

    def start_messenger(self):
        try:
            logger.info("Starting Slack Bot...")
            handler = SocketModeHandler(self.slack_app, self.SLACK_APP_TOKEN)
            handler.start()
        except Exception as e:
            logger.error(f"Startup error: {e}")

    def send_messenger_notification(self, repo_name: str, image_tag: str, pushed_at: str):
        try:
            blocks = self.build_deploy_notification_blocks(repo_name, image_tag, pushed_at)
            response = self.slack_app.client.chat_postMessage(
                channel=self.SLACK_CHANNEL,
                blocks=blocks,
                text=truncate_text(f"A new image has been detected in {repo_name}.", self.SLACK_MSG_MAX_SIZE),
            )
            message_ts = response["ts"]

            def timeout():
                try:
                    self.slack_app.client.chat_update(
                        channel=self.SLACK_CHANNEL,
                        ts=message_ts,
                        text=truncate_text("Deployment Skipped by Timeout.", self.SLACK_MSG_MAX_SIZE),
                        blocks=[self.build_status_block(":alarm_clock:", f"*No action taken for {repo_name}:{image_tag} — skipped after {self.DEPLOY_TIMEOUT} minutes.*")],
                    )
                except Exception as timeout_err:
                    logger.error(f"Timeout update failed: {timeout_err}")
                finally:
                    self._clear_timer(timer_key)

            timer_key = f"{repo_name}:{image_tag}"
            self._clear_timer(timer_key)
            timer = threading.Timer(self.DEPLOY_TIMEOUT * 60, timeout)
            self.active_timers[timer_key] = timer
            timer.start()

        except Exception as slack_err:
            logger.error(f"Failed to send Slack message: {slack_err}")

    # ----- UI builders -----
    def build_tag_blocks(self, repo_name: str, service: str, tags: List[str]):
        blocks = [{
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Tags for `{service}` in `{repo_name}`:*"}
        }]
        sorted_tags = sorted(tags, reverse=True)
        for tag in sorted_tags:
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"`{tag}`"},
                "accessory": {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Deploy"},
                    "value": json.dumps({
                        "repo": repo_name,
                        "tag": tag,
                        "source": "from_group"
                    }),
                    "action_id": "deploy_action",
                }
            })
        return blocks

    def build_status_block(self, icon: str, message: str):
        return {"type": "section", "text": {"type": "mrkdwn", "text": f"{icon} {truncate_text(message, self.SLACK_MSG_MAX_SIZE)}"}}

    def build_deploy_notification_blocks(self, repo_name: str, image_tag: str, pushed_at: str):
        return [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"`New Image Alert!`\n"
                        f"Repository: *{repo_name}*\n"
                        f"Tag: *{image_tag}*\n"
                        f"Pushed At: *{pushed_at}*"
                    ),
                },
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Deploy", "emoji": True},
                        "value": json.dumps({"repo": repo_name, "tag": image_tag, "source": "from_monitor"}),
                        "action_id": "deploy_action",
                        "style": "primary",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Skip", "emoji": True},
                        "value": json.dumps({"repo": repo_name, "tag": image_tag, "source": "skip"}),
                        "action_id": "skip_action",
                        "style": "danger",
                    },
                ],
            },
        ]

    def build_repo_selection_blocks(self, repos: List[str]):
        buttons = [
            {"type": "button", "text": {"type": "plain_text", "text": repo}, "value": repo, "action_id": f"select_repo_{i}"}
            for i, repo in enumerate(repos)
        ]
        blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": "Select a repository to view its images:"}}]
        blocks.extend([{"type": "actions", "elements": chunk} for chunk in self._chunk_buttons(buttons)])
        return blocks

    def build_image_blocks(self, repo_name: str, images: List[Any]):
        blocks = []
        flat_tags = normalize_registry_tags(images)
        for tag in flat_tags:
            if not isinstance(tag, str):
                continue
            if "latest" in tag.lower():
                continue
            if not re.match(self.TAG_PATTERN_MATCH, tag):
                logger.debug(f"Skipping tag '{tag}' in image list; does not match pattern: {self.TAG_PATTERN_MATCH}")
                continue
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Tag:* `{tag}`"},
                "accessory": {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Deploy"},
                    "value": json.dumps({"repo": repo_name, "tag": tag, "source": "from_deploy"}),
                    "action_id": "deploy_action",
                },
            })
        return blocks

    def info_block(self, message: str):
        return {"type": "section", "text": {"type": "mrkdwn", "text": f":information_source: {message}"}}
