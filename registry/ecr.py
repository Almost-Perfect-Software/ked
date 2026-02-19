from typing import Any, Dict, List, Tuple
import boto3
import time
from datetime import datetime
import logging
import os

from base.ked_base import BaseRegistry
from utils import ked_utils

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("ECR Repository Monitor")


class EcrRegistry(BaseRegistry):
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        # Configuration (Use environment variables for secure access)
        self.HEALTH_FILE_PATH = "/tmp/healthz"
        self.REGION = self.config.get("ecr", {}).get("region") or os.environ.get("ECR_REGION")
        self.REPOSITORIES = self.config.get("ecr", {}).get("repositories") or os.environ.get("ECR_REPOSITORIES", "").split(",")
        self.POLL_INTERVAL_SECONDS = (
            self.config.get("ecr", {}).get("poll_interval_seconds")
            or self.config.get("ecr", {}).get("check_interval_seconds")
            or int(os.environ.get("POLL_INTERVAL_SECONDS", 60))
        )
        # Initialize AWS ECR client
        self.ecr_client = boto3.client("ecr", region_name=self.REGION)

    def get_repository_images(self, repository_name: str) -> List[Dict[str, Any]]:
        try:
            images = []
            paginator = self.ecr_client.get_paginator("describe_images")
            for page in paginator.paginate(repositoryName=repository_name):
                images.extend(page.get("imageDetails", []))
            return images
        except Exception as e:
            logger.error(f"Failed to fetch images for repository {repository_name}: {e}")
            return []

    def get_repository_tags(self, repository_name: str) -> List[str]:
        try:
            tags: List[str] = []
            paginator = self.ecr_client.get_paginator("describe_images")
            for page in paginator.paginate(repositoryName=repository_name):
                for image in page.get("imageDetails", []):
                    tags.extend(image.get("imageTags", []) or [])
            return tags
        except Exception as e:
            logger.error(f"Failed to fetch image tags for repository {repository_name}: {e}")
            return []

    def monitor_repositories(self) -> Tuple[str, str, str]:
        logger.info("Starting ECR monitoring...")
        tracked_images = {repo: set() for repo in self.REPOSITORIES}

        logger.info("Setting baseline for tracked images...")
        for repo in self.REPOSITORIES:
            if not repo or not str(repo).strip():
                continue
            logger.info(f"Fetching baseline images for repository: {repo}")
            images = self.get_repository_images(repo)
            for image in images:
                digest = image.get("imageDigest")
                if digest:
                    tracked_images[repo].add(digest)

        logger.info("Baseline setup complete. Monitoring for new images...")

        while True:
            for repo in self.REPOSITORIES:
                if not repo or not str(repo).strip():
                    continue

                if not ked_utils.is_registry_in_jobs(repo, self.config.get("jobs", [])):
                    continue

                logger.info(f"Checking repository: {repo}")
                images = self.get_repository_images(repo)

                for image in images:
                    matched_tags = []
                    digest = image.get("imageDigest")
                    tags = image.get("imageTags", []) or []

                    allowed_tags = ked_utils.find_tags_for_registry(repo, self.config.get("jobs", []))
                    if not allowed_tags:
                        continue

                    for tag in tags:
                        if ked_utils.is_tag_allowed(tag, allowed_tags):
                            matched_tags.append(tag)
                            break

                    if not matched_tags:
                        continue

                    valid_tags = ked_utils.filter_tags(tags)
                    if not valid_tags:
                        continue

                    pushed_at_raw = image.get("imagePushedAt", None)
                    if pushed_at_raw and isinstance(pushed_at_raw, datetime):
                        pushed_at = pushed_at_raw.strftime('%c')
                    elif pushed_at_raw and isinstance(pushed_at_raw, str):
                        try:
                            pushed_at = datetime.fromisoformat(pushed_at_raw).strftime('%c')
                        except ValueError:
                            logger.error(f"Failed to parse 'imagePushedAt' as ISO format: {pushed_at_raw}")
                            pushed_at = "<unknown>"
                    else:
                        logger.warning(f"'imagePushedAt' is missing or invalid for digest {digest}.")
                        pushed_at = "<unknown>"

                    if digest and digest not in tracked_images[repo]:
                        for tag in valid_tags:
                            logger.info(f"New image detected in {repo}: {tag}")
                            return repo, tag, pushed_at

                        tracked_images[repo].add(digest)

            try:
                with open(self.HEALTH_FILE_PATH, 'w') as f:
                    f.write("healthy")
            except Exception as e:
                if os.path.exists(self.HEALTH_FILE_PATH):
                    os.remove(self.HEALTH_FILE_PATH)
                logger.error(f"Service is unhealthy: {e}")

            time.sleep(self.POLL_INTERVAL_SECONDS)
