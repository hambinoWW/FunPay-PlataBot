"""Built-in command for listing paid orders older than 24 hours."""
from __future__ import annotations
import logging
import time
from datetime import datetime, timezone
from tg_bot import utils

logger = logging.getLogger("PLATA.modules.old_orders")

def _orders(account):
    start, result, locale, subcats = "", [], None, None
    while start is not None:
        for attempt in range(3):
            try:
                start, page, locale, subcats = account.get_sales(start_from=start or None, state="paid", locale=locale, sudcategories=subcats)
                break
            except Exception:
                if attempt == 2: raise
                time.sleep(1)
        for order in page:
            if (datetime.now(timezone.utc) - order.date.replace(tzinfo=timezone.utc)).total_seconds() > 86400:
                result.append(f"#{order.id}")
        time.sleep(.2)
    return result

def init(cardinal):
    if not cardinal.telegram: return
    def command(message):
        send_orders(cardinal, message)
    cardinal.telegram.msg_handler(command, commands=["old_orders"])

def send_orders(cardinal, message):
    bot = cardinal.telegram.bot
    reply = bot.reply_to(message, "Сканирую заказы старше 24 часов…")
    try: ids = _orders(cardinal.account)
    except Exception:
        logger.exception("Не удалось получить старые заказы")
        bot.edit_message_text("❌ Не удалось получить список заказов.", reply.chat.id, reply.id)
        return
    if not ids:
        bot.edit_message_text("✅ Просроченных заказов нет.", reply.chat.id, reply.id)
        return
    text = "Здравствуйте!\n\nПрошу подтвердить выполнение заказов:\n" + ", ".join(ids) + "\n\nСпасибо."
    chunks = utils.split_by_limit([text], limit=4096)
    bot.edit_message_text(f"<code>{utils.escape(chunks[0])}</code>", reply.chat.id, reply.id)
    for chunk in chunks[1:]: bot.send_message(reply.chat.id, f"<code>{utils.escape(chunk)}</code>")

BIND_TO_PRE_INIT = [init]
