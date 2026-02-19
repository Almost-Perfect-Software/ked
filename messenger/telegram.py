import os
import logging
import threading
import re
import json
from collections import defaultdict
from typing import Any, Dict, List, Optional
import time
import hashlib

import requests

from utils.ked_utils import normalize_registry_tags, truncate_text

from base.ked_base import BaseMessenger, BaseRegistry
from base import ked_helm_deployer

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("Telegram Agent")
HTTP_TIMEOUT_SECONDS = 15
CALLBACK_TTL_SECONDS = 3600


class TelegramMessenger(BaseMessenger):
    def __init__(self, config: Dict[str, Any], registry: BaseRegistry):
        super().__init__(config, registry)
        self.DEPLOY_TIMEOUT = int(self.config.get("deploy_timeout") or os.environ.get("DEPLOY_TIMEOUT") or "60")
        self.TAG_PATTERN_MATCH = (
            self.config.get("tag_pattern_match")
            or os.environ.get("TAG_PATTERN_MATCH")
            or os.environ.get("tag_pattern_match")
            or r"^(.*)-(\d+\.\d+\.\d+(?:-\w+)?)$"
        )
        self.TELEGRAM_CHAT_ID = self.config.get("telegram", {}).get("chat_id") or os.environ.get("TELEGRAM_CHAT_ID")
        self.TELEGRAM_BOT_TOKEN = self.config.get("telegram", {}).get("bot_token") or os.environ.get("TELEGRAM_BOT_TOKEN")
        self.TELEGRAM_MSG_MAX_SIZE = self.config.get("telegram", {}).get("msg_max_size") or os.environ.get("TELEGRAM_MSG_MAX_SIZE")
        self.ENVIRONMENT = self.config.get("environment") or os.environ.get("ENVIRONMENT") or "default"

        self.TELEGRAM_API_URL = f"https://api.telegram.org/bot{self.TELEGRAM_BOT_TOKEN}"

        self.active_timers: Dict[str, threading.Timer] = {}
        self.update_offset = 0
        self.callback_data_store: Dict[str, Dict[str, Any]] = {}
        self.callback_data_expiry: Dict[str, float] = {}

    # ---- Helper telegram API ----
    def _send_message(self, text: str, reply_markup: Optional[Dict[str, Any]] = None):
        text = truncate_text(text, self.TELEGRAM_MSG_MAX_SIZE)
        url = f"{self.TELEGRAM_API_URL}/sendMessage"
        data = {
            "chat_id": self.TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "Markdown"
        }
        if reply_markup:
            data["reply_markup"] = json.dumps(reply_markup)
        response = requests.post(url, data=data, timeout=HTTP_TIMEOUT_SECONDS)
        result = response.json()
        if not result.get("ok"):
            logger.error(f"Failed to send message: {result}")
        return result

    def _edit_message(self, message_id: int, text: str, reply_markup: Optional[Dict[str, Any]] = None):
        text = truncate_text(text, self.TELEGRAM_MSG_MAX_SIZE)
        url = f"{self.TELEGRAM_API_URL}/editMessageText"
        data = {
            "chat_id": self.TELEGRAM_CHAT_ID,
            "message_id": message_id,
            "text": text,
            "parse_mode": "Markdown"
        }
        if reply_markup:
            data["reply_markup"] = json.dumps(reply_markup)
        response = requests.post(url, data=data, timeout=HTTP_TIMEOUT_SECONDS)
        result = response.json()
        if not result.get("ok"):
            logger.error(f"Failed to edit message: {result}")
        return result

    def _answer_callback_query(self, callback_query_id: str, text: str = ""):
        url = f"{self.TELEGRAM_API_URL}/answerCallbackQuery"
        data = {
            "callback_query_id": callback_query_id,
            "text": text
        }
        response = requests.post(url, data=data, timeout=HTTP_TIMEOUT_SECONDS)
        return response.json()

    def _get_updates(self, offset: Optional[int] = None):
        url = f"{self.TELEGRAM_API_URL}/getUpdates"
        data = {"timeout": 30}
        if offset:
            data["offset"] = offset
        try:
            response = requests.post(url, data=data, timeout=35)
            result = response.json()
            if not result.get("ok"):
                logger.error(f"Failed to get updates: {result}")
            return result
        except requests.exceptions.Timeout:
            return {"ok": True, "result": []}
        except Exception as e:
            logger.error(f"Exception getting updates: {e}")
            return {"ok": False, "result": []}

    def _set_commands(self):
        url = f"{self.TELEGRAM_API_URL}/setMyCommands"
        env_lower = self.ENVIRONMENT.lower().replace('-', '_')
        commands = [
            {"command": f"deploy_{env_lower}", "description": f"Deploy to {self.ENVIRONMENT}"},
            {"command": "deploy", "description": f"Deploy to {self.ENVIRONMENT}"}
        ]
        data = {"commands": json.dumps(commands)}
        response = requests.post(url, data=data, timeout=HTTP_TIMEOUT_SECONDS)
        result = response.json()
        if result.get("ok"):
            logger.info(f"Bot commands set successfully: {[cmd['command'] for cmd in commands]}")
        else:
            logger.error(f"Failed to set commands: {result}")
        return result

    def _generate_callback_id(self, data: Dict[str, Any]) -> str:
        callback_id = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:8]
        self.callback_data_store[callback_id] = data
        self.callback_data_expiry[callback_id] = time.time() + CALLBACK_TTL_SECONDS
        return callback_id

    def _consume_callback_payload(self, callback_id: str) -> Optional[Dict[str, Any]]:
        payload = self.callback_data_store.get(callback_id)
        expires_at = self.callback_data_expiry.get(callback_id, 0)
        if not payload or time.time() > expires_at:
            self.callback_data_store.pop(callback_id, None)
            self.callback_data_expiry.pop(callback_id, None)
            return None
        self.callback_data_store.pop(callback_id, None)
        self.callback_data_expiry.pop(callback_id, None)
        return payload

    def _clear_timer(self, timer_key: str) -> None:
        timer = self.active_timers.pop(timer_key, None)
        if timer:
            timer.cancel()

    # ---- BaseMessenger impl ----
    def start_messenger(self) -> None:
        try:
            logger.info("Starting Telegram Bot...")

            self._set_commands()

            test_response = self._send_message("🤖 Telegram Bot started and ready!")
            if not test_response.get("ok"):
                logger.error(f"Failed to send test message: {test_response}")
                return
            else:
                logger.info("Bot connection test successful")

            while True:
                try:
                    updates = self._get_updates(self.update_offset)
                    if updates.get("ok"):
                        results = updates.get("result", [])
                        if results:
                            logger.info(f"Received {len(results)} updates")

                        for update in results:
                            logger.info(f"Processing update: {update.get('update_id')}")
                            self._handle_update(update)
                            self.update_offset = update["update_id"] + 1
                    else:
                        logger.error(f"Error getting updates: {updates}")
                        time.sleep(5)
                except Exception as e:
                    logger.error(f"Error in polling loop: {e}")
                    time.sleep(5)
        except Exception as e:
            logger.error(f"Startup error: {e}")

    def send_messenger_notification(self, repo_name: str, image_tag: str, pushed_at: str) -> None:
        try:
            text = self._build_deploy_notification_text(repo_name, image_tag, pushed_at)
            keyboard = self._build_deploy_notification_keyboard(repo_name, image_tag)

            response = self._send_message(text, keyboard)
            if not response.get("ok"):
                logger.error(f"Failed to send notification: {response}")
                return

            message_id = response.get("result", {}).get("message_id")

            def timeout():
                try:
                    timeout_text = f"⏰ *No action taken for {repo_name}:{image_tag} — skipped after {self.DEPLOY_TIMEOUT} minutes.*"
                    self._edit_message(message_id, timeout_text)
                except Exception as timeout_err:
                    logger.error(f"Timeout update failed: {timeout_err}")
                finally:
                    self._clear_timer(timer_key)

            timer_key = f"{repo_name}:{image_tag}"
            self._clear_timer(timer_key)
            timer = threading.Timer(self.DEPLOY_TIMEOUT * 60, timeout)
            self.active_timers[timer_key] = timer
            timer.start()

        except Exception as telegram_err:
            logger.error(f"Failed to send Telegram message: {telegram_err}")

    # ---- Update routing ----
    def _handle_update(self, update: Dict[str, Any]) -> None:
        try:
            if "message" in update:
                self._handle_message(update["message"])
            elif "channel_post" in update:
                self._handle_message(update["channel_post"])
            elif "callback_query" in update:
                self._handle_callback_query(update["callback_query"])
            else:
                logger.info(f"Unhandled update type: {list(update.keys())}")
        except Exception as e:
            logger.error(f"Error handling update: {e}")

    def _handle_message(self, message: Dict[str, Any]) -> None:
        text = message.get("text", "")
        chat_id = message["chat"]["id"]
        user = message.get("from", message.get("sender_chat", {}))

        if str(chat_id) != str(self.TELEGRAM_CHAT_ID):
            logger.warning(f"Ignoring message from unauthorized chat: {chat_id} (expected: {self.TELEGRAM_CHAT_ID})")
            return

        if text.startswith("/"):
            env_lower = self.ENVIRONMENT.lower().replace('-', '_')
            deploy_patterns = [
                f"/deploy_{self.ENVIRONMENT}",
                f"/deploy-{self.ENVIRONMENT}",
                f"/deploy_{env_lower}",
                f"/deploy_{self.ENVIRONMENT.lower()}",
                "/deploy"
            ]

            for pattern in deploy_patterns:
                if text.startswith(pattern):
                    self._handle_deploy_command(message)
                    return

            help_text = (
                f"Available commands:\n"
                f"`/deploy_{env_lower}` - Deploy to {self.ENVIRONMENT}\n"
                f"`/deploy` - Deploy to {self.ENVIRONMENT}\n\n"
                f"You can also use:\n"
                f"`/deploy_{self.ENVIRONMENT}` or `/deploy-{self.ENVIRONMENT}`"
            )
            self._send_message(help_text)

    def _handle_callback_query(self, callback_query: Dict[str, Any]) -> None:
        data = callback_query["data"]
        message = callback_query["message"]
        user = callback_query["from"]

        self._answer_callback_query(callback_query["id"])

        try:
            if data.startswith("repo_"):
                self._handle_repository_selection(data, message, user)
            elif data.startswith("service_"):
                self._handle_service_selection(data, message, user)
            elif data.startswith("deploy_"):
                self._handle_deploy_action(data, message, user)
            elif data.startswith("skip_"):
                self._handle_skip_action(data, message, user)
            else:
                logger.warning(f"Unknown callback data pattern: {data}")
        except Exception as e:
            logger.error(f"Error handling callback query: {e}")

    # ---- UI builders and handlers ----
    def _build_deploy_notification_text(self, repo_name: str, image_tag: str, pushed_at: str) -> str:
        return (
            f"🚀 *New Image Alert!*\n"
            f"Repository: *{repo_name}*\n"
            f"Tag: *{image_tag}*\n"
            f"Pushed At: *{pushed_at}*"
        )

    def _build_deploy_notification_keyboard(self, repo_name: str, image_tag: str) -> Dict[str, Any]:
        deploy_id = self._generate_callback_id({'repo': repo_name, 'tag': image_tag, 'source': 'from_monitor'})
        skip_id = self._generate_callback_id({'repo': repo_name, 'tag': image_tag, 'source': 'skip'})
        return {
            "inline_keyboard": [[
                {"text": "✅ Deploy", "callback_data": f"deploy_{deploy_id}"},
                {"text": "❌ Skip", "callback_data": f"skip_{skip_id}"}
            ]]
        }

    def _build_repo_selection_keyboard(self, repos: List[str]) -> Dict[str, Any]:
        keyboard = []
        for repo in repos:
            keyboard.append([{"text": repo, "callback_data": f"repo_{repo[:50]}"}])
        return {"inline_keyboard": keyboard}

    def _build_tag_keyboard(self, repo_name: str, service: str, tags: List[str]) -> Dict[str, Any]:
        keyboard = []
        sorted_tags = sorted(tags, reverse=True)
        for tag in sorted_tags:
            callback_id = self._generate_callback_id({'repo': repo_name, 'tag': tag, 'source': 'from_group'})
            keyboard.append([{"text": f"Deploy {tag}", "callback_data": f"deploy_{callback_id}"}])
        return {"inline_keyboard": keyboard}

    def _build_service_selection_keyboard(self, repo_name: str, services: List[str]) -> Dict[str, Any]:
        keyboard = []
        for service in sorted(services):
            callback_id = self._generate_callback_id({'repo': repo_name, 'service': service})
            keyboard.append([{"text": service, "callback_data": f"service_{callback_id}"}])
        return {"inline_keyboard": keyboard}

    def _handle_deploy_command(self, message: Dict[str, Any]) -> None:
        try:
            text = message.get("text", "").strip()
            command_parts = text.split()
            repo_name = " ".join(command_parts[1:]) if len(command_parts) > 1 else ""

            repos = getattr(self.registry, "REPOSITORIES", [])
            if not repo_name:
                text = "Select a repository to view its images:"
                keyboard = self._build_repo_selection_keyboard(sorted(repos))
                self._send_message(text, keyboard)
                return

            if repo_name not in repos:
                available_repos = ", ".join(sorted(repos))
                self._send_message(f"❌ The repository `{repo_name}` is not in the available list.\n\nAvailable repositories: {available_repos}")
                return

            images = self.registry.get_repository_images(repo_name)
            if not images:
                self._send_message(f"ℹ️ The repository `{repo_name}` has no images.")
                return

            keyboard = self._build_image_keyboard(repo_name, images)
            max_buttons = 45
            if len(keyboard["inline_keyboard"]) > max_buttons:
                keyboard["inline_keyboard"] = keyboard["inline_keyboard"][:max_buttons]

            if not keyboard["inline_keyboard"]:
                self._send_message("ℹ️ No valid image tags found (excluding 'latest').")
                return

            text = f"*Images in {repo_name}:*"
            self._send_message(text, keyboard)

        except Exception as deploy_error:
            logger.exception(f"Deploy command handler failed: {deploy_error}")
            self._send_message(f"❌ Unexpected error: `{deploy_error}`")

    def _build_image_keyboard(self, repo_name: str, images: List[Any]) -> Dict[str, Any]:
        keyboard = []
        flat_tags = normalize_registry_tags(images)
        for tag in sorted(flat_tags, reverse=True):
            if not isinstance(tag, str):
                continue
            if "latest" in tag.lower():
                continue
            if not re.match(self.TAG_PATTERN_MATCH, tag):
                continue
            callback_id = self._generate_callback_id({'repo': repo_name, 'tag': tag, 'source': 'from_deploy'})
            keyboard.append([{"text": f"Deploy {tag}", "callback_data": f"deploy_{callback_id}"}])
        return {"inline_keyboard": keyboard}

    def _handle_repository_selection(self, data: str, message: Dict[str, Any], user: Dict[str, Any]) -> None:
        repo_name = data.replace("repo_", "")
        logger.info(f"User {user.get('username', user.get('id'))} selected repository: {repo_name}")

        try:
            images_or_tags = self.registry.get_repository_images(repo_name)
            flat_tags: List[str] = normalize_registry_tags(images_or_tags)

            if not flat_tags:
                text = f"ℹ️ No images found for `{repo_name}`."
                self._edit_message(message["message_id"], text)
                return

            # Group tags by service name
            service_tags = defaultdict(list)
            for tag_str in flat_tags:
                # Skip 'latest' variants safely
                if isinstance(tag_str, str) and "latest" in tag_str.lower():
                    continue

                match = re.match(self.TAG_PATTERN_MATCH, tag_str)
                if match:
                    service_name = match.group(1)
                    service_tags[service_name].append(tag_str)
                else:
                    service_tags["other"].append(tag_str)

            if len(service_tags) == 1:
                only_service = list(service_tags.keys())[0]
                text = f"*Tags for `{only_service}` in `{repo_name}`:*"
                keyboard = self._build_tag_keyboard(repo_name, only_service, service_tags[only_service])
                self._edit_message(message["message_id"], text, keyboard)
                return

            text = f"*Select a service group in `{repo_name}` to view tags:*"
            keyboard = self._build_service_selection_keyboard(repo_name, list(service_tags.keys()))
            self._edit_message(message["message_id"], text, keyboard)

        except Exception as err:
            logger.error(f"Error in handle_repository_selection for '{repo_name}': {err}")
            text = f"❌ Failed to fetch images due to: {err}"
            self._edit_message(message["message_id"], text)

    def _handle_service_selection(self, data: str, message: Dict[str, Any], user: Dict[str, Any]) -> None:
        try:
            callback_id = data.replace("service_", "")
            payload = self._consume_callback_payload(callback_id)
            if not payload:
                self._edit_message(message["message_id"], "❌ Session expired. Please try again.")
                return

            repo_name = payload["repo"]
            service = payload["service"]
        except (KeyError):
            logger.error("Error parsing service selection data")
            return

        try:
            tags = self.registry.get_repository_tags(repo_name)
            service_tags = []
            for tag in tags:
                if not isinstance(tag, str):
                    continue
                if "latest" in tag.lower():
                    continue
                match = re.match(self.TAG_PATTERN_MATCH, tag)
                if service == "other":
                    if not match:
                        service_tags.append(tag)
                elif match and match.group(1) == service:
                    service_tags.append(tag)

            if not service_tags:
                text = f"ℹ️ No tags found for `{service}` in `{repo_name}`."
                self._edit_message(message["message_id"], text)
                return

            text = f"*Tags for `{service}` in `{repo_name}`:*"
            keyboard = self._build_tag_keyboard(repo_name, service, service_tags)
            self._edit_message(message["message_id"], text, keyboard)

        except Exception as err:
            logger.error(f"Error in handle_service_selection: {err}")
            text = f"❌ Failed to list tags due to: {err}"
            self._edit_message(message["message_id"], text)

    def _handle_deploy_action(self, data: str, message: Dict[str, Any], user: Dict[str, Any]) -> None:
        try:
            callback_id = data.replace("deploy_", "")
            payload = self._consume_callback_payload(callback_id)
            if not payload:
                self._edit_message(message["message_id"], "❌ Session expired. Please try again.")
                return

            repo_name = payload["repo"]
            image_tag = payload["tag"]
        except (KeyError):
            logger.error("Error parsing deploy action data")
            return

        try:
            user_mention = f"@{user.get('username', user.get('first_name', str(user.get('id'))))}"

            timer_key = f"{repo_name}:{image_tag}"
            self._clear_timer(timer_key)

            initial_text = (
                f"👟 *Deployment Initiated:*\n"
                f"Repository: `{repo_name}`\n"
                f"Tag: `{image_tag}`\n"
                f"Initiated by: {user_mention}"
            )
            self._edit_message(message["message_id"], initial_text)

            result = ked_helm_deployer.dummy_deploy_function(self.config, repo_name, image_tag)
            status_label = "Success" if result["success"] else "Failed"
            icon = "✅" if result["success"] else "❌"

            result_text = (
                f"{icon} *{status_label}!* Deployment status for {repo_name}:{image_tag}\n"
                f"*Details:* {result['message'].rstrip('.')}\n"
                f"Deployed by {user_mention}."
            )
            self._edit_message(message["message_id"], result_text)

        except Exception as deploy_err:
            logger.error(f"Deploy action error: {deploy_err}")
            error_text = f"❌ Deployment failed due to: `{deploy_err}`"
            self._edit_message(message["message_id"], error_text)

    def _handle_skip_action(self, data: str, message: Dict[str, Any], user: Dict[str, Any]) -> None:
        try:
            callback_id = data.replace("skip_", "")
            payload = self._consume_callback_payload(callback_id)
            if not payload:
                self._edit_message(message["message_id"], "❌ Session expired. Please try again.")
                return

            repo_name = payload["repo"]
            image_tag = payload["tag"]
        except (KeyError):
            logger.error("Error parsing skip action data")
        else:
            try:
                user_mention = f"@{user.get('username', user.get('first_name', str(user.get('id'))))}"

                timer_key = f"{repo_name}:{image_tag}"
                self._clear_timer(timer_key)

                logger.info(f"Deployment skipped by {user_mention} for {repo_name}:{image_tag}")
                skip_text = f"❌ *Deployment for {repo_name}:{image_tag} was skipped by {user_mention}.*"
                self._edit_message(message["message_id"], skip_text)
            except Exception as skip_err:
                logger.error(f"Skip handler error: {skip_err}")
