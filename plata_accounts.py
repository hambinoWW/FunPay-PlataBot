"""Account registry for multi-account PLATA installations.

The registry is intentionally independent from Cardinal so old single-account
configs remain valid while account switching is introduced incrementally.
"""

from __future__ import annotations

import json
import os
import threading
import re
from configparser import ConfigParser
from dataclasses import asdict, dataclass
from pathlib import Path

from Utils.plata_tools import normalize_proxy


REGISTRY_PATH = Path("configs/accounts.json")
_LOCK = threading.RLock()
ACCOUNT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,31}$")


@dataclass
class AccountProfile:
    account_id: str
    name: str
    config_path: str
    enabled: bool = True
    auto_delivery_path: str | None = None
    auto_response_path: str | None = None


def _read_config(config_path: str | Path) -> ConfigParser:
    config = ConfigParser(delimiters=(":",), interpolation=None)
    config.optionxform = str
    with open(config_path, "r", encoding="utf-8") as file:
        config.read_file(file)
    return config


def _save_config(config: ConfigParser, config_path: str | Path) -> None:
    path = Path(config_path)
    temp = path.with_suffix(".tmp")
    with temp.open("w", encoding="utf-8") as file:
        config.write(file)
    os.replace(temp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def read_account_proxy(config_path: str | Path) -> str | None:
    """
    Возвращает прокси аккаунта из его конфига.

    :param config_path: путь до конфига аккаунта.
    :return: прокси аккаунта или None, если прокси не задан.
    """
    try:
        config = _read_config(config_path)
    except (OSError, ValueError):
        return None
    try:
        enabled = config["Proxy"].getboolean("enable", fallback=False) if "Proxy" in config else False
    except ValueError:
        enabled = False
    if not enabled:
        return None
    value = (config["Proxy"].get("proxy") or "").strip()
    if not value:
        return None
    try:
        return normalize_proxy(value)
    except ValueError:
        return value


def write_account_proxy(config_path: str | Path, proxy: str | None) -> str | None:
    """
    Записывает прокси аккаунта в его конфиг.

    :param config_path: путь до конфига аккаунта.
    :param proxy: прокси в формате login:password@ip:port или ip:port, None - отключить прокси.
    :return: нормализованный прокси или None, если прокси отключен.
    """
    normalized = normalize_proxy(proxy)
    config = _read_config(config_path)
    if "Proxy" not in config:
        config.add_section("Proxy")
    config["Proxy"]["enable"] = "1" if normalized else "0"
    config["Proxy"]["proxy"] = normalized or ""
    if "check" not in config["Proxy"]:
        config["Proxy"]["check"] = "0"
    _save_config(config, config_path)
    return normalized


class AccountRegistry:
    def __init__(self, path: Path | str = REGISTRY_PATH):
        self.path = Path(path)
        self._active: str | None = None

    def _read(self) -> dict:
        if not self.path.exists():
            return {"schema": 1, "active": None, "accounts": []}
        try:
            with self.path.open("r", encoding="utf-8") as file:
                value = json.load(file)
            if not isinstance(value, dict) or not isinstance(value.get("accounts"), list):
                raise ValueError
            return value
        except (OSError, ValueError, TypeError):
            return {"schema": 1, "active": None, "accounts": []}

    def _write(self, value: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        with temp.open("w", encoding="utf-8") as file:
            json.dump(value, file, ensure_ascii=False, indent=2)
        os.replace(temp, self.path)

    def list(self) -> list[AccountProfile]:
        with _LOCK:
            fields = AccountProfile.__dataclass_fields__
            result = []
            for item in self._read()["accounts"]:
                if not isinstance(item, dict) or not all(isinstance(item.get(key), str)
                                                         for key in ("account_id", "name", "config_path")):
                    continue
                try:
                    result.append(AccountProfile(**{key: value for key, value in item.items() if key in fields}))
                except (TypeError, ValueError):
                    continue
            return result

    def get(self, account_id: str) -> AccountProfile | None:
        return next((item for item in self.list() if item.account_id == account_id), None)

    def active_id(self) -> str | None:
        with _LOCK:
            return self._read().get("active")

    def set_active(self, account_id: str) -> None:
        with _LOCK:
            data = self._read()
            if not any(item.get("account_id") == account_id and item.get("enabled", True)
                       for item in data["accounts"]):
                raise KeyError(account_id)
            data["active"] = account_id
            self._write(data)

    def add(self, profile: AccountProfile) -> None:
        with _LOCK:
            data = self._read()
            if any(item.get("account_id") == profile.account_id for item in data["accounts"]):
                raise ValueError(f"Account already exists: {profile.account_id}")
            data["accounts"].append(asdict(profile))
            if not data.get("active"):
                data["active"] = profile.account_id
            self._write(data)

    def remove(self, account_id: str) -> None:
        with _LOCK:
            data = self._read()
            data["accounts"] = [item for item in data["accounts"]
                                 if item.get("account_id") != account_id]
            if data.get("active") == account_id:
                data["active"] = data["accounts"][0]["account_id"] if data["accounts"] else None
            self._write(data)

    def set_enabled(self, account_id: str, enabled: bool) -> AccountProfile:
        with _LOCK:
            data = self._read()
            selected = None
            for item in data["accounts"]:
                if item.get("account_id") == account_id:
                    item["enabled"] = enabled
                    selected = item
                    break
            if selected is None:
                raise KeyError(account_id)
            if not enabled and data.get("active") == account_id:
                replacement = next((item["account_id"] for item in data["accounts"]
                                    if item.get("enabled", True) and item["account_id"] != account_id), None)
                data["active"] = replacement
            self._write(data)
            return AccountProfile(**selected)

    def rename(self, account_id: str, name: str) -> AccountProfile:
        name = name.strip()
        if not name or len(name) > 64:
            raise ValueError("Invalid account name")
        with _LOCK:
            data = self._read()
            selected = None
            for item in data["accounts"]:
                if item.get("account_id") == account_id:
                    item["name"] = name
                    selected = item
                    break
            if selected is None:
                raise KeyError(account_id)
            self._write(data)
            fields = AccountProfile.__dataclass_fields__
            return AccountProfile(**{key: value for key, value in selected.items() if key in fields})

    def ensure_legacy_account(self, config_path: str = "configs/_main.cfg") -> AccountProfile:
        """Register the existing single-account config without modifying it."""
        with _LOCK:
            accounts = self.list()
            if accounts:
                return accounts[0]
            profile = AccountProfile("primary", "Основной аккаунт", config_path)
            self.add(profile)
            return profile

    def create_from_base(self, account_id: str, name: str, golden_key: str,
                         base_config_path: str = "configs/_main.cfg") -> AccountProfile:
        """Create a separate account config by cloning shared PLATA settings."""
        account_id = account_id.strip().lower()
        if not ACCOUNT_ID_RE.fullmatch(account_id):
            raise ValueError("Invalid account ID")
        if len(golden_key) != 32 or golden_key != golden_key.lower() or not golden_key.isalnum():
            raise ValueError("Invalid golden_key")
        if self.get(account_id):
            raise ValueError("Account already exists")

        config = ConfigParser(delimiters=(":",), interpolation=None)
        config.optionxform = str
        with open(base_config_path, "r", encoding="utf-8") as file:
            config.read_file(file)
        config["FunPay"]["golden_key"] = golden_key
        # Прокси у каждого аккаунта свой: новый профиль не наследует прокси базового аккаунта.
        if "Proxy" not in config:
            config.add_section("Proxy")
        config["Proxy"]["enable"] = "0"
        config["Proxy"]["proxy"] = ""

        config_path = Path("configs/accounts") / f"{account_id}.cfg"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        _save_config(config, config_path)

        delivery_path = config_path.with_name("auto_delivery.cfg")
        response_path = config_path.with_name("auto_response.cfg")
        for target in (delivery_path, response_path):
            if not target.exists():
                target.write_text("", encoding="utf-8")

        products_path = Path("storage/accounts") / account_id / "products"
        products_path.mkdir(parents=True, exist_ok=True)

        profile = AccountProfile(account_id, name.strip() or account_id, str(config_path), True,
                                 str(delivery_path), str(response_path))
        self.add(profile)
        return profile

    def update_golden_key(self, account_id: str, golden_key: str) -> AccountProfile:
        if len(golden_key) != 32 or golden_key != golden_key.lower() or not golden_key.isalnum():
            raise ValueError("Invalid golden_key")
        profile = self.get(account_id)
        if profile is None:
            raise KeyError(account_id)
        config = _read_config(profile.config_path)
        config["FunPay"]["golden_key"] = golden_key
        _save_config(config, profile.config_path)
        return profile
