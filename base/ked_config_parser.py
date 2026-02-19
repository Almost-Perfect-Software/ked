import logging
from typing import Any, Optional, Dict
import yaml
import threading

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("KED Config Parser")

# Global cached config and lock
_config_cache: Optional[Dict[str, Any]] = None
_config_lock = threading.Lock()


def load_config(config_path: str = "config/config.yaml") -> Optional[Dict[str, Any]]:
    """
    Load a YAML configuration file once and cache it in process.
    Subsequent calls return the cached dictionary.
    """
    global _config_cache
    if _config_cache is not None:
        return _config_cache

    with _config_lock:
        if _config_cache is not None:
            return _config_cache
        try:
            with open(config_path, "r") as file:
                logger.info(f"Loading configuration from '{config_path}'...")
                _config_cache = yaml.safe_load(file)
                logger.info("Configuration successfully loaded.")
                return _config_cache
        except FileNotFoundError:
            logger.error(f"Configuration file '{config_path}' not found.")
            return None
        except yaml.YAMLError as e:
            logger.error(f"Error parsing YAML file '{config_path}': {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error while loading config: {e}")
            return None


def get_config_value(key: str, config: Dict[str, Any]) -> Optional[Any]:
    if not config:
        logger.warning("Cannot fetch key from configuration as it is not loaded.")
        return None
    return config.get(key)


def get_nested_config_value(keys: str, config: Dict[str, Any], separator: str = ".") -> Optional[Any]:
    if not config:
        logger.warning("Cannot fetch nested key from configuration as it is not loaded.")
        return None
    current_value = config
    try:
        for key in keys.split(separator):
            if isinstance(current_value, dict) and key in current_value:
                current_value = current_value[key]
            else:
                logger.warning(f"Nested key '{keys}' not found in the configuration.")
                return None
        return current_value
    except Exception as e:
        logger.error(f"Error retrieving nested key '{keys}': {e}")
        return None