import subprocess
import logging
from utils import ked_utils
from base import ked_pre_deploy
from base import ked_post_deploy
import os
import shutil
import yaml

import requests
from requests.auth import HTTPBasicAuth


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger('helm-deployer')

HTTP_TIMEOUT_SECONDS = 15


def deploy(config, repo_name, tag):
    deploy_dir = ked_utils.generate_random_string()
    if not config:
        return False, "Configuration is not loaded."
    job_config = ked_utils.find_job_config(config, repo_name, tag)
    if not job_config:
        return False, f"No job configuration found for {repo_name} and tag {tag}."
    success, output = deploy_helm_chart(config, job_config, tag, deploy_dir)
    return success, output


def update_helm_chart_with_app_version(chart, app_version, base_dir):
    """
    Pulls a Helm chart, updates the app version using `helm package --app-version`, and repackages it.

    Parameters:
    - chart (str): The URL of the Helm chart (or the chart name if it exists locally).
    - app_version (str): The new app version to set in the packaged Helm chart.
    - base_dir (str): The base directory where all files will be stored.

    Returns:
    - str: The path to the newly packaged Helm chart within the base directory.
    """
    try:
        # Ensure the base directory exists
        os.makedirs(base_dir, exist_ok=True)

        # Step 1: Pull the Helm chart into the base directory
        pull_command = ["helm", "pull", chart, "--untar", "--untardir", base_dir]
        print(f"Pulling Helm chart: {chart}")
        subprocess.check_call(pull_command)

        # Determine the extracted chart name (assumes typical Helm naming conventions)
        chart_name = os.path.basename(chart).rsplit("/", 1)[0]
        chart_path = os.path.join(base_dir, chart_name)

        if not os.path.exists(chart_path):
            raise FileNotFoundError(f"Failed to find extracted chart at {chart_path}")

        # Step 2: Read Chart.yaml to extract the chart version
        chart_yaml_path = os.path.join(chart_path, "Chart.yaml")
        if not os.path.exists(chart_yaml_path):
            raise FileNotFoundError(f"Chart.yaml not found in {chart_path}")

        with open(chart_yaml_path, "r") as f:
            chart_data = yaml.safe_load(f)
            chart_version = chart_data.get("version", "unknown")

        # Step 3: Use `helm package` with the `--app-version` flag to set the new app version
        package_command = [
            "helm", "package", chart_path,
            "--app-version", app_version,
            "--destination", base_dir
        ]
        print(f"Packaging Helm chart with new app version: {' '.join(package_command)}")
        subprocess.check_call(package_command)

        # Step 4: Determine the packaged chart path using the chart version
        packaged_chart_dest = os.path.join(base_dir, f"{chart_name}-{chart_version}.tgz")
        if not os.path.exists(packaged_chart_dest):
            raise FileNotFoundError(f"Packaged chart not found: {packaged_chart_dest}")

        # Step 5: Cleanup unpacked directory
        shutil.rmtree(chart_path, ignore_errors=True)

        print(f"Successfully packaged Helm chart saved at: {packaged_chart_dest}")
        return packaged_chart_dest

    except subprocess.CalledProcessError as helm_error:
        print(f"Helm command failed: {helm_error}")
        raise
    except Exception as e:
        print(f"Error occurred: {e}")
        raise


