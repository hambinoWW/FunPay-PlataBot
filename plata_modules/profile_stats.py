"""Built-in extended profile statistics, exposed through /profile_plus."""
from __future__ import annotations
import html
import plata_analytics

def init(cardinal):
    if not cardinal.telegram: return
    def command(message):
        send_stats(cardinal, message)
    cardinal.telegram.msg_handler(command, commands=["profile_plus"])

def send_stats(cardinal, message):
    account_id = str(getattr(cardinal, "account_profile_id", "primary"))
    report = plata_analytics.get_report(account_id=account_id)
    totals = ", ".join(f"{v:g} {c}" for c, v in report["totals"].items()) or "нет данных"
    text = (f"<b>Расширенная статистика PLATA</b>\n\nПродаж: <b>{report['sales']}</b>\n"
            f"Возвратов: <b>{report['refunds']}</b>\nОборот: <b>{html.escape(totals)}</b>\n"
            f"Средний чек: <b>{(report['totals'].get('RUB', 0) / report['sales'] if report['sales'] else 0):.2f} RUB</b>")
    cardinal.telegram.bot.send_message(message.chat.id, text)

BIND_TO_PRE_INIT = [init]
