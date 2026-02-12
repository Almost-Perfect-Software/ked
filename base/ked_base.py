import abc
from typing import Any, Dict, List, Tuple


class BaseRegistry(abc.ABC):
    """
    Base class for registry modules.
    Concrete registries must implement:
      - get_repository_images(repo) -> List[Any]
      - get_repository_tags(repo) -> List[str]
      - monitor_repositories() -> Tuple[str, str, str]
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config

    @abc.abstractmethod
    def get_repository_images(self, repo: str) -> List[Any]:
        raise NotImplementedError

    @abc.abstractmethod
    def get_repository_tags(self, repo: str) -> List[str]:
        raise NotImplementedError

    @abc.abstractmethod
    def monitor_repositories(self) -> Tuple[str, str, str]:
        raise NotImplementedError


class BaseMessenger(abc.ABC):
    """
    Base class for messenger modules.
    Concrete messengers must implement:
      - start_messenger()
      - send_messenger_notification(repo_name, image_tag, pushed_at)
    """

    def __init__(self, config: Dict[str, Any], registry: BaseRegistry):
        self.config = config
        self.registry = registry

    @abc.abstractmethod
    def start_messenger(self) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def send_messenger_notification(self, repo_name: str, image_tag: str, pushed_at: str) -> None:
        raise NotImplementedError