def fetch_value_files(config, repo, helm_project, name, branch, values_file_name, deploy_dir):
    """
    Fetches Helm values files from a remote repository and saves them to a specified directory.
    """
    repository = next((r for r in config.get("repository", []) if r.get("name") == repo), None)
    if not repository:
        raise ValueError(f"Repository '{repo}' not found in configuration")

    repository_url = repository.get("url") or repository.get("path")
    if not repository_url:
        raise ValueError(f"Repository '{repo}' is missing both 'url' and 'path'.")
    if not values_file_name:
        raise ValueError("Values file name is empty.")

    file_url = f"{repository_url}/{helm_project}/{branch}/{name}/{values_file_name}"
    username = repository.get("username")
    token = repository.get("token")
    if not username or not token:
        raise ValueError(f"Repository '{repo}' credentials are incomplete.")

    os.makedirs(deploy_dir, exist_ok=True)
    file_path = os.path.join(deploy_dir, values_file_name)
    file_dir = os.path.dirname(file_path)
    if file_dir:
        os.makedirs(file_dir, exist_ok=True)

    try:
        response = requests.get(
            file_url,
            auth=HTTPBasicAuth(username, token),
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        with open(file_path, "w", encoding="utf-8") as file:
            file.write(response.text)
        logger.info(f"Successfully downloaded {values_file_name} to {file_path}")
    except requests.RequestException as e:
        logger.error(f"Failed to fetch the values file: {e}")
        raise


def run_command(cmd, dry_run):
    """Execute a shell command."""
    cmd_str = " ".join(cmd)
    logger.info(f"Command: {cmd_str}")

    if dry_run:
        return True, "Dry run - command not executed"

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return True, result.stdout
    except subprocess.CalledProcessError as e:
        return False, f"Command failed with exit code {e.returncode}:\n{e.stderr}"


def deploy_helm_chart(config, job_config, tag, deploy_dir):
    """
    Deploy Helm chart using the specified configuration, tag, and base directory for deployment.
    """
    if not config:
        return False, "Configuration is not loaded."
    if not job_config:
        return False, "Job configuration is missing."

    overall_success = True
    dry_run = config.get("dry_run")
    clear_on_fail = config.get("clear_on_fail")
    os.makedirs(deploy_dir, exist_ok=True)

    helm_repo = job_config.get('helm_repo')
    helm_chart = job_config.get('helm_chart')
    namespace = job_config.get('namespace')
    timeout = job_config.get('timeout')
    chart_name = f"{helm_repo}/{helm_chart}" if helm_repo else helm_chart
    release_name = job_config.get('name', job_config.get('registry', '').split('/')[-1])
    helm_name = job_config.get('helm_name') or release_name
    helm_values_repo = job_config.get('helm_values_repo')
    helm_branch = job_config.get('helm_branch')
    helm_values_project = job_config.get('helm_values_project')

    if not helm_chart:
        return False, f"Helm chart is not configured for job '{release_name}'."
    if not helm_values_repo or not helm_branch or not helm_values_project:
        return False, f"Helm values source is incomplete for job '{release_name}'."

    new_helm_arch = update_helm_chart_with_app_version(chart_name, tag, deploy_dir)

    default_values_file = job_config.get("helm_default_values_file")
    if not default_values_file:
        if clear_on_fail:
            ked_utils.purge_files(job_config, deploy_dir, new_helm_arch)
        return False, f"Default Helm values file is not configured for job '{release_name}'."

    fetch_value_files(
        config,
        helm_values_repo,
        helm_values_project,
        helm_name,
        helm_branch,
        default_values_file,
        deploy_dir,
    )

    values_files = job_config.get("helm_values_files", [])
    output = ""
    success = False
    deploy_variants = values_files if values_files else [None]

    for file in deploy_variants:
        values_args = ["--wait", "--create-namespace"]
        values_args.extend(["-f", os.path.join(deploy_dir, default_values_file)])
        if file:
            fetch_value_files(
                config,
                helm_values_repo,
                helm_values_project,
                helm_name,
                helm_branch,
                file,
                deploy_dir,
            )
            values_args.extend(["-f", os.path.join(deploy_dir, file)])
            fullname = ked_utils.get_full_name(str(os.path.join(deploy_dir, file)))
            if fullname:
                release_name = fullname

        set_values = [f"version={tag}", f"image.tag={tag}"]
        cmd = ["helm", "upgrade", "--install", release_name, new_helm_arch]
        cmd.extend(values_args)
        for value in set_values:
            cmd.extend(["--set", value])
        if namespace:
            cmd.extend(["--namespace", namespace])
        if timeout:
            cmd.extend(["--timeout", f"{timeout}s"])

        success, output = run_command(cmd, dry_run)
        if not success:
            logger.error(f"Helm deployment failed: {output}")
            overall_success = False
            if clear_on_fail:
                ked_utils.purge_files(job_config, deploy_dir, new_helm_arch)
            break  # Exit loop on first failure

    if overall_success:
        logger.info(f"Helm deployment successful for {release_name}")

    if overall_success:
        ked_utils.purge_files(job_config, deploy_dir, new_helm_arch)
    return overall_success, output


def dummy_deploy_function(config, repo_name, image_tag):
    """
    Run a deployment process including pre and post-deploy steps.
    """
    try:
        logger.info(f"Deployment initiated for Repository: {repo_name}, Tag: {image_tag}")
        job_config = ked_utils.find_job_config(config, repo_name, image_tag)
        if not job_config:
            return {"success": False, "message": f"No job configuration found for {repo_name} and tag {image_tag}."}

        if job_config.get("pre_deploy"):
            pre_deploy_status, pre_deploy_message = ked_pre_deploy.tasks(job_config.get("pre_deploy"), repo_name, image_tag)
            if not pre_deploy_status:
                logger.warning(f"Pre-Deployment Tasks failed: {pre_deploy_message}")
                return {"success": False, "message": f"Pre-Deployment Failed: {pre_deploy_message}"}

        deploy_status, deploy_message = deploy(config, repo_name, image_tag)
        if not deploy_status:
            logger.warning(f"Deployment failed: {deploy_message}")
            return {"success": False, "message": f"Deployment Failed: {deploy_message}"}

        if job_config.get("post_deploy"):
            post_deploy_status, post_deploy_message = ked_post_deploy.tasks(job_config.get("post_deploy"), repo_name, image_tag)
            if not post_deploy_status:
                logger.warning(f"Post-Deployment Tasks failed: {post_deploy_message}")
                return {"success": False, "message": f"Post-Deployment Failed: {post_deploy_message}"}

        return {"success": True, "message": "Deployed Successfully!"}
    except Exception as deploy_err:
        logger.error(f"Deployment error for {repo_name}:{image_tag}: {deploy_err}", exc_info=True)
        return {"success": False, "message": f"Unexpected Error: {deploy_err}"}
