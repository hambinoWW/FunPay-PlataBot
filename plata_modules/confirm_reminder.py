"""Built-in, account-scoped order confirmation reminders."""
from __future__ import annotations

import json
import threading
import time
import logging
from pathlib import Path

from FunPayAPI.types import OrderStatuses

CONFIG = Path("storage/plata/modules/confirm_reminder.json")
STATE_DIR = Path("storage/plata/modules/confirm_reminder_state")
_lock = threading.RLock()
_active: dict[str, dict] = {}
_stop_events: dict[str, threading.Event] = {}
_worker_tokens: dict[str, object] = {}
logger = logging.getLogger("PLATA.modules.confirm_reminder")
_defaults = {"enabled": True, "delay": 1, "unit": "minutes",
             "text": "Заказ выполнен. Пожалуйста, зайдите в раздел «Покупки», выберите его в списке и нажмите кнопку «Подтвердить выполнение заказа».\n"
                     "Подтвердите тут: https://Funpay.com/orders/{order_id}",
             "max_attempts": 3}

def _account_path(account_id: str) -> Path:
    safe = "".join(ch for ch in str(account_id) if ch.isalnum() or ch in "_-") or "primary"
    return CONFIG.parent / f"confirm_reminder_{safe}.json"


def _load() -> dict:
    try:
        raw = json.loads(CONFIG.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {"accounts": {}}
        if "accounts" in raw and isinstance(raw["accounts"], dict):
            return raw
        return {"accounts": {"primary": {**_defaults, **raw}}}
    except (OSError, ValueError, TypeError):
        return {"accounts": {}}


def _settings(account_id: str) -> dict:
    path = _account_path(account_id)
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        saved = _load().get("accounts", {}).get(account_id, {})
    settings = {**_defaults, **(saved if isinstance(saved, dict) else {})}
    settings["enabled"] = bool(settings.get("enabled", True))
    try: settings["delay"] = max(1, min(86400, int(settings.get("delay", 1))))
    except (TypeError, ValueError): settings["delay"] = 1
    settings["unit"] = settings.get("unit") if settings.get("unit") in {"seconds", "minutes", "hours", "days"} else "minutes"
    try: settings["max_attempts"] = max(1, min(10, int(settings.get("max_attempts", 3))))
    except (TypeError, ValueError): settings["max_attempts"] = 3
    settings["text"] = str(settings.get("text") or _defaults["text"])
    # Migrate the previous per-order URL template to the fixed instructions.
    if ("https://funpay.com/orders/{order_id}/" in str(settings.get("text", ""))
            or "https://Funpay.com/orders" == str(settings.get("text", "")).rsplit(" ", 1)[-1]):
        settings["text"] = _defaults["text"]
    if not path.exists() and saved:
        _save_account(account_id, settings)
    return settings

def _save_account(account_id: str, settings: dict) -> None:
    with _lock:
        path = _account_path(account_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)


def _save(data: dict) -> None:
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(CONFIG)


def _state_path(account_id: str) -> Path:
    safe_id = "".join(ch for ch in str(account_id) if ch.isalnum() or ch in "_-") or "primary"
    return STATE_DIR / f"{safe_id}.json"


def _save_state(account_id: str) -> None:
    path = _state_path(account_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    records = {key: value for key, value in _active.items() if value.get("account_id") == account_id}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _load_state(account_id: str) -> None:
    try:
        data = json.loads(_state_path(account_id).read_text(encoding="utf-8"))
        if isinstance(data, dict):
            _active.update({str(k): v for k, v in data.items() if isinstance(v, dict)})
    except (OSError, ValueError, TypeError):
        pass


def _seconds(data: dict) -> int:
    return max(1, int(data.get("delay", 1))) * {"seconds": 1, "minutes": 60, "hours": 3600, "days": 86400}.get(data.get("unit"), 60)


def on_new_order(cardinal, event):
    account_id = str(getattr(cardinal, "account_profile_id", "primary"))
    data = _settings(account_id)
    if not data["enabled"]:
        return
    order = cardinal.get_order_from_object(event.order)
    if order and order.chat_id:
        with _lock:
            _active[f"{account_id}:{order.id}"] = {"account_id": account_id, "order": str(order.id),
                "chat": order.chat_id, "at": time.time() + _seconds(data), "attempts": 0}
            _save_state(account_id)


def on_order_status_changed(cardinal, event):
    order = cardinal.get_order_from_object(event.order)
    if not order:
        return
    key = f"{getattr(cardinal, 'account_profile_id', 'primary')}:{order.id}"
    if order.status in (OrderStatuses.CLOSED, OrderStatuses.REFUNDED) or str(order.status) != str(OrderStatuses.PAID):
        with _lock:
            _active.pop(key, None)
            _save_state(str(getattr(cardinal, "account_profile_id", "primary")))


def loop(cardinal, token: object, stop_event: threading.Event):
    account_id = str(getattr(cardinal, "account_profile_id", "primary"))
    try:
        while getattr(cardinal, "running", True) and _worker_tokens.get(account_id) is token:
            data = _settings(account_id)
            if data["enabled"]:
                for key, item in list(_active.items()):
                    if item.get("account_id") != account_id or time.time() < item.get("at", 0):
                        continue
                    try:
                        cardinal.send_message(item["chat"], data["text"].format(order_id=item["order"]))
                    except Exception as error:
                        logger.warning("Reminder send failed: account=%s order=%s attempt=%s error=%s",
                                       account_id, item.get("order"), item.get("attempts", 0) + 1, error)
                        item["attempts"] = int(item.get("attempts", 0)) + 1
                        if item["attempts"] < int(data.get("max_attempts", 3)):
                            item["at"] = time.time() + min(300, 10 * item["attempts"])
                        else:
                            _active.pop(key, None)
                    else:
                        _active.pop(key, None)
                    with _lock:
                        _save_state(account_id)
            stop_event.wait(5)
    finally:
        with _lock:
            if _worker_tokens.get(account_id) is token:
                _worker_tokens.pop(account_id, None)


def stop(account_id: str) -> None:
    with _lock:
        event = _stop_events.get(str(account_id))
        if event:
            event.set()
        _worker_tokens.pop(str(account_id), None)


def init(cardinal):
    account_id = str(getattr(cardinal, "account_profile_id", "primary"))
    with _lock:
        _load_state(account_id)
        previous = _stop_events.get(account_id)
        if previous:
            previous.set()
        stop_event = threading.Event()
        token = object()
        _stop_events[account_id] = stop_event
        _worker_tokens[account_id] = token
    threading.Thread(target=loop, args=(cardinal, token, stop_event), daemon=True,
                     name=f"plata-confirm-reminder-{getattr(cardinal, 'account_profile_id', 'primary')}").start()


BIND_TO_POST_START = [init]
BIND_TO_NEW_ORDER = [on_new_order]
BIND_TO_ORDER_STATUS_CHANGED = [on_order_status_changed]
