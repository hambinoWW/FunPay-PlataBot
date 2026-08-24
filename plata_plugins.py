"""Plugin diagnostics and recoverable local backups."""

from __future__ import annotations

import ast
import json
import shutil
import importlib.util
from datetime import datetime, timezone
from pathlib import Path


BACKUP_DIR = Path("storage/plugins/backups")
AUDIT_PATH = Path("storage/plugins/audit.json")
SCOPES_PATH = Path("storage/plugins/account_scopes.json")
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
