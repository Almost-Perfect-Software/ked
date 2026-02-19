import os
import re
import logging
import random
import string
import shutil
import yaml
from typing import Any, List, Dict, Optional

from base import ked_config_parser

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("KED Utils")

def load_helm_values(config_path: str) -> Optional[Dict[str, Any]]:
    """
    Load a YAML configuration file.

    Args:
        config_path (str): Path to the YAML file.

    Returns:
        Optional[Dict[str, Any]]: Parsed configuration as a dictionary,
                                  or None if an error occurs.
    """
    try:
        with open(config_path, "r") as file:
            logger.info(f"Loading configuration from '{config_path}'...")
            config = yaml.safe_load(file)
            logger.info("Configuration successfully loaded.")
            return config
    except FileNotFoundError:
        logger.error(f"Configuration file '{config_path}' not found.")
        return None
    except yaml.YAMLError as e:
        logger.error(f"Error parsing YAML file '{config_path}': {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error while loading config: {e}")
        return None

def normalize_registry_tags(images_or_tags: List[Any]) -> List[str]:
    """
    Normalize various registry return shapes into a flat list of string tags.
    Supports ECR (list of dicts with "imageTags"), Docker Hub (list of strings/tuples), etc.
    - Dicts: pull from item["imageTags"] if present.
    - Tuples/Lists: prefer the first string element as the tag (e.g., (tag, pushed_at)).
    - Strings: use as-is.
    - Whitespace-containing strings (likely timestamps) are ignored.
    """
    flat: List[str] = []
    if not images_or_tags:
        return flat
    for item in images_or_tags:
        # ECR: dict items with optional list under "imageTags"
        if isinstance(item, dict):
            for t in (item.get("imageTags") or []):
                if isinstance(t, str):
                    ts = t.strip()
                    if ts and " " not in ts:
                        flat.append(ts)
        # Docker Hub and others may return tuples/lists (e.g., ("tag", "pushed_at"))
        elif isinstance(item, (list, tuple)):
            if len(item) > 0 and isinstance(item[0], str):
                t = item[0].strip()
                if t and " " not in t:
                    flat.append(t)
            else:
                for t in item:
                    if isinstance(t, str):
                        ts = t.strip()
                        if ts and " " not in ts:
                            flat.append(ts)
        elif isinstance(item, str) and item:
            s = item.strip()
            if s and " " not in s:
                flat.append(s)
    return flat


def truncate_text(text: str, max_size: Optional[int] = None) -> str:
    """
    Truncate text to max_size characters, appending an ellipsis & note when truncated.
    Accepts max_size as int or None. If max_size is falsy/invalid, returns text unchanged.
    """
    try:
        max_len = int(max_size) if max_size is not None else None
    except (ValueError, TypeError):
        max_len = None
    if not max_len or len(text) <= max_len:
        return text
    suffix = "\n\n… _message truncated_"
    cut_at = max(0, max_len - len(suffix))
    return text[:cut_at] + suffix


def is_registry_in_jobs(registry_name: str, jobs: List[Dict]) -> bool:
    """
    Check if a given Registry is present in the list of jobs.

    Args:
        registry_name (str): The name of the Registry to check.
        jobs (List[Dict]): A list of job configurations.

    Returns:
        bool: True if the ECR is found in the jobs list, otherwise False.
    """
    return any(job.get("registry") == registry_name for job in jobs)


def find_tag_for_registry(registry_name: str, jobs: List[Dict]) -> Optional[str]:
    """
    Find the 'tag' associated with a given Registry in the jobs list.

    Args:
        registry_name (str): The name of the Registry to search for.
        jobs (List[Dict]): A list of job configurations.

    Returns:
        Optional[str]: The associated tag if found, otherwise None.
    """
    for job in jobs:
        if job.get("registry") == registry_name:
            return job.get("tag")  # Return the tag if found
    return None


def find_tags_for_registry(registry_name: str, jobs: List[Dict]) -> List[str]:
    """
    Finds all 'tags' associated with a given Registry in the jobs list.

    Args:
        registry_name (str): The name of the Registry to search for.
        jobs (List[Dict]): A list of job configurations.

    Returns:
        List[str]: A list of matching tags.
    """
    return [job.get("tag") for job in jobs if job.get("registry") == registry_name and job.get("tag")]


def is_tag_allowed(tag: str, allowed_patterns: List[str]) -> bool:
    """
    Check if a tag matches any of the allowed patterns.

    Args:
        tag (str): The tag to validate.
        allowed_patterns (List[str]): A list of allowed patterns (wildcards are supported).

    Returns:
        bool: True if the tag matches any pattern, otherwise False.
    """
    return any(re.fullmatch(pattern.replace("*", ".*"), tag) for pattern in allowed_patterns)


