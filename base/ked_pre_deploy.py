import logging
from typing import Callable, Dict, List, Tuple

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("KED Pre Deploy")


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
}


def tasks(task_list: List[str], repo_name: str, tag: str) -> Tuple[bool, Dict[str, List[str]]]:
    """
    Execute a list of tasks for a given repository and tag.

    Args:
        task_list (List[str]): List of task names to execute.
        repo_name (str): Name of the repository associated with the tasks.
        tag (str): Associated repository tag.

    Returns:
        Tuple[bool, Dict[str, List[str]]]:
            - A boolean indicating overall success.
            - A dictionary containing successful and failed tasks.
    """
    if not task_list:
        logger.warning("No tasks provided to execute.")
        return False, {"success": [], "failure": []}

    overall_success = True
    overall_result = {"success": [], "failure": []}

    for task_name in task_list:
        logger.info(f"Starting task: '{task_name}' for repo '{repo_name}' and tag '{tag}'")

        task_function = AVAILABLE_TASKS.get(task_name)
        if not task_function:
            logger.error(f"Task '{task_name}' is not available in AVAILABLE_TASKS.")
            overall_result["failure"].append(task_name)
            overall_success = False  # Mark as failure and continue
            continue

        try:
            # Execute the task
            task_function(repo_name, tag)
            logger.info(f"Successfully completed task: '{task_name}'")
            overall_result["success"].append(task_name)
        except Exception as err:
            logger.error(f"Error occurred while executing task '{task_name}': {err}")
            overall_result["failure"].append(task_name)
            overall_success = False

    logger.info(f"Task execution complete. Results: {overall_result}")
    return overall_success, overall_result