"""Plugin diagnostics and recoverable local backups."""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import importlib.util
from datetime import datetime, timezone
from pathlib import Path


BACKUP_DIR = Path("storage/plugins/backups")
AUDIT_PATH = Path("storage/plugins/audit.json")
SCOPES_PATH = Path("storage/plugins/account_scopes.json")
MISSING_DEPS_PATH = Path("storage/plugins/missing_dependencies.json")
INSTALL_TIMEOUT = 900
MISSING_MODULE_RE = re.compile(r"""No module named ['"]([A-Za-z0-9_.\-]+)['"]""")
PACKAGE_ALIASES = {
    "telebot": "pyTelegramBotAPI",
    "PIL": "Pillow",
    "cv2": "opencv-python",
    "yaml": "PyYAML",
    "bs4": "beautifulsoup4",
    "dotenv": "python-dotenv",
    "dateutil": "python-dateutil",
    "Crypto": "pycryptodome",
    "Cryptodome": "pycryptodomex",
    "attr": "attrs",
    "sklearn": "scikit-learn",
    "serial": "pyserial",
    "OpenSSL": "pyOpenSSL",
    "jwt": "PyJWT",
    "docx": "python-docx",
    "pptx": "python-pptx",
    "googleapiclient": "google-api-python-client",
    "telegram": "python-telegram-bot",
}
_MISSING_LOCK = threading.Lock()
REQUIRED_FIELDS = {"NAME", "VERSION", "DESCRIPTION", "CREDITS", "SETTINGS_PAGE", "UUID", "BIND_TO_DELETE"}


def audit_plugin(path: str | Path) -> dict:
    path = Path(path)
    result = {"file": path.name, "ok": False, "missing": [], "imports": [],
              "missing_dependencies": [], "error": None}
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        assigned = {target.id for node in tree.body if isinstance(node, (ast.Assign, ast.AnnAssign))
                    for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
                    if isinstance(target, ast.Name)}
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module.split(".")[0])
        result["imports"] = sorted(set(imports))
        local_modules = {"cardinal", "plata", "tg_bot", "Utils", "FunPayAPI", "locales", "plugins"}
        result["missing_dependencies"] = sorted(
            name for name in result["imports"]
            if name not in local_modules and importlib.util.find_spec(name) is None
        )
        result["missing"] = sorted(REQUIRED_FIELDS - assigned)
        result["ok"] = not result["missing"] and not result["missing_dependencies"]
    except Exception as error:
        result["error"] = str(error)
    return result


def audit_all(directory: str = "plugins") -> list[dict]:
    results = [audit_plugin(path) for path in sorted(Path(directory).glob("*.py"))]
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    AUDIT_PATH.write_text(json.dumps({"updated_at": datetime.now(timezone.utc).isoformat(), "plugins": results},
                                     ensure_ascii=False, indent=2), encoding="utf-8")
    return results


def extract_missing_modules(text: str | None) -> list[str]:
    """
    Извлекает имена отсутствующих модулей из текста ошибки (трейсбека).

    :param text: текст ошибки.

    :return: список корневых имен модулей без повторов.
    """
    modules = []
    for match in MISSING_MODULE_RE.finditer(text or ""):
        root = match.group(1).split(".")[0]
        if root and root not in modules:
            modules.append(root)
    return modules


def packages_for(modules: list[str]) -> list[str]:
    """
    Преобразует имена импортируемых модулей в имена пакетов PyPI.

    :param modules: имена модулей из ошибок импорта.

    :return: список пакетов для pip без повторов.
    """
    packages = []
    for module in modules:
        root = str(module).split(".")[0].strip()
        if not root or root.startswith("-"):
            continue
        package = PACKAGE_ALIASES.get(root, root)
        if package and package not in packages:
            packages.append(package)
    return packages


