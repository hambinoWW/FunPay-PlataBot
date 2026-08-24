"""Local sales analytics for a single-user PLATA installation."""

from __future__ import annotations

import json
import os
import threading
import csv
import io
from collections import Counter
from datetime import timedelta
from datetime import datetime, timezone
from pathlib import Path


ANALYTICS_PATH = Path("storage/plata/analytics.json")
_LOCK = threading.Lock()


def _empty_data() -> dict:
    return {"schema": 1, "orders": {}, "updated_at": None}


def load_analytics() -> dict:
    if not ANALYTICS_PATH.exists():
        return _empty_data()
    try:
        with ANALYTICS_PATH.open("r", encoding="utf-8") as file:
            data = json.load(file)
        if not isinstance(data.get("orders"), dict):
            return _empty_data()
        return data
    except (OSError, ValueError, TypeError):
        return _empty_data()


def record_order(order, account_id: str = "primary") -> bool:
    """Record an order once. Returns True when a new record was added."""
    order_id = str(order.id)
    record_id = f"{account_id}:{order_id}"
    with _LOCK:
        data = load_analytics()
        if record_id in data["orders"]:
            return False

        now = datetime.now(timezone.utc).isoformat()
        data["orders"][record_id] = {
            "id": order_id,
            "account_id": account_id,
            "created_at": now,
            "price": float(order.price),
            "currency": getattr(order.currency, "name", str(order.currency)),
            "buyer": order.buyer_username,
            "description": order.description,
            "subcategory_id": getattr(order.subcategory, "id", None),
            "status": getattr(order.status, "name", str(order.status)),
        }
        data["updated_at"] = now

        ANALYTICS_PATH.parent.mkdir(parents=True, exist_ok=True)
        temp_path = ANALYTICS_PATH.with_suffix(".tmp")
        with temp_path.open("w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
        os.replace(temp_path, ANALYTICS_PATH)
        return True


def update_order_status(order, account_id: str = "primary") -> None:
    """Update an already recorded order, creating it when necessary."""
    record_order(order, account_id)
    order_id = str(order.id)
    record_id = f"{account_id}:{order_id}"
    with _LOCK:
        data = load_analytics()
        item = data["orders"].get(record_id)
        if item is None:
            return
        item["status"] = getattr(order.status, "name", str(order.status))
        item["updated_at"] = datetime.now(timezone.utc).isoformat()
        data["updated_at"] = item["updated_at"]

        ANALYTICS_PATH.parent.mkdir(parents=True, exist_ok=True)
        temp_path = ANALYTICS_PATH.with_suffix(".tmp")
        with temp_path.open("w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
        os.replace(temp_path, ANALYTICS_PATH)


def get_summary(account_id: str | None = None) -> dict:
    orders = list(load_analytics()["orders"].values())
    if account_id is not None:
        orders = [item for item in orders if item.get("account_id", "primary") == account_id]
    totals = {}
    status_counts = {}
    for order in orders:
        status = order.get("status", "UNKNOWN")
        status_counts[status] = status_counts.get(status, 0) + 1
        if status in {"REFUNDED", "UNPAID"}:
            continue
        currency = order["currency"]
        totals[currency] = round(totals.get(currency, 0) + order["price"], 2)
    return {"orders": len(orders), "totals": totals, "statuses": status_counts}


def get_recent_orders(limit: int = 5, account_id: str | None = None) -> list[dict]:
    orders = list(load_analytics()["orders"].values())
    if account_id is not None:
        orders = [item for item in orders if item.get("account_id", "primary") == account_id]
    orders.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    return orders[:max(0, limit)]


def get_report(days: int | None = None, account_id: str | None = None) -> dict:
    orders = list(load_analytics()["orders"].values())
    if account_id is not None:
        orders = [item for item in orders if item.get("account_id", "primary") == account_id]
    if days is not None:
        threshold = datetime.now(timezone.utc) - timedelta(days=days)
        orders = [item for item in orders if _parse_date(item.get("created_at")) >= threshold]
    valid = [item for item in orders if item.get("status") not in {"REFUNDED", "UNPAID"}]
    totals, accounts = {}, Counter()
    for item in valid:
        totals[item["currency"]] = round(totals.get(item["currency"], 0) + float(item["price"]), 2)
        accounts[item.get("account_id", "primary")] += 1
    return {
        "orders": len(orders), "sales": len(valid), "totals": totals,
        "refunds": sum(item.get("status") == "REFUNDED" for item in orders),
        "top_products": Counter(item.get("description") or "Без названия" for item in valid).most_common(5),
        "top_buyers": Counter(item.get("buyer") or "unknown" for item in valid).most_common(5),
        "accounts": accounts.most_common(),
    }


def _parse_date(value: str | None) -> datetime:
    try:
        return datetime.fromisoformat(value).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return datetime.min.replace(tzinfo=timezone.utc)


def export_csv(account_id: str | None = None) -> bytes:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["id", "account_id", "created_at", "price", "currency",
                                                    "buyer", "description", "status"])
    writer.writeheader()
    for item in get_recent_orders(1_000_000, account_id):
        writer.writerow({key: item.get(key, "") for key in writer.fieldnames})
    return output.getvalue().encode("utf-8-sig")
