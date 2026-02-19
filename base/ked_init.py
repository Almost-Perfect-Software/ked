import logging
import os
import subprocess
from typing import Dict, List

try:
    from base.ked_config_parser import load_config
except ModuleNotFoundError:  # pragma: no cover - direct script execution fallback
    from ked_config_parser import load_config

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("KED Init")


def add_helm_repo(repo_name: str, repo_path: str, repo_type: str) -> bool:
    """
    Adds a Helm repository based on its type.

    Args:
        repo_name (str): The name of the Helm repository.
        repo_path (str): The URL or path to the Helm repository.
        repo_type (str): The type of the repository (e.g., 's3', 'https').

    Returns:
        bool: True if the repository was added successfully, False otherwise.
    """
    logger.info(f"Adding Helm repository '{repo_name}' of type '{repo_type}' at '{repo_path}'")

    try:
        if repo_type == "s3":
            # Add S3 repository using `helm s3` plugin
            subprocess.run(
                ["helm", "repo", "add", repo_name, f"s3://{repo_path}"], check=True
            )
        elif repo_type == "https":
            # Add HTTPS repository
            subprocess.run(["helm", "repo", "add", repo_name, repo_path], check=True)
        else:
            logger.error(f"Unsupported repository type: '{repo_type}'")
            return False
        logger.info(f"Successfully added Helm repository '{repo_name}'")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(
            f"Failed to add Helm repository '{repo_name}' of type '{repo_type}': {e}"
        )
        return False


def validate_helm_repos(repos: List[Dict]) -> List[Dict]:
    """
    Validates the structure of Helm repository configurations.

    Args:
        repos (List[Dict]): A list of Helm repository configurations.

    Returns:
        List[Dict]: A list of valid repository configurations. Logs and skips invalid entries.
    """
    valid_repos = []
    for repo in repos:
        if not all(key in repo for key in ["name", "path", "type"]):
            logger.warning(f"Skipping invalid repository configuration: {repo}")
            continue
        valid_repos.append(repo)
    return valid_repos


def main(config) -> None:
    """
    Main function to add all Helm repositories based on the configuration.

    Returns:
        None
    """
    helm_repos = config.get("helm_repo", [])
    if not helm_repos:
        logger.warning("No Helm repositories found in the configuration.")
        return

    # Validate and filter repositories
    valid_repos = validate_helm_repos(helm_repos)

    if not valid_repos:
        logger.warning("No valid Helm repositories available for addition.")
        return

    # Attempt to add each repository
    for repo in valid_repos:
        repo_name = repo["name"]
        repo_path = repo["path"]
        repo_type = repo["type"]
        add_helm_repo(repo_name, repo_path, repo_type)


if __name__ == "__main__":
    config_path = os.environ.get("KED_CONFIG") or os.environ.get("KED_CONFIG_PATH")
    if not config_path:
        config_path = "config/config.yaml" if os.path.exists("config/config.yaml") else "config.yaml"
    config = load_config(config_path)
    if not config:
        logger.error(f"Failed to load configuration from '{config_path}'.")
        raise SystemExit(1)
    main(config)
