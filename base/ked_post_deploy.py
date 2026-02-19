import logging
from typing import Callable, Dict, List, Tuple


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("KED Post Deploy")

# Initialize SSM Client
# ssm = boto3.client("ssm")

# Default Redis values
# DEFAULT_REDIS_PORT = 6379
# DEFAULT_REDIS_PASSWORD = ""


# def fetch_ssm_parameter(name: str, decrypt: bool = True) -> Optional[str]:
#     """
#     Fetch a parameter from AWS SSM Parameter Store.
#
#     Args:
#         name (str): The name of the parameter to fetch.
#         decrypt (bool): Whether to decrypt the parameter value.
#
#     Returns:
#         Optional[str]: The parameter value, or None if the parameter could not be fetched.
#     """
#     try:
#         response = ssm.get_parameter(Name=name, WithDecryption=decrypt)
#         return response.get("Parameter", {}).get("Value")
#     except Exception as e:
#         logger.error(f"Unable to fetch SSM parameter '{name}': {e}")
#         return None
#
#
# def flushall_redis_cache(repo_name: str, tag: str) -> None:
#     """
#     Flush all keys on the Redis server associated with a specific project.
#
#     Args:
#         repo_name (str): The repository name associated with the Redis.
#         tag (str): The tag associated with the repository.
#
#     Returns:
#         None
#     """
#     job_config = ked_utils.find_job_config(config, repo_name, tag)
#     project = job_config.get("project")
#
#     if not project:
#         logger.error(f"No project found for repo '{repo_name}' and tag '{tag}'")
#         return
#
#     logger.info(f"Executing FLUSHALL Redis command for project '{project}'")
#
#     # Fetch Redis connection details from AWS SSM
#     redis_host = fetch_ssm_parameter(f"/nb/{project}/REDIS_HOST")
#     redis_port = fetch_ssm_parameter(f"/nb/{project}/REDIS_PORT")
#     redis_password = fetch_ssm_parameter(f"/nb/{project}/REDIS_PASSWORD") or DEFAULT_REDIS_PASSWORD
#
#     if not redis_host:
#         error_msg = f"Redis host not configured for project '{project}'"
#         logger.error(error_msg)
#         raise ValueError(error_msg)
#
#     try:
#         redis_port = int(redis_port) if redis_port else DEFAULT_REDIS_PORT
#         logger.info(f"Connecting to Redis at {redis_host}:{redis_port}")
#
#         redis_client = redis.StrictRedis(
#             host=redis_host,
#             port=redis_port,
#             password=redis_password,
#             decode_responses=True,  # Decode responses into readable strings.
#         )
#
#         # Test Redis connection
#         redis_client.ping()
#         logger.info("Successfully connected to Redis.")
#
#         # Flush all data
#         redis_client.flushall()
#         logger.info("FLUSHALL executed: All Redis data cleared.")
#     except redis.RedisError as redis_err:
#         logger.error(f"RedisError occurred: {redis_err}")
#     except Exception as err:
#         logger.error(f"An unexpected error occurred while connecting to Redis: {err}")
#
#
# def trigger_jenkins_webhook(repo_name: str, tag: str) -> Optional[requests.Response]:
#     """
#     Trigger a Jenkins webhook for a given repository and tag.
#
#     Args:
#         repo_name (str): The repository to trigger the webhook for.
#         tag (str): The tag associated with the repository.
#
#     Returns:
#         Optional[requests.Response]: The HTTP response object if successful, otherwise None.
#     """
#     job_config = ked_utils.find_job_config(config, repo_name, tag)
#     webhook_token = job_config.get("webhook_token")
#     environment = config.get("environment")
#
#     payload = {
#         "environment": environment,
#     }
#     headers = {"Content-Type": "application/json"}
#
#     try:
#         logger.info(f"Triggering Jenkins webhook: {jenkins_url}/generic-webhook-trigger/invoke?token={webhook_token} (environment={environment})")
#         response = requests.post(
#             url=f"{jenkins_url}/generic-webhook-trigger/invoke?token={webhook_token}", json=payload, headers=headers
#         )
#         response.raise_for_status()
#         logger.info(f"Webhook triggered successfully with status code: {response.status_code}")
#         return response
#     except requests.exceptions.HTTPError as http_err:
#         logger.error(f"HTTP error occurred while triggering Jenkins: {http_err}")
#     except Exception as err:
#         logger.error(f"An unexpected error occurred while triggering Jenkins: {err}")
#     return None

def test_task(repo_name: str, tag: str) -> None:
    """
    A placeholder function used as a test task.

    Args:
        repo_name (str): Name of the repository associated with the task.
        tag (str): Tag associated with the repository.

    Returns:
        None
    """
    logger.info(f"Executing test task for repo '{repo_name}' with tag '{tag}'")


# Dictionary of available tasks


AVAILABLE_TASKS: Dict[str, Callable[[str, str], None]] = {
    "test_task": test_task,
    # "flushall_redis_cache": flushall_redis_cache,
    # "trigger_jenkins_webhook": trigger_jenkins_webhook,
}


def tasks(task_list: List[str], repo_name: str, tag: str) -> Tuple[bool, Dict[str, List[str]]]:
    """
    Execute a list of tasks for a given repository and tag.

    Args:
        task_list (List[str]): A list of task names to execute.
        repo_name (str): The repository name for the tasks.
        tag (str): The tag associated with the repository.

    Returns:
        Tuple[bool, Dict[str, List[str]]]:
            - Boolean indicating overall success.
            - Dictionary with keys "success" and "failure" listing corresponding tasks.
    """
    if not task_list:
        logger.warning(f"No tasks provided for repo '{repo_name}' with tag '{tag}'.")
        return False, {"success": [], "failure": []}

    overall_result = {"success": [], "failure": []}
    overall_success = True

    for task_name in task_list:
        logger.info(f"Starting task: '{task_name}' for repo '{repo_name}' and tag '{tag}'")
        task_function = AVAILABLE_TASKS.get(task_name)

        if not task_function:
            logger.error(f"Task '{task_name}' is not in AVAILABLE_TASKS.")
            overall_result["failure"].append(task_name)
            overall_success = False
            continue

        try:
            task_function(repo_name, tag)
            logger.info(f"Successfully completed task: '{task_name}'")
            overall_result["success"].append(task_name)
        except Exception as err:
            logger.error(f"Error occurred while executing task '{task_name}': {err}")
            overall_result["failure"].append(task_name)
            overall_success = False

    logger.info(f"Task execution completed. Results: {overall_result}")
    return overall_success, overall_result
