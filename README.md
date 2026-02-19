# KED: Kubernetes ECR Deployer

![Python Version](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Status](https://img.shields.io/badge/status-stable-brightgreen)

**KED** is a lightweight, modular ChatOps tool designed to simplify the continuous delivery pipeline. It monitors container registries (ECR, DockerHub) for new images and notifies your team via messenger (Slack, Telegram) with interactive deployment controls.

We built KED as a resource-efficient alternative to complex CD solutions like Spinnaker, focusing on simplicity, modularity, and ease of maintenance.

---

## 🚀 Key Features

- **Multi-Registry Support**: Monitors Amazon ECR and Docker Hub
* **ChatOps Integration:** Sends interactive notifications to Slack or Telegram.
   * **Deploy:** One-click deployment to your Kubernetes cluster.
   * **Ignore:** Skip specific versions directly from the chat.
* **Helm Support:** Deploys applications using Helm charts transparently.
- **Tag Pattern Matching**: Deploy only images matching specific tag patterns using regex
- **Dry Run Mode**: Test configurations without actual deployments
* **Pre/Post Hooks:** Run custom scripts before and after deployment (ideal for DB migrations, cache clearing, or metrics).
* **Modular Architecture:** Written in Python. Easily extendable to support other registries or messengers.
- **Multiple Environment Support**: Configure different settings per environment

---

## ⚙️ How It Works

1.  **Poll:** KED checks the configured repository at a set interval.
2.  **Notify:** When a new image matching your pattern is found, KED sends a message with buttons to your chat.
3.  **Action:** Upon user approval ("Deploy" button), KED initiates the Helm upgrade process.
4.  **Feedback:** Deployment status (Success/Fail) is reported back to the chat.

---

## 🛠️ Installation

### Prerequisites

* Python 3.10+
* Kubernetes Cluster (EKS or other)
* Helm 3 installed
* Access to ECR/DockerHub (credentials configured)

### Option 1: Running with Docker

The easiest way to run KED is using Docker Compose:

```bash
# 1. Clone the repository
git clone https://github.com/Almost-Perfect-Software/ked.git
cd ked

# 2. Configure your settings
mkdir -p config
cp config.example.yaml config/config.yaml
# Edit config/config.yaml with your credentials and preferences

# 3. Build and Run
docker-compose up -d
```

### Option 2: Running in Kubernetes (Recommended)

We provide Helm charts for deploying KED directly into your cluster:

```bash
helm upgrade --install ked -n ked ./charts/ked -f values.yaml --create-namespace
```

---

### Local Installation
1. Install Python 3 and pip
2. Install required dependencies:
``` bash
pip install --upgrade -r requirements.txt
```
3. Configure your settings
``` bash
mkdir -p config
cp config.example.yaml config/config.yaml
# Edit config/config.yaml with your credentials and preferences
```

4. Run the application:
``` bash
python3 ked.py
```

## 📝 Configuration

Configuration is managed via `config/config.yaml` (or `config.yaml` in repo root as fallback). Below is a reference example:
#### Global Settings
``` yaml
dry_run: true                    # Enable dry run mode (no actual deployments)
clear_on_fail: true              # Delete temporary helm chart directory on failure
environment: sandbox            # Environment name
messenger: slack                # Notification service (slack/telegram)
monitor: ecr                   # Monitor type (ecr/dockerhub)
deploy_timeout: 60             # Deployment timeout in minutes
tag_pattern_match: "^(.*)-(\d+\.\d+\.\d+(?:-\w+)?)$"  # Regex for tag matching
```
#### Registry Configurations
**Amazon ECR:**
``` yaml
ecr:
  region: eu-central-1          # AWS region
  repositories:                 # List of ECR repositories to monitor
    - "core"
    - "build"
    - "devops"
  poll_interval_seconds: 30     # Polling interval
```
**Docker Hub:**
``` yaml
dockerhub:
  registry_url: https://hub.docker.com
  repositories:
    - "username/repository"
  username: your_username
  password: your_password
  poll_interval_seconds: 30
```
#### Notification Settings
**Slack:**
``` yaml
slack:
  app_token: xapp-1-xxx          # Slack app token
  bot_token: xoxb-xxx            # Slack bot token
  channel: C123456789       # Slack channel ID
```
**Telegram:**
``` yaml
telegram:
  bot_token: 1234567890:xxx      # Telegram bot token
  chat_id: -1002667204934        # Telegram chat ID
```
#### Repository and Helm Configuration
**Source Code Repositories:**
``` yaml
repository:
  - name: bitbucket
    url: https://api.bitbucket.org/2.0/repositories/your_workspace
    username: your_username
    token: your_token
```
**Helm Repositories:**
``` yaml
helm_repo:
  - name: acme
    path: helm-repo           # S3 bucket name for S3 type
    type: s3                     # Repository type (s3/https)
  - name: bitnami
    path: https://charts.bitnami.com/bitnami
    type: https
```
#### Job Configurations
Define deployment jobs that specify which images to deploy and how:
``` yaml
jobs:
  - registry: devops                    # Registry name from above configs
    name: devops                        # Application name
    tag: "devops-ecr-test-*"                 # Tag pattern to match
    namespace: default                     # Kubernetes namespace
    helm_repo: acme                     # Helm repository name
    helm_chart: acme-node               # Helm chart name
    helm_name: acme-service1        # Helm release name
    helm_branch: src/master               # Branch for Helm values
    helm_values_repo: bitbucket          # Repository for Helm values
    helm_values_project: helm         # Project containing values
    helm_default_values_file: values.yaml # Default values file
    helm_values_files:                   # Environment-specific values
      - stage.yml
    post_deploy:                         # Optional post-deployment actions
      - test_task
```

## Interactive Commands
### Telegram Bot Commands
- `/deploy` or `/deploy_{environment}` - Manually deploy images through interactive selection
- Automatic notifications with Deploy/Skip buttons when new images are detected

### Workflow
1. KED monitors configured registries for new images
2. When a new image matching the tag pattern is found, a notification is sent
3. Users can deploy immediately or skip the deployment
4. Deployments are executed using Helm with the specified configuration
5. Status updates are sent back to the notification channel

## Security Notes
- Store sensitive credentials (tokens, passwords) as environment variables or use secure credential management
- Use IAM roles and least-privilege access for AWS ECR
- Regularly rotate API tokens and passwords
- Consider using Kubernetes secrets for sensitive configuration data


## Troubleshooting
- **Permission Issues**: Ensure proper IAM permissions for ECR access and Kubernetes cluster access
- **Network Issues**: Verify connectivity to registries and Kubernetes cluster
- **Helm Issues**: Check Helm installation and chart availability
- **Tag Matching**: Test your regex patterns with sample tags
- **Bot Authentication**: Verify Slack/Telegram bot tokens and permissions

## Architecture
``` 
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Registry      │    │      KED        │    │   Kubernetes    │
│   Monitor       │───▶│   Core Engine   │───▶│    Cluster      │
│   (ECR/Docker)  │    │                 │    │   (via Helm)    │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                              │
                              ▼
                       ┌─────────────────┐
                       │   Notifications │
                       │ (Slack/Telegram)│
                       └─────────────────┘
```

---

## 🧩 Extending KED (Modularity)

KED is designed to be developer-friendly. If you need to add a new integration (e.g., Discord notifications or Google Container Registry), check the `registry/` and `messenger/` directories.

* **Registries:** Create a class inheriting from `BaseRegistry`.
* **Messengers:** Create a class inheriting from `BaseMessenger`.

---

## 🤝 Contributing

Contributions are what make the open-source community such an amazing place to learn, inspire, and create. Any contributions you make are **greatly appreciated**.

1.  Fork the Project
2.  Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3.  Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4.  Push to the Branch (`git push origin feature/AmazingFeature`)
5.  Open a Pull Request

---

## 👟 KED Icon 

Prompt from AIs:
Create an icon for the application that deployed images from ECR to Kubernetes. The icon should depict a sneaker, the Kubernetes icon, a gear, and the word KED.

## 📄 License

Distributed under the MIT License. See `LICENSE` for more information.

---

## 📞 Contact

Project Link: [https://github.com/Almost-Perfect-Software/ked.git](https://github.com/Almost-Perfect-Software/ked)
