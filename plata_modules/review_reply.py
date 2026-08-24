"""Built-in review replies with account-isolated, locked settings."""
from __future__ import annotations
import copy
import json
import threading
from pathlib import Path
from FunPayAPI.types import MessageTypes
from Utils.plata_tools import format_order_text

PATH = Path("storage/plata/modules/review_reply.json")
LOCK = threading.RLock()
DEFAULT = {"enabled": False, "watermark": True, "hidden": True,
           "replies": {str(i): {"enabled": False, "text": ""} for i in range(1, 7)}}

def _account_path(account_id):
    safe = "".join(ch for ch in str(account_id) if ch.isalnum() or ch in "_-") or "primary"
    return PATH.parent / f"review_reply_{safe}.json"

def _settings(account_id):
    with LOCK:
        path = _account_path(account_id)
        try: data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError): data = {}
        if not data:
            try: legacy = json.loads(PATH.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError): legacy = {}
            data = legacy.get("accounts", {}).get(str(account_id), {}) if isinstance(legacy, dict) else {}
        saved = data if isinstance(data, dict) else {}
        result = copy.deepcopy(DEFAULT)
        if isinstance(saved, dict):
            for key, value in saved.items():
                if key == "replies" and isinstance(value, dict):
                    for star, reply in value.items():
                        if str(star) in result["replies"] and isinstance(reply, dict):
                            result["replies"][str(star)] = {
                                "enabled": bool(reply.get("enabled", False)),
                                "text": str(reply.get("text", "")),
                            }
                else: result[key] = value
        result["enabled"] = bool(result.get("enabled", False))
        result["watermark"] = bool(result.get("watermark", True))
        result["hidden"] = bool(result.get("hidden", True))
        result["on_feedback_changed"] = bool(result.get("on_feedback_changed", False))
        if not path.exists() and saved:
            _save(account_id, result)
        return result

def _save(account_id, settings):
    with LOCK:
        path = _account_path(account_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        data = settings
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

def _event_object(cardinal, event):
    obj = getattr(event, "message", None)
    if obj is None and getattr(cardinal, "old_mode_enabled", False):
        obj = getattr(event, "chat", None)
    return obj

def on_message(cardinal, event):
    obj = _event_object(cardinal, event)
    if obj is None: return
    message_type = getattr(obj, "type", getattr(obj, "last_message_type", None))
    if message_type not in (MessageTypes.NEW_FEEDBACK, MessageTypes.FEEDBACK_CHANGED, MessageTypes.FEEDBACK_DELETED): return
    if getattr(obj, "i_am_buyer", False): return
    settings = _settings(str(getattr(cardinal, "account_profile_id", "primary")))
    if not settings.get("enabled"): return
    order = cardinal.get_order_from_object(obj)
    if order is None: return
    if message_type == MessageTypes.FEEDBACK_CHANGED and not settings.get("on_feedback_changed", False): return
    review = getattr(order, "review", None)
    if review and getattr(review, "hidden", False) and not settings.get("hidden", True): return
    stars = "6" if message_type == MessageTypes.FEEDBACK_DELETED else str(getattr(review, "stars", 0))
    item = settings.get("replies", {}).get(stars, {})
    chat_id = getattr(obj, "chat_id", getattr(obj, "id", None))
    if item.get("enabled") and item.get("text") and chat_id:
        cardinal.send_message(chat_id, format_order_text(item["text"], order), watermark=settings.get("watermark", True))

BIND_TO_NEW_MESSAGE = [on_message]
BIND_TO_LAST_CHAT_MESSAGE_CHANGED = [on_message]
