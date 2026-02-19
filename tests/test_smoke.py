from base.ked_base import BaseRegistry
from base import ked_helm_deployer, ked_post_deploy
from ked import resolve_component_names, resolve_config_path
from messenger.telegram import TelegramMessenger


class DummyRegistry(BaseRegistry):
    def get_repository_images(self, repo):
        return []

    def get_repository_tags(self, repo):
        return []

    def monitor_repositories(self):
        return "", "", ""


def test_resolve_config_path_fallback(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("KED_CONFIG", raising=False)
    monkeypatch.delenv("KED_CONFIG_PATH", raising=False)

    root_config = tmp_path / "config.yaml"
    root_config.write_text("messenger: slack\n", encoding="utf-8")
    assert resolve_config_path() == "config.yaml"

    nested_config = tmp_path / "config" / "config.yaml"
    nested_config.parent.mkdir(parents=True, exist_ok=True)
    nested_config.write_text("messenger: slack\n", encoding="utf-8")
    assert resolve_config_path() == "config/config.yaml"


def test_component_aliases_are_resolved():
    names = resolve_component_names({"messenger": "tg", "monitor": "docker"})
    assert names["messenger_module"] == "messenger.telegram"
    assert names["registry_module"] == "registry.dockerhub"
    assert names["messenger_class"] == "TelegramMessenger"
    assert names["registry_class"] == "DockerhubRegistry"


def test_deploy_uses_passed_config_without_global_state():
    ok, message = ked_helm_deployer.deploy(None, "repo", "tag")
    assert not ok
    assert "Configuration is not loaded" in message

    ok, message = ked_helm_deployer.deploy({"jobs": []}, "repo", "tag")
    assert not ok
    assert "No job configuration found" in message


def test_telegram_keyboard_supports_mixed_registry_shapes():
    cfg = {
        "telegram": {"bot_token": "dummy", "chat_id": "1", "msg_max_size": 4000},
        "deploy_timeout": 1,
        "tag_pattern_match": r"^(.*)-(\d+\.\d+\.\d+(?:-\w+)?)$",
    }
    messenger = TelegramMessenger(cfg, DummyRegistry(cfg))

    keyboard = messenger._build_image_keyboard(
        "repo",
        [
            ("svc-1.2.3", "2026-01-01"),
            {"imageTags": ["api-2.3.4", "latest"]},
            ("latest", "2026-01-01"),
        ],
    )
    rows = keyboard.get("inline_keyboard", [])
    labels = [row[0]["text"] for row in rows]
    assert "Deploy svc-1.2.3" in labels
    assert "Deploy api-2.3.4" in labels
    assert all("latest" not in label.lower() for label in labels)


def test_post_deploy_module_import_and_tasks_map():
    assert "test_task" in ked_post_deploy.AVAILABLE_TASKS
    assert callable(ked_post_deploy.AVAILABLE_TASKS["test_task"])
