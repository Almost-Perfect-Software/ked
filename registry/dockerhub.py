from typing import Any, Dict, List, Tuple
import os
import time
import logging
import requests
from datetime import datetime

from base.ked_base import BaseRegistry
from utils import ked_utils

logger = logging.getLogger("KED Docker Monitor")
HTTP_TIMEOUT_SECONDS = 15


class DockerhubRegistry(BaseRegistry):
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.HEALTH_FILE_PATH = "/tmp/healthz"
        self.REGISTRY_URL = self.config.get("dockerhub", {}).get("registry_url") or os.environ.get("DOCKERHUB_REGISTRY_URL")
        repos = self.config.get("dockerhub", {}).get("repositories")
        self.REPOSITORIES = repos if repos is not None else os.environ.get("DOCKERHUB_REPOSITORIES", "").split(",")
        self.POLL_INTERVAL_SECONDS = (
            self.config.get("dockerhub", {}).get("poll_interval_seconds")
            or self.config.get("dockerhub", {}).get("check_interval_seconds")
            or int(os.environ.get("POLL_INTERVAL_SECONDS", 60))
        )
        self.DOCKERHUB_USER = self.config.get("dockerhub", {}).get("username") or os.environ.get("DOCKERHUB_USER")
        self.DOCKERHUB_PASS = self.config.get("dockerhub", {}).get("password") or os.environ.get("DOCKERHUB_PASS")
        self.DOCKERHUB_API = "https://hub.docker.com/v2"

    def get_repository_images(self, repo: str) -> List[Tuple[str, str]]:
        tags_info: List[Tuple[str, str]] = []
        page = 1
        while True:
            url = f"{self.DOCKERHUB_API}/repositories/{repo}/tags?page={page}&page_size=100"
            resp = requests.get(
                url,
                auth=(self.DOCKERHUB_USER, self.DOCKERHUB_PASS),
                timeout=HTTP_TIMEOUT_SECONDS,
            )
            if resp.status_code == 401:
                logger.error(f"Authentication failed for repo: {repo}")
                return tags_info
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])
            for r in results:
                tag = r.get("name")
                pushed_at = r.get("last_updated")
                if tag and pushed_at:
                    try:
                        pushed_at_dt = datetime.fromisoformat(pushed_at.replace("Z", "+00:00"))
                        pushed_at_str = pushed_at_dt.strftime("%Y-%m-%d %H:%M:%S %Z")
                    except Exception:
                        pushed_at_str = pushed_at
                    tags_info.append((tag, pushed_at_str))
            if not data.get("next"):
                break
            page += 1
        return tags_info

    def get_repository_tags(self, repo: str) -> List[str]:
        tags: List[str] = []
        page = 1
        while True:
            url = f"{self.DOCKERHUB_API}/repositories/{repo}/tags?page={page}&page_size=100"
            resp = requests.get(
                url,
                auth=(self.DOCKERHUB_USER, self.DOCKERHUB_PASS),
                timeout=HTTP_TIMEOUT_SECONDS,
            )
            if resp.status_code == 401:
                logger.error(f"Authentication failed for repo: {repo}")
                return tags
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])
            for r in results:
                tag = r.get("name")
                if tag:
                    tags.append(tag)
            if not data.get("next"):
                break
            page += 1
        return tags

    def monitor_repositories(self) -> Tuple[str, str, str]:
        logger.info("Starting Dockerhub monitoring...")
        seen_tags: Dict[str, Dict[str, str]] = {repo: {} for repo in self.REPOSITORIES}

        logger.info("Setting baseline for tracked images...")
        for repo in self.REPOSITORIES:
            if not repo or not repo.strip():
                continue
            logger.info(f"Fetching baseline images for repository: {repo}")
            tags_info = self.get_repository_images(repo)
            for tag, pushed_date in tags_info:
                seen_tags[repo][tag] = pushed_date

        logger.info("Baseline setup complete. Monitoring for new images...")

        while True:
            for repo in self.REPOSITORIES:
                if not repo or not repo.strip():
                    continue

                if not ked_utils.is_registry_in_jobs(repo, self.config.get("jobs", [])):
                    continue

                logger.info(f"Checking repository: {repo}")
                current_tags_info = self.get_repository_images(repo)
                allowed_tags = ked_utils.find_tags_for_registry(repo, self.config.get("jobs", []))
                if not allowed_tags:
                    continue

                for tag, pushed_date in current_tags_info:
                    if not ked_utils.is_tag_allowed(tag, allowed_tags):
                        continue
                    if (tag not in seen_tags[repo]) or (seen_tags[repo][tag] != pushed_date):
                        logger.info(f"New or updated image detected in {repo}: {tag} pushed at {pushed_date}")
                        seen_tags[repo][tag] = pushed_date
                        return repo, tag, pushed_date

            try:
                with open(self.HEALTH_FILE_PATH, 'w') as f:
                    f.write("healthy")
            except Exception as e:
                if os.path.exists(self.HEALTH_FILE_PATH):
                    os.remove(self.HEALTH_FILE_PATH)
                logger.error(f"Service is unhealthy: {e}")

            time.sleep(self.POLL_INTERVAL_SECONDS)
