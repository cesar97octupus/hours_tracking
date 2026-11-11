import json
import os
from dataclasses import asdict, dataclass, field

import keyring

from app.db import get_app_dir

SERVICE_NAME = "hours_tracking"
SCHEMA_VERSION = 1


@dataclass
class UiPrefs:
    minimize_to_tray_on_close: bool = True
    window_geometry: str | None = None
    last_picker_mode: str = "task"
    autostart_enabled: bool = True
    checkin_alarm_enabled: bool = False
    checkin_alarm_time: str = "09:00"
    checkout_alarm_enabled: bool = False
    checkout_alarm_time: str = "18:00"
    hours_alarm_enabled: bool = False
    hours_alarm_time: str = "16:00"
    filter_stage_id: int | None = None
    filter_no_hours_only: bool = False
    filter_created_after_enabled: bool = False
    filter_created_after_date: str = ""


@dataclass
class AppConfig:
    odoo_url: str
    odoo_db: str
    odoo_username: str
    schema_version: int = SCHEMA_VERSION
    ui: UiPrefs = field(default_factory=UiPrefs)


def get_config_path():
    return get_app_dir() / "config.json"


def load_config() -> AppConfig | None:
    path = get_config_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        # A crash or forced shutdown mid-write can leave a truncated/zero-filled
        # file. Quarantine it and fall back to first-run setup instead of crashing.
        path.replace(path.with_suffix(".json.bak"))
        return None
    ui_data = data.get("ui", {})
    try:
        return AppConfig(
            odoo_url=data["odoo_url"],
            odoo_db=data["odoo_db"],
            odoo_username=data["odoo_username"],
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            ui=UiPrefs(**ui_data),
        )
    except KeyError:
        path.replace(path.with_suffix(".json.bak"))
        return None


def save_config(cfg: AppConfig) -> None:
    path = get_config_path()
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(asdict(cfg), indent=2), encoding="utf-8")
    os.replace(tmp_path, path)  # atomic on both POSIX and Windows


def get_password(username: str) -> str | None:
    return keyring.get_password(SERVICE_NAME, username)


def set_password(username: str, password: str) -> None:
    keyring.set_password(SERVICE_NAME, username, password)


def delete_password(username: str) -> None:
    try:
        keyring.delete_password(SERVICE_NAME, username)
    except keyring.errors.PasswordDeleteError:
        pass