def are_tags_allowed(tags: List[str], allowed_patterns: List[str]) -> bool:
    """
    Check if all listed tags match one of the allowed patterns.

    Args:
        tags (List[str]): A list of tags to validate.
        allowed_patterns (List[str]): A list of allowed patterns (wildcards are supported).

    Returns:
        bool: True if any tag matches at least one allowed pattern, otherwise False.
    """
    return all(any(re.fullmatch(pattern.replace("*", ".*"), tag) for pattern in allowed_patterns) for tag in tags)


def filter_tags(tags: List[str]) -> List[str]:
    """
    Filters out unwanted tags from a list of image tags.

    Args:
        tags (List[str]): A list of tags to be filtered.

    Returns:
        List[str]: Filtered tags (excludes "<untagged>" and those containing "latest").
    """
    return [tag for tag in tags if tag != "<untagged>" and "latest" not in tag.lower()]


def find_job_config(config: Dict, repo_name: str, tag: str) -> Optional[Dict]:
    """
    Finds the job configuration for the specified repository and tag.

    Args:
        config (Dict): Configuration containing jobs.
        repo_name (str): The repository name to match.
        tag (str): The tag to filter jobs based on a pattern match.

    Returns:
        Optional[Dict]: The matching job configuration if found, otherwise None.
    """
    for job in config.get('jobs', []):
        if job.get('registry') == repo_name:
            job_tag_pattern = job.get('tag')
            if job_tag_pattern and re.fullmatch(job_tag_pattern.replace("*", ".*"), tag):
                return job
    return None


def get_full_name(config_file: str) -> Optional[str]:
    """
    Extracts the "fullnameOverride" value from a configuration file.

    Args:
        config_file (str): Path to the YAML configuration file.

    Returns:
        Optional[str]: The value of "fullnameOverride", or None if not found.
    """
    config = load_helm_values(config_file)
    return config and config.get("fullnameOverride")  # Simplified logic


def get_helm_values_files(job_config: Dict, base_path: str = "") -> List[str]:
    """
    Retrieves a list of Helm values file paths from a job's configuration.

    Args:
        job_config (Dict): A dictionary containing job configuration.
        base_path (str, optional): Base path where the value files should be located.

    Returns:
        List[str]: List of paths to the Helm values files, or an empty list if none exist.
    """
    values_files = job_config.get('helm_values_files', [])
    return [os.path.join(base_path, file_path) for file_path in values_files]


def purge_files(job_config: Dict, download_dir: str, new_helm_arch: str) -> None:
    """
    Deletes specified Helm values files, the default values file, and optionally clears the download directory.

    Args:
        job_config (Dict): Job configuration containing file paths.
        download_dir (str): The directory where downloaded files are stored and should be cleaned.
        new_helm_arch (str): Arch with which the Helm chart was built.

    Returns:
        None
    """
    # Remove default values file
    default_values_file = job_config.get("helm_default_values_file")
    if default_values_file:
        default_file_path = os.path.join(download_dir, default_values_file)
        if os.path.exists(default_file_path):
            os.remove(default_file_path)
            logger.info(f"Removed default values file: {default_file_path}")

    # Remove additional values files
    for file in job_config.get("helm_values_files", []):
        file_path = os.path.join(download_dir, file)
        if os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f"Removed values file: {file_path}")

    # Remove the Helm chart archive
    if os.path.exists(new_helm_arch):
        os.remove(new_helm_arch)
        logger.info(f"Removed Helm chart archive: {new_helm_arch}")

    # Remove the download directory and nested temporary content.
    if os.path.exists(download_dir):
        shutil.rmtree(download_dir, ignore_errors=True)
        logger.info(f"Removed download directory: {download_dir}")


def generate_random_string(length: int = 10) -> str:
    """
    Generates a random string of a specified length.

    Args:
        length (int): The length of the random string. Default is 8.

    Returns:
        str: A random string consisting of uppercase, lowercase, and digits.
    """
    characters = string.ascii_letters + string.digits
    random_string = ''.join(random.choices(characters, k=length))
    return random_string


def get_namespaces_from_config(config: Dict):
    """
    Reads a configuration file and returns a list of unique namespaces from the jobs section.

    Args:
        config (Dict): Configuration containing jobs.

    Returns:
        list: A list of unique namespaces found in the configuration file.

    Raises:
        FileNotFoundError: If the configuration file does not exist.
        ValueError: If the configuration file is malformed or does not contain valid data.
    """
    try:
        # Extract namespaces from the jobs section
        jobs = config.get("jobs", [])
        if not isinstance(jobs, list):
            raise ValueError("The 'jobs' section in the configuration file must be a list.")

        # Collect namespaces
        namespaces = {job.get("namespace") for job in jobs if "namespace" in job}

        # Return a sorted list of unique namespaces
        return sorted(namespaces)

    except FileNotFoundError:
        raise FileNotFoundError(f"The configuration file '{config}' does not exist.")
    except yaml.YAMLError:
        raise ValueError(f"Failed to parse the configuration file: '{config}'.")
    except Exception as e:
        raise RuntimeError(f"An unexpected error occurred: {e}")
