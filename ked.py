import logging
import threading
import os
import sys
import importlib
from pathlib import Path
from typing import Any, Dict

from base.ked_config_parser import load_config
from base.ked_init import main as ked_init_main

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("KED Notifier")


def dynamic_import(module_path: str, class_name: str):
    """
    Dynamically import a class from a module.
    Example: dynamic_import("messenger.slack", "SlackMessenger")
    """
    try:
        module = importlib.import_module(module_path)
        clazz = getattr(module, class_name)
        return clazz
    except ModuleNotFoundError as e:
        raise ImportError(f"Module '{module_path}' not found: {e}") from e
    except AttributeError as e:
        raise ImportError(f"Class '{class_name}' not found in '{module_path}': {e}") from e


def resolve_component_names(cfg: Dict[str, Any]) -> Dict[str, str]:
    """
    Resolve messenger and registry names and map them to module/class names.
    """
    messenger_name = (
        cfg.get("messenger")
        or os.environ.get("MESSENGER")
        or os.environ.get("messenger")
        or "slack"
    ).strip().lower()
    registry_name = (
        cfg.get("monitor")
        or os.environ.get("MONITOR")
        or os.environ.get("monitor")
        or "ecr"
    ).strip().lower()

    registry_aliases = {
        "docker": "dockerhub",
    }
    messenger_aliases = {
        "tg": "telegram",
    }
    messenger_name = messenger_aliases.get(messenger_name, messenger_name)
    registry_name = registry_aliases.get(registry_name, registry_name)

    messenger_module = f"messenger.{messenger_name}"
    registry_module = f"registry.{registry_name}"

    # Class naming convention: snake_case -> PascalCase + suffix
    def to_pascal(s: str) -> str:
        return "".join(p.capitalize() for p in s.replace("-", "_").split("_"))

    messenger_class = f"{to_pascal(messenger_name)}Messenger"
    registry_class = f"{to_pascal(registry_name)}Registry"

    return {
        "messenger_module": messenger_module,
        "messenger_class": messenger_class,
        "registry_module": registry_module,
        "registry_class": registry_class,
    }


def monitor_loop(registry, messenger):
    """
    Monitor repositories and send notifications on new images.
    """
    while True:
        repo, tag, pushed_at = registry.monitor_repositories()
        messenger.send_messenger_notification(repo, tag, pushed_at)


def resolve_config_path() -> str:
    """
    Resolve runtime config path with backward-compatible fallbacks.
    """
    explicit = os.environ.get("KED_CONFIG") or os.environ.get("KED_CONFIG_PATH")
    if explicit:
        return explicit

    for candidate in ("config/config.yaml", "config.yaml"):
        if Path(candidate).is_file():
            return candidate
    return "config/config.yaml"


if __name__ == "__main__":
    # 1) Load config ONCE
    config_path = resolve_config_path()
    logger.info(f"Loading configuration from {config_path}")
    config = load_config(config_path)
    if not config:
        logger.error("Failed to load configuration. Exiting.")
        sys.exit(1)

    # 2) Init base (helm repos etc.)
    ked_init_main(config)

    # 3) Dynamically load components
    names = resolve_component_names(config)
    try:
        RegistryClass = dynamic_import(names["registry_module"], names["registry_class"])
        MessengerClass = dynamic_import(names["messenger_module"], names["messenger_class"])
    except ImportError as e:
        logger.error(f"Component load error: {e}")
        sys.exit(1)

    # 4) Instantiate with shared config
    registry = RegistryClass(config)
    messenger = MessengerClass(config, registry)

    # 5) Start threads
    try:
        logger.info("Starting Repository Monitoring...")
        threading.Thread(target=monitor_loop, args=(registry, messenger), daemon=True).start()
    except Exception as e:
        logger.error(f"Startup error (monitor): {e}")

    try:
        logger.info("Starting Messenger Bot...")
        threading.Thread(target=messenger.start_messenger, daemon=True).start()
    except Exception as e:
        logger.error(f"Startup error (messenger): {e}")

    # Keep main thread alive
    try:
        while True:
            threading.Event().wait(3600)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