def install_dependencies(modules: list[str]) -> dict:
    """
    Устанавливает пакеты, которых не хватает плагину, через pip.

    :param modules: имена отсутствующих модулей.

    :return: результат установки: ok, packages, code, output.
    """
    packages = packages_for(modules)
    if not packages:
        return {"ok": False, "packages": [], "code": None, "output": "Нет модулей для установки."}
    command = [sys.executable, "-m", "pip", "install", "--no-input",
               "--disable-pip-version-check", *packages]
    env = os.environ.copy()
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    try:
        process = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                                 errors="replace", timeout=INSTALL_TIMEOUT, env=env)
        output = (process.stdout or "") + (process.stderr or "")
        code = process.returncode
    except subprocess.TimeoutExpired:
        code, output = None, f"Превышено время установки ({INSTALL_TIMEOUT} с)."
    except Exception as error:
        code, output = None, str(error)
    return {"ok": code == 0, "packages": packages, "code": code, "output": output[-4000:]}


def load_missing() -> dict[str, dict]:
    """
    Читает сохраненные сведения о нехватке библиотек у плагинов.

    Ключ — UUID плагина или file:<имя файла>.

    :return: словарь записей вида {"modules": [...], "source": str, "updated_at": str}.
    """
    try:
        data = json.loads(MISSING_DEPS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def record_missing(key: str, modules: list[str], source: str = "runtime") -> list[str]:
    """
    Запоминает модули, которых плагину не хватает.

    :param key: UUID плагина или file:<имя файла>.
    :param modules: имена отсутствующих модулей.
    :param source: источник сведений (runtime / load / audit).

    :return: список новых модулей, о которых еще не сообщалось.
    """
    modules = sorted({str(module).split(".")[0].strip() for module in modules if str(module).strip()})
    if not key or not modules:
        return []
    with _MISSING_LOCK:
        data = load_missing()
        entry = data.get(key) if isinstance(data.get(key), dict) else {}
        known = set(entry.get("modules") or [])
        new_modules = [module for module in modules if module not in known]
        entry["modules"] = sorted(known | set(modules))
        entry["source"] = source
        entry["updated_at"] = datetime.now(timezone.utc).isoformat()
        data[key] = entry
        MISSING_DEPS_PATH.parent.mkdir(parents=True, exist_ok=True)
        MISSING_DEPS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return new_modules


def clear_missing(key: str) -> None:
    """
    Убирает запись о нехватке библиотек (например, после успешной установки).

    :param key: UUID плагина или file:<имя файла>.
    """
    with _MISSING_LOCK:
        data = load_missing()
        if data.pop(key, None) is None:
            return
        MISSING_DEPS_PATH.parent.mkdir(parents=True, exist_ok=True)
        MISSING_DEPS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def collect_missing(key: str | None, path: str | Path) -> list[str]:
    """
    Собирает недостающие плагину модули: по аудиту файла и по сохраненным ошибкам.

    :param key: UUID плагина или file:<имя файла>.
    :param path: путь до файла плагина.

    :return: отсортированный список имен модулей.
    """
    modules = set(audit_plugin(path).get("missing_dependencies") or [])
    if key:
        modules.update((load_missing().get(key) or {}).get("modules") or [])
    return sorted(modules)


def backup_plugin(path: str | Path) -> Path:
    source = Path(path)
    target_dir = BACKUP_DIR / source.stem
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{source.name}"
    shutil.copy2(source, target)
    return target


def restore_latest(path: str | Path) -> Path:
    target = Path(path)
    backups = sorted((BACKUP_DIR / target.stem).glob(f"*-{target.name}"), reverse=True)
    if not backups:
        raise FileNotFoundError(target.name)
    shutil.copy2(backups[0], target)
    return backups[0]


def list_backups(path: str | Path) -> list[Path]:
    target = Path(path)
    return sorted((BACKUP_DIR / target.stem).glob(f"*-{target.name}"), reverse=True)


def load_scopes() -> dict[str, list[str]]:
    try:
        data = json.loads(SCOPES_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def set_scope(uuid: str, account_ids: list[str]) -> None:
    scopes = load_scopes()
    scopes[uuid] = sorted(set(account_ids))
    SCOPES_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCOPES_PATH.write_text(json.dumps(scopes, ensure_ascii=False, indent=2), encoding="utf-8")


def enabled_for_account(uuid: str, account_id: str) -> bool:
    scope = load_scopes().get(uuid, [])
    return not scope or account_id in scope
