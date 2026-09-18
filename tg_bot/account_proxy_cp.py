"""
В данном модуле описана ПУ настройки прокси для каждого FunPay-аккаунта PLATA.
Модуль реализован в виде плагина.
"""

from __future__ import annotations

import html
import logging
from threading import Lock, Thread
from typing import TYPE_CHECKING

from telebot.types import CallbackQuery, InlineKeyboardButton as B, InlineKeyboardMarkup as K, Message

import plata_accounts
from Utils import plata_tools
from locales.localizer import Localizer
from tg_bot import MENU_CFG, utils
from tg_bot.static_keyboards import CLEAR_STATE_BTN

if TYPE_CHECKING:
    from cardinal import Cardinal

logger = logging.getLogger("TGBot")
localizer = Localizer()
_ = localizer.translate

CALLBACK_PREFIX = "pap"
ACCOUNT_PROXY_STATE = "plata_account_proxy"
ACTIVE_ACCOUNT = "*"


def init_account_proxy_cp(crd: Cardinal, *args):
    tg = crd.telegram
    bot = tg.bot
    check_results = {}
    check_lock = Lock()

    def get_runtime():
        return getattr(crd, "runtime", None)

    def get_profile(account_id: str):
        registry = getattr(crd, "account_registry", None)
        return registry.get(account_id) if registry is not None else None

    def resolve_account_id(raw: str) -> str:
        if raw == ACTIVE_ACCOUNT:
            return str(getattr(crd, "account_profile_id", "primary"))
        return raw

    def current_proxy(account_id: str) -> str | None:
        profile = get_profile(account_id)
        return plata_accounts.read_account_proxy(profile.config_path) if profile else None

    def set_account_proxy(account_id: str, proxy: str | None) -> str | None:
        runtime = get_runtime()
        if runtime is not None:
            return runtime.set_proxy(account_id, proxy)
        profile = get_profile(account_id)
        if profile is None:
            raise KeyError(account_id)
        return plata_accounts.write_account_proxy(profile.config_path, proxy)

    def sync_pool() -> None:
        runtime = get_runtime()
        if runtime is not None:
            runtime.sync_proxy_pool()

    def panel_payload(account_id: str, center_offset: int, notice: str | None = None):
        profile = get_profile(account_id)
        if profile is None:
            return None, None
        proxy = current_proxy(account_id)
        with check_lock:
            work = check_results.get(proxy) if proxy else None
        lines = ["🔌 <b>Прокси аккаунта</b>",
                 f"{html.escape(profile.name)} · <i>{html.escape(account_id)}</i>", ""]
        if notice:
            lines.extend((notice, ""))
        lines.append(f"Текущий прокси: <code>{html.escape(proxy)}</code>" if proxy
                     else "Текущий прокси: <b>не задан</b>")
        if proxy:
            lines.append(f"Проверка: "
                         f"{'✅ работает' if work else '❌ не отвечает' if work is False else '⏳ не проверялся'}")
        lines.extend(("", "Прокси применяется сразу, перезапускать аккаунт не нужно."))
        keyboard = K()
        keyboard.add(B("🔽 Выбрать из списка", callback_data=f"{CALLBACK_PREFIX}:{account_id}:list:0:{center_offset}"))
        keyboard.add(B("➕ Добавить прокси", callback_data=f"{CALLBACK_PREFIX}:{account_id}:add:{center_offset}"))
        if proxy:
            keyboard.row(B("🧪 Проверить", callback_data=f"{CALLBACK_PREFIX}:{account_id}:check:{center_offset}"),
                         B("🚫 Отключить", callback_data=f"{CALLBACK_PREFIX}:{account_id}:off:{center_offset}"))
        keyboard.add(B("⬅️ Назад", callback_data=f"{CALLBACK_PREFIX}:{account_id}:back:{center_offset}"))
        return "\n".join(lines), keyboard

    def parse_callback(data: str) -> tuple[str, str, list[str]]:
        parts = data.split(":")
        account_id = parts[1] if len(parts) > 1 else ""
        action = parts[2] if len(parts) > 2 else ""
        return account_id, action, parts[3:]

    def to_int(value, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def edit_panel(c: CallbackQuery, account_id: str, center_offset: int, notice: str | None = None) -> bool:
        text, keyboard = panel_payload(account_id, center_offset, notice)
        if text is None:
            bot.answer_callback_query(c.id, "Аккаунт не найден.", show_alert=True)
            return False
        bot.edit_message_text(text, c.message.chat.id, c.message.id, reply_markup=keyboard)
        return True

    def open_list(c: CallbackQuery, account_id: str, list_offset: int, center_offset: int) -> None:
        profile = get_profile(account_id)
        if profile is None:
            bot.answer_callback_query(c.id, "Аккаунт не найден.", show_alert=True)
            return
        pool = plata_tools.load_proxy_dict()
        current = current_proxy(account_id)
        lines = ["🔌 <b>Прокси аккаунта</b>",
                 f"{html.escape(profile.name)} · <i>{html.escape(account_id)}</i>", "",
                 "Выберите прокси из общего списка:"]
        if not pool:
            lines.append("Список пуст — добавьте прокси кнопкой «➕ Добавить прокси».")
        keyboard = K()
        page = list(pool.items())[list_offset: list_offset + MENU_CFG.PROXY_BTNS_AMOUNT]
        for proxy_id, proxy in page:
            with check_lock:
                work = check_results.get(proxy)
            e = "🟢" if work else "🟡" if work is None else "🔴"
            if proxy == current:
                keyboard.add(B(f"{e}✅ {proxy}",
                               callback_data=f"{CALLBACK_PREFIX}:{account_id}:open:{center_offset}"))
            else:
                keyboard.add(B(f"{e} {proxy}",
                               callback_data=f"{CALLBACK_PREFIX}:{account_id}:use:{proxy_id}:{center_offset}"))
        keyboard = utils.add_navigation_buttons(keyboard, list_offset, MENU_CFG.PROXY_BTNS_AMOUNT, len(page),
                                                len(pool), f"{CALLBACK_PREFIX}:{account_id}:list",
                                                extra=[center_offset])
        keyboard.add(B("⬅️ Назад", callback_data=f"{CALLBACK_PREFIX}:{account_id}:open:{center_offset}"))
        bot.edit_message_text("\n".join(lines), c.message.chat.id, c.message.id, reply_markup=keyboard)

    def use_proxy(c: CallbackQuery, account_id: str, proxy_id: int, center_offset: int) -> None:
        proxy = plata_tools.load_proxy_dict().get(proxy_id)
        if not proxy:
            bot.answer_callback_query(c.id, "Прокси не найден в списке.", show_alert=True)
            open_list(c, account_id, 0, center_offset)
            return
        try:
            set_account_proxy(account_id, proxy)
        except Exception:
            logger.debug("TRACEBACK", exc_info=True)
            bot.answer_callback_query(c.id, "Не удалось применить прокси.", show_alert=True)
            return
        bot.answer_callback_query(c.id, "Прокси применён.")
        edit_panel(c, account_id, center_offset, f"✅ Прокси применён: <code>{html.escape(proxy)}</code>")

    def check_account_proxy(c: CallbackQuery, account_id: str, center_offset: int) -> None:
        proxy = current_proxy(account_id)
        if not proxy:
            bot.answer_callback_query(c.id, "У аккаунта не задан прокси.", show_alert=True)
            return
        bot.answer_callback_query(c.id, "Проверяю прокси…")
        chat_id, message_id = c.message.chat.id, c.message.id

        def worker():
            work = plata_tools.check_proxy(plata_tools.build_proxy_dict(proxy))
            with check_lock:
                check_results[proxy] = work
            try:
                text, keyboard = panel_payload(account_id, center_offset,
                                               "✅ Прокси работает." if work else "❌ Прокси не отвечает.")
                if text is not None:
                    bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)
            except Exception:
                logger.debug("TRACEBACK", exc_info=True)

        Thread(target=worker, daemon=True).start()

    def start_add_proxy(c: CallbackQuery, account_id: str, center_offset: int) -> None:
        if get_profile(account_id) is None:
            bot.answer_callback_query(c.id, "Аккаунт не найден.", show_alert=True)
            return
        result = bot.send_message(
            c.message.chat.id,
            "Отправьте прокси в формате <u>login:password@ip:port</u> или <u>ip:port</u>.\n"
            "Отправьте <code>-</code>, чтобы отключить прокси у этого аккаунта.",
            reply_markup=CLEAR_STATE_BTN(),
        )
        tg.set_state(result.chat.id, result.id, c.from_user.id, ACCOUNT_PROXY_STATE,
                     {"account_id": account_id, "offset": center_offset, "panel_mid": c.message.id})
        bot.answer_callback_query(c.id)

    def add_proxy_message(m: Message) -> None:
        state = tg.get_state(m.chat.id, m.from_user.id)
        if not state:
            return
        data = state.get("data") or {}
        account_id = data.get("account_id", "")
        center_offset = to_int(data.get("offset"))
        value = (m.text or "").strip()
        try:
            bot.delete_message(m.chat.id, m.id)
        except Exception:
            pass
        if get_profile(account_id) is None:
            tg.clear_state(m.chat.id, m.from_user.id)
            bot.send_message(m.chat.id, "Аккаунт не найден.")
            return
        try:
            if value == "-":
                set_account_proxy(account_id, None)
                notice = "🚫 Прокси отключён."
            else:
                proxy, created = plata_tools.register_proxy(value)
                sync_pool()
                set_account_proxy(account_id, proxy)
                notice = f"✅ Прокси {'добавлен и применён' if created else 'применён'}: " \
                         f"<code>{html.escape(proxy)}</code>"
        except ValueError:
            bot.send_message(m.chat.id, "❌ Прокси должны иметь формат <u>login:password@ip:port</u> или <u>ip:port</u>.")
            return
        except Exception:
            logger.debug("TRACEBACK", exc_info=True)
            bot.send_message(m.chat.id, "❌ Не удалось применить прокси. Подробности в логе.")
            return
        tg.clear_state(m.chat.id, m.from_user.id, True)
        text, keyboard = panel_payload(account_id, center_offset, notice)
        panel_mid = to_int(data.get("panel_mid"))
        if panel_mid:
            try:
                bot.edit_message_text(text, m.chat.id, panel_mid, reply_markup=keyboard)
                return
            except Exception:
                logger.debug("TRACEBACK", exc_info=True)
        bot.send_message(m.chat.id, text, reply_markup=keyboard)

    def account_proxy_callback(c: CallbackQuery) -> None:
        account_id, action, args = parse_callback(c.data)
        account_id = resolve_account_id(account_id)
        center_offset = to_int(args[0]) if args else 0
        if action == "open":
            if edit_panel(c, account_id, center_offset):
                bot.answer_callback_query(c.id)
        elif action == "back":
            crd.telegram.refresh_account_center(c, center_offset)
            bot.answer_callback_query(c.id)
        elif action == "list":
            open_list(c, account_id, to_int(args[0]) if args else 0,
                      to_int(args[1]) if len(args) > 1 else 0)
            bot.answer_callback_query(c.id)
        elif action == "use":
            use_proxy(c, account_id, to_int(args[0]) if args else -1,
                      to_int(args[1]) if len(args) > 1 else 0)
        elif action == "check":
            check_account_proxy(c, account_id, center_offset)
        elif action == "off":
            try:
                set_account_proxy(account_id, None)
            except Exception:
                logger.debug("TRACEBACK", exc_info=True)
                bot.answer_callback_query(c.id, "Не удалось отключить прокси.", show_alert=True)
                return
            bot.answer_callback_query(c.id, "Прокси отключён.")
            edit_panel(c, account_id, center_offset, "🚫 Прокси отключён.")
        elif action == "add":
            start_add_proxy(c, account_id, center_offset)
        else:
            bot.answer_callback_query(c.id)

    tg.cbq_handler(account_proxy_callback, lambda c: c.data.startswith(f"{CALLBACK_PREFIX}:"))
    tg.msg_handler(add_proxy_message,
                   func=lambda m: tg.check_state(m.chat.id, m.from_user.id, ACCOUNT_PROXY_STATE))


BIND_TO_PRE_INIT = [init_account_proxy_cp]
