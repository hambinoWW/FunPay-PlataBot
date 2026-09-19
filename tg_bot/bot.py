"""
В данном модуле написан Telegram бот.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from FunPayAPI import Account
from tg_bot.utils import NotificationTypes

if TYPE_CHECKING:
    from cardinal import Cardinal

import os
import sys
import time
import random
import string
import psutil
import telebot
from telebot.apihelper import ApiTelegramException
import logging
import html
import traceback
import plata_accounts
import plata_analytics
import plata_plugins

from telebot.types import InlineKeyboardMarkup as K, InlineKeyboardButton as B, Message, CallbackQuery, BotCommand, \
    InputFile
from tg_bot import utils, static_keyboards as skb, keyboards as kb, CBT
from Utils import cardinal_tools, plata_tools, updater
from locales.localizer import Localizer

logger = logging.getLogger("TGBot")
localizer = Localizer()
_ = localizer.translate
telebot.apihelper.ENABLE_MIDDLEWARE = True


class ActiveCardinalProxy:
    """Forwards panel operations to the account currently selected in Telegram."""

    def __init__(self, telegram):
        object.__setattr__(self, "_telegram", telegram)

    def __getattr__(self, name):
        return getattr(self._telegram.cardinal, name)

    def __setattr__(self, name, value):
        setattr(self._telegram.cardinal, name, value)


class TGBot:
    def __init__(self, cardinal: Cardinal):
        self.cardinal = cardinal
        self.runtime = getattr(cardinal, "runtime", None)
        if cardinal.MAIN_CFG["Telegram"]["proxy"]:
            telebot.apihelper.proxy = {"https": cardinal.MAIN_CFG["Telegram"]["proxy"],
                                       "http": cardinal.MAIN_CFG["Telegram"]["proxy"]}
        self.bot = telebot.TeleBot(self.cardinal.MAIN_CFG["Telegram"]["token"], parse_mode="HTML",
                                   allow_sending_without_reply=True, num_threads=5)

        self.file_handlers = {}  # хэндлеры, привязанные к получению файла.
        self.attempts = {}  # {user_id: attempts} - попытки авторизации в Telegram ПУ.
        self.init_messages = []  # [(chat_id, message_id)] - список сообщений о запуске TG бота.

        # {
        #     chat_id: {
        #         user_id: {
        #             "state": "state",
        #             "data": { ... },
        #             "mid": int
        #         }
        #     }
        # }
        self.user_states = {}

        # {
        #    chat_id: {
        #        utils.NotificationTypes.new_message: bool,
        #        utils.NotificationTypes.new_order: bool,
        #        ...
        #    },
        # }
        #
        self.notification_settings = utils.load_notification_settings()  # настройки уведомлений.
        self.answer_templates = utils.load_answer_templates()  # заготовки ответов.
        self.authorized_users = utils.load_authorized_users()  # авторизированные пользователи.

        self.commands = {
            "menu": "cmd_menu",
            "profile": "cmd_profile",
            "stats": "cmd_stats",
            "accounts": "cmd_accounts",
            "stats_all": "cmd_stats_all",
            "restart": "cmd_restart",
            "check_updates": "cmd_check_updates",
            "update": "cmd_update",
            "golden_key": "cmd_golden_key",
            "ban": "cmd_ban",
            "unban": "cmd_unban",
            "black_list": "cmd_black_list",
            "upload_chat_img": "cmd_upload_chat_img",
            "upload_offer_img": "cmd_upload_offer_img",
            "upload_plugin": "cmd_upload_plugin",
            "test_lot": "cmd_test_lot",
            "logs": "cmd_logs",
            "about": "cmd_about",
            "sys": "cmd_sys",
            "get_backup": "cmd_get_backup",
            "create_backup": "cmd_create_backup",
            "upload_backup": "cmd_upload_backup",
            "del_logs": "cmd_del_logs",
            "power_off": "cmd_power_off",
            "watermark": "cmd_watermark",
            "analytics": "cmd_analytics",
            "plugins_audit": "cmd_plugins_audit",
            "plugin_copy": "cmd_plugin_copy",
            "plugin_recover": "cmd_plugin_recover",
            "plugin_access": "cmd_plugin_access",
            "plugin_help": "cmd_plugin_help",
            "reminder_text": "cmd_reminder_text",
            "old_orders": "cmd_old_orders",
            "profile_plus": "cmd_profile_plus",
            "review_reply": "cmd_review_reply",
        }
        self.__default_notification_settings = {
            utils.NotificationTypes.ad: 1,
            utils.NotificationTypes.announcement: 1
        }

    # User states
    def get_state(self, chat_id: int, user_id: int) -> dict | None:
        """
        Получает текущее состояние пользователя.

        :param chat_id: id чата.
        :param user_id: id пользователя.

        :return: данные состояния пользователя.
        """
        try:
            return self.user_states[chat_id][user_id]
        except KeyError:
            return None

    def set_state(self, chat_id: int, message_id: int, user_id: int, state: str, data: dict | None = None):
        """
        Устанавливает состояние для пользователя.

        :param chat_id: id чата.
        :param message_id: id сообщения, после которого устанавливается данное состояние.
        :param user_id: id пользователя.
        :param state: состояние.
        :param data: доп. данные.
        """
        if chat_id not in self.user_states:
            self.user_states[chat_id] = {}
        self.user_states[chat_id][user_id] = {"state": state, "mid": message_id, "data": data or {}}

    def clear_state(self, chat_id: int, user_id: int, del_msg: bool = False) -> int | None:
        """
        Очищает состояние пользователя.

        :param chat_id: id чата.
        :param user_id: id пользователя.
        :param del_msg: удалять ли сообщение, после которого было обозначено текущее состояние.

        :return: ID сообщения-инициатора или None, если состояние и так было пустое.
        """
        try:
            state = self.user_states[chat_id][user_id]
        except KeyError:
            return None

        msg_id = state.get("mid")
        del self.user_states[chat_id][user_id]
        if del_msg:
            try:
                self.bot.delete_message(chat_id, msg_id)
            except:
                pass
        return msg_id

    def check_state(self, chat_id: int, user_id: int, state: str) -> bool:
        """
        Проверяет, является ли состояние указанным.

        :param chat_id: id чата.
        :param user_id: id пользователя.
        :param state: состояние.

        :return: True / False
        """
        try:
            return self.user_states[chat_id][user_id]["state"] == state
        except KeyError:
            return False

    # Notification settings
    def is_notification_enabled(self, chat_id: int | str, notification_type: str) -> bool:
        """
        Включен ли указанный тип уведомлений в указанном чате?

        :param chat_id: ID Telegram чата.
        :param notification_type: тип уведомлений.
        """
        if notification_type in (utils.NotificationTypes.announcement, utils.NotificationTypes.ad):
            return True
        try:
            return bool(self.notification_settings[str(chat_id)][notification_type])
        except KeyError:
            return False

    def toggle_notification(self, chat_id: int, notification_type: str) -> bool:
        """
        Переключает указанный тип уведомлений в указанном чате и сохраняет настройки уведомлений.

        :param chat_id: ID Telegram чата.
        :param notification_type: тип уведомлений.

        :return: вкл / выкл указанный тип уведомлений в указанном чате.
        """
        if notification_type in (utils.NotificationTypes.announcement, utils.NotificationTypes.ad):
            return True
        chat_id = str(chat_id)
        if chat_id not in self.notification_settings:
            self.notification_settings[chat_id] = {}

        self.notification_settings[chat_id][notification_type] = not self.is_notification_enabled(chat_id,
                                                                                                  notification_type)
        utils.save_notification_settings(self.notification_settings)
        return self.notification_settings[chat_id][notification_type]

    # handler binders
    def is_file_handler(self, m: Message):
        return self.get_state(m.chat.id, m.from_user.id) and m.content_type in ["photo", "document"]

    def file_handler(self, state, handler):
        self.file_handlers[state] = handler

    def run_file_handlers(self, m: Message):
        if (state := self.get_state(m.chat.id, m.from_user.id)) is None \
                or state["state"] not in self.file_handlers:
            return
        try:
            self.file_handlers[state["state"]](m)
        except:
            logger.error(_("log_tg_handler_error"))
            logger.debug("TRACEBACK", exc_info=True)

    def msg_handler(self, handler, **kwargs):
        """
        Регистрирует хэндлер, срабатывающий при новом сообщении.

        :param handler: хэндлер.
        :param kwargs: аргументы для хэндлера.
        """
        bot_instance = self.bot

        @bot_instance.message_handler(**kwargs)
        def run_handler(message: Message):
            try:
                handler(message)
            except:
                self.report_missing_dependency(handler, message.chat.id)
                logger.error(_("log_tg_handler_error"))
                logger.debug("TRACEBACK", exc_info=True)

    def cbq_handler(self, handler, func, **kwargs):
        """
        Регистрирует хэндлер, срабатывающий при новом callback'е.

        :param handler: хэндлер.
        :param func: функция-фильтр.
        :param kwargs: аргументы для хэндлера.
        """
        bot_instance = self.bot

        @bot_instance.callback_query_handler(func, **kwargs)
        def run_handler(call: CallbackQuery):
            try:
                handler(call)
            except:
                chat = getattr(call.message, "chat", None)
                self.report_missing_dependency(handler, getattr(chat, "id", None))
                logger.error(_("log_tg_handler_error"))
                logger.debug("TRACEBACK", exc_info=True)

    def report_missing_dependency(self, handler, chat_id: int | None = None) -> bool:
        """
        Проверяет, вызвано ли последнее исключение отсутствием Python-библиотеки,
        и предлагает установить ее одной кнопкой.

        :param handler: хэндлер, в котором произошла ошибка.
        :param chat_id: чат, куда отправить предложение об установке.

        :return: True, если ошибка связана с отсутствующей библиотекой.
        """
        modules = plata_plugins.extract_missing_modules(traceback.format_exc())
        if not modules:
            return False
        key = getattr(handler, "plugin_uuid", None) or self.plugin_key_for_handler(handler)
        if not key:
            return False
        new_modules = plata_plugins.record_missing(key, modules, "runtime")
        if new_modules:
            self.notify_missing_dependency(key, new_modules, chat_id)
        return True

    def plugin_key_for_handler(self, handler) -> str | None:
        """
        Определяет UUID плагина по модулю хэндлера Telegram-панели.

        :param handler: хэндлер, зарегистрированный плагином.

        :return: UUID плагина или None.
        """
        module = getattr(handler, "__module__", None) or ""
        if not module.startswith("plugins."):
            return None
        file_name = f"{module.split('.', 1)[1]}.py"
        for uuid, plugin in self.cardinal.plugins.items():
            if os.path.basename(plugin.path) == file_name:
                return uuid
        return None

    def notify_missing_dependency(self, key: str, modules: list[str],
                                  chat_id: int | None = None) -> None:
        """
        Сообщает, что плагину не хватает библиотек, с кнопкой установки.

        :param key: UUID плагина или file:<имя файла>.
        :param modules: имена отсутствующих модулей.
        :param chat_id: чат для сообщения (None — все чаты уведомлений).
        """
        plugin = self.cardinal.plugins.get(key)
        name = plugin.name if plugin is not None else key.split(":", 1)[-1]
        packages = ", ".join(plata_plugins.packages_for(modules))
        text = _("pl_missing_deps_notify", utils.escape(name), utils.escape(packages))
        keyboard = K().add(B(_("pl_install_deps"), None, f"{CBT.INSTALL_PLUGIN_DEPS}:{key}"))
        if chat_id is None:
            self.send_notification(text, keyboard, notification_type=NotificationTypes.critical)
            return
        try:
            self.bot.send_message(chat_id, text, reply_markup=keyboard)
        except Exception:
            logger.debug("TRACEBACK", exc_info=True)

    def notify_pending_missing_dependencies(self) -> None:
        """
        Напоминает в уведомлениях о плагинах, которым до сих пор не хватает библиотек.
        """
        entries = [(key, sorted(set(data.get("modules") or [])))
                   for key, data in plata_plugins.load_missing().items()]
        entries = [(key, modules) for key, modules in entries if modules]
        if not entries:
            return
        lines = ["<b>📦 Плагинам не хватает библиотек</b>", ""]
        keyboard = K()
        for key, modules in entries[:8]:
            plugin = self.cardinal.plugins.get(key)
            name = plugin.name if plugin is not None else key.split(":", 1)[-1]
            packages = ", ".join(plata_plugins.packages_for(modules))
            lines.append(f"• <b>{utils.escape(name)}</b>: <code>{utils.escape(packages)}</code>")
            keyboard.add(B(f"📦 {name}"[:48], None, f"{CBT.INSTALL_PLUGIN_DEPS}:{key}"))
        lines.append("")
        lines.append("Нажмите кнопку, чтобы установить зависимости.")
        self.send_notification("\n".join(lines), keyboard,
                               notification_type=NotificationTypes.important_announcement)

    def mdw_handler(self, handler, **kwargs):
        """
        Регистрирует промежуточный хэндлер.

        :param handler: хэндлер.
        :param kwargs: аргументы для хэндлера.
        """
        bot_instance = self.bot

        @bot_instance.middleware_handler(**kwargs)
        def run_handler(bot, update):
            try:
                handler(bot, update)
            except:
                logger.error(_("log_tg_handler_error"))
                logger.debug("TRACEBACK", exc_info=True)

    # Система свой-чужой 0_0
    def setup_chat_notifications(self, bot: TGBot, m: Message):
        """
        Устанавливает настройки уведомлений по умолчанию в новом чате.
        """
        if str(m.chat.id) in self.notification_settings and m.from_user.id in self.authorized_users and \
                self.is_notification_enabled(m.chat.id, NotificationTypes.critical):
            return
        elif str(m.chat.id) in self.notification_settings and m.from_user.id in self.authorized_users and not \
                self.is_notification_enabled(m.chat.id, NotificationTypes.critical):
            self.notification_settings[str(m.chat.id)][NotificationTypes.critical] = 1
            utils.save_notification_settings(self.notification_settings)
            return
        elif str(m.chat.id) not in self.notification_settings:
            self.notification_settings[str(m.chat.id)] = self.__default_notification_settings.copy()
            utils.save_notification_settings(self.notification_settings)

    def reg_admin(self, m: Message):
        """
        Проверяет, есть ли пользователь в списке пользователей с доступом к ПУ TG.
        """
        lang = m.from_user.language_code
        if m.chat.type != "private" or (self.attempts.get(m.from_user.id, 0) >= 5) or m.text is None:
            return
        if not self.cardinal.block_tg_login and \
                cardinal_tools.check_password(m.text, self.cardinal.MAIN_CFG["Telegram"]["secretKeyHash"]):
            self.send_notification(text=_("access_granted_notification", m.from_user.username, m.from_user.id),
                                   notification_type=NotificationTypes.critical, pin=True)
            self.authorized_users[m.from_user.id] = {}
            utils.save_authorized_users(self.authorized_users)
            if str(m.chat.id) not in self.notification_settings or not self.is_notification_enabled(m.chat.id,
                                                                                                    NotificationTypes.critical):
                self.notification_settings[str(m.chat.id)] = self.__default_notification_settings.copy()
                self.notification_settings[str(m.chat.id)][NotificationTypes.critical] = 1
                utils.save_notification_settings(self.notification_settings)
            text = _("access_granted", language=lang)
            kb_links = None
            logger.warning(_("log_access_granted", m.from_user.username, m.from_user.id))
        else:
            self.attempts[m.from_user.id] = self.attempts.get(m.from_user.id, 0) + 1
            text = _("access_denied", m.from_user.username, language=lang)
            kb_links = None
            logger.warning(_("log_access_attempt", m.from_user.username, m.from_user.id))
        self.bot.send_message(m.chat.id, text, reply_markup=kb_links)

    def ignore_unauthorized_users(self, c: CallbackQuery):
        """
        Игнорирует callback'и от не авторизированных пользователей.
        """
        logger.warning(_("log_click_attempt", c.from_user.username, c.from_user.id, c.message.chat.username,
                         c.message.chat.id))
        self.attempts[c.from_user.id] = self.attempts.get(c.from_user.id, 0) + 1
        if self.attempts[c.from_user.id] <= 5:
            self.bot.answer_callback_query(c.id, _("adv_fpc", language=c.from_user.language_code), show_alert=True)
        return

    # Команды
    def send_settings_menu(self, m: Message):
        """
        Отправляет основное меню настроек (новым сообщением).
        """
        self.bot.send_message(m.chat.id, self._main_menu_text(), reply_markup=skb.SETTINGS_SECTIONS())

    def _main_menu_text(self) -> str:
        account = getattr(self.cardinal, "account", None)
        username = html.escape(getattr(account, "username", None) or "не подключён")
        account_id = str(getattr(self.cardinal, "account_profile_id", "primary"))
        account_label = html.escape(self._account_display_name(account_id))
        balance = self.cardinal.balance
        balance_text = "нет данных"
        if balance is not None:
            total_rub = getattr(balance, "total_rub", None)
            if isinstance(total_rub, (int, float)):
                balance_text = f"{total_rub:g} RUB"
        today = plata_analytics.get_report(1, getattr(self.cardinal, "account_profile_id", "primary"))
        turnover = ", ".join(f"{value:g} {currency}" for currency, value in today["totals"].items()) or "нет продаж"
        runtime = getattr(self, "runtime", None)
        errors = len(getattr(runtime, "errors", {})) if runtime else 0
        offline = self._selected_account_offline()
        lines = [
            "<b>PLATA · Рабочая панель</b>",
            (f"🟠 Настройка без запуска · ошибок <b>{errors}</b>" if offline
             else f"🟢 Система онлайн · ошибок <b>{errors}</b>"),
            "",
            f"👤 <b>@{username}</b> · <b>{account_label}</b>",
            f"💰 Баланс: <b>{balance_text}</b>",
            f"🛒 Сегодня: <b>{today['sales']}</b> продаж",
            f"📈 Оборот: <b>{html.escape(turnover)}</b>",
            f"↩️ Возвраты: <b>{today['refunds']}</b>",
        ]
        if offline:
            lines.extend(("", "⚠️ Аккаунт не запущен — изменения сохраняются. "
                              "Запуск: 👤 Аккаунты → ▶️ Запустить."))
        lines.extend(("", "Выберите раздел:"))
        return "\n".join(lines)

    @staticmethod
    def _account_display_name(account_id: str) -> str:
        """Human-readable account label; internal IDs remain unchanged."""
        return "Основной аккаунт" if str(account_id) == "primary" else str(account_id)

    def _selected_account_offline(self) -> bool:
        """True, если панель нацелена на остановленный аккаунт (режим настройки)."""
        runtime = getattr(self, "runtime", None)
        if runtime is None or not hasattr(runtime, "is_offline"):
            return False
        account_id = str(getattr(self.cardinal, "account_profile_id", "primary"))
        try:
            return bool(runtime.is_offline(account_id))
        except Exception:
            return False

    def send_profile(self, m: Message):
        """
        Отправляет статистику аккаунта.
        """
        if self._selected_account_offline():
            self.bot.send_message(
                m.chat.id,
                "⚠️ Аккаунт не запущен — профиль FunPay появится после запуска.\n"
                "Запустите его в разделе 👤 Аккаунты.",
                reply_markup=K().add(B("⬅️ Назад", callback_data="plata_menu:back")),
            )
            return
        self.bot.send_message(m.chat.id, utils.generate_profile_text(self.cardinal),
                              reply_markup=K().row(B("🔄 Обновить", callback_data=CBT.UPDATE_PROFILE),
                                                   B("⬅️ Назад", callback_data="plata_menu:back")))

    def send_sales_stats(self, m: Message):
        """Sends locally collected PLATA sales statistics."""
        account_id = getattr(self.cardinal, "account_profile_id", "primary")
        summary = plata_analytics.get_summary(account_id)
        totals = summary["totals"]
        totals_text = "\n".join(
            f"• <code>{amount:g}</code> {html.escape(currency)}"
            for currency, amount in sorted(totals.items())
        ) or "• нет данных"
        statuses = summary["statuses"]
        status_names = {
            "PAID": "оплачено",
            "CLOSED": "завершено",
            "REFUNDED": "возвращено",
            "PARTIALLY_REFUNDED": "частичный возврат",
            "UNPAID": "не оплачено",
        }
        statuses_text = ", ".join(
            f"{status_names.get(status, status.lower())}: <b>{count}</b>"
            for status, count in sorted(statuses.items())
        ) or "нет данных"

        recent_lines = []
        for order in plata_analytics.get_recent_orders(5, account_id):
            description = html.escape(str(order.get("description") or "Без названия"))
            if len(description) > 60:
                description = description[:57] + "..."
            recent_lines.append(
                f"• <code>#{html.escape(order['id'])}</code> — "
                f"<code>{order['price']:g}</code> {html.escape(order['currency'])}\n"
                f"  {description}"
            )
        recent_text = "\n".join(recent_lines) or "• заказов пока нет"

        text = (
            "<b>Статистика PLATA</b>\n\n"
            f"Заказов учтено: <b>{summary['orders']}</b>\n\n"
            f"Статусы: {statuses_text}\n\n"
            f"<b>Оборот:</b>\n{totals_text}\n\n"
            f"<b>Последние продажи:</b>\n{recent_text}"
        )
        self.bot.send_message(
            m.chat.id,
            text,
            reply_markup=K().add(B("⬅️ Назад", callback_data="plata_menu:back")),
        )

    def send_all_sales_stats(self, m: Message):
        registry = getattr(self.cardinal, "account_registry", None)
        if registry is None:
            self.bot.send_message(m.chat.id, "Реестр аккаунтов PLATA не инициализирован.")
            return

        grand_totals = {}
        total_orders = 0
        lines = ["<b>Общая аналитика PLATA</b>", ""]
        for profile in registry.list():
            summary = plata_analytics.get_summary(profile.account_id)
            total_orders += summary["orders"]
            for currency, amount in summary["totals"].items():
                grand_totals[currency] = round(grand_totals.get(currency, 0) + amount, 2)
            amounts = ", ".join(f"<code>{amount:g}</code> {html.escape(currency)}"
                                for currency, amount in sorted(summary["totals"].items())) or "нет оборота"
            lines.append(f"• <b>{html.escape(profile.name)}</b>: "
                         f"{summary['orders']} заказов, {amounts}")

        totals_text = ", ".join(f"<code>{amount:g}</code> {html.escape(currency)}"
                                for currency, amount in sorted(grand_totals.items())) or "нет данных"
        lines.extend(("", f"Всего заказов: <b>{total_orders}</b>", f"Общий оборот: {totals_text}"))
        self.bot.send_message(
            m.chat.id,
            "\n".join(lines),
            reply_markup=K().add(B("⬅️ Назад", callback_data="plata_menu:back")),
        )

    def send_accounts(self, m: Message):
        """Shows the PLATA account center."""
        text, keyboard = self._account_center_payload(0)
        self.bot.send_message(m.chat.id, text, reply_markup=keyboard)

    def _account_center_payload(self, offset: int = 0):
        registry = getattr(self.cardinal, "account_registry", None)
        if registry is None:
            return "Реестр аккаунтов PLATA не инициализирован.", None
        active_id = registry.active_id()
        runtime = getattr(self, "runtime", None)
        lines = ["<b>Центр аккаунтов PLATA</b>",
                 "Управление подключением, статистикой и профилями.", ""]
        keyboard = K()
        keyboard.add(B("➕ Добавить аккаунт", callback_data="pa:add"))
        profiles = registry.list()
        page_size = 4
        offset = max(0, min(offset, max(0, len(profiles) - 1)))
        page_profiles = profiles[offset:offset + page_size]
        for profile in page_profiles:
            marker = "●" if profile.account_id == active_id else "○"
            instance = runtime.get(profile.account_id) if runtime else None
            if not profile.enabled:
                state = "отключён"
            elif instance is not None:
                state = "работает"
            elif runtime and profile.account_id in runtime.errors:
                state = "ошибка запуска"
            elif runtime and profile.account_id == active_id and runtime.is_offline(profile.account_id):
                state = "настройка (не запущен)"
            else:
                state = "ожидает запуска"
            username = getattr(getattr(instance, "account", None), "username", None)
            summary = plata_analytics.get_summary(profile.account_id)
            totals = ", ".join(f"{amount:g} {currency}" for currency, amount in sorted(summary["totals"].items()))
            balance = getattr(instance, "balance", None)
            total_rub = getattr(balance, "total_rub", None)
            balance_text = f"{total_rub:g} RUB" if isinstance(total_rub, (int, float)) else "нет данных"
            active_sales = getattr(getattr(instance, "account", None), "active_sales", None)
            label = self._account_display_name(profile.account_id)
            lines.append(f"{marker} <b>{html.escape(profile.name)}</b> "
                         f"<i>{html.escape(label)}</i> — {state}")
            lines.append(f"   @{html.escape(username or 'не подключён')} · "
                         f"баланс {balance_text}")
            lines.append(f"   {summary['orders']} заказов · оборот {html.escape(totals or 'нет данных')}"
                         f" · активных продаж {active_sales if active_sales is not None else '—'}")
            proxy = plata_accounts.read_account_proxy(profile.config_path)
            lines.append(f"   🔌 Прокси: <code>{html.escape(proxy)}</code>" if proxy else "   🔌 Прокси: не задан")
            if runtime and profile.account_id in runtime.errors:
                lines.append(f"   Ошибка: <code>{html.escape(runtime.errors[profile.account_id][:140])}</code>")
            action = profile.account_id
            if instance is not None and profile.enabled:
                keyboard.row(
                    B(f"{marker} Выбрать", callback_data=f"pa:{action}:select:{offset}"),
                    B("📊 Статистика", callback_data=f"pa:{action}:stats:{offset}"),
                )
                keyboard.row(
                    B("🔄 Перезапустить", callback_data=f"pa:{action}:restart:{offset}"),
                    B("⏹ Отключить", callback_data=f"pa:{action}:disable:{offset}"),
                )
                keyboard.add(B("🔌 Прокси", callback_data=f"pap:{action}:open:{offset}"))
            elif profile.enabled:
                keyboard.row(B("⚙️ Настроить", callback_data=f"pa:{action}:configure:{offset}"),
                             B("▶️ Запустить", callback_data=f"pa:{action}:enable:{offset}"))
                keyboard.row(B("🔑 Golden key", callback_data=f"pa:{action}:key:{offset}"),
                             B("🔌 Прокси", callback_data=f"pap:{action}:open:{offset}"))
            else:
                keyboard.row(B("▶️ Включить", callback_data=f"pa:{action}:enable:{offset}"),
                             B("🔑 Golden key", callback_data=f"pa:{action}:key:{offset}"))
                keyboard.add(B("🔌 Прокси", callback_data=f"pap:{action}:open:{offset}"))
        navigation = []
        if offset > 0:
            navigation.append(B("◀️", callback_data=f"pp:{max(0, offset - page_size)}"))
        if offset + page_size < len(profiles):
            navigation.append(B("▶️", callback_data=f"pp:{offset + page_size}"))
        if navigation:
            keyboard.row(*navigation)
        keyboard.row(B("📊 Общая статистика", callback_data="plata_menu:stats_all"),
                     B("🩺 Проверка аккаунтов", callback_data="plata_menu:health"))
        keyboard.add(B("⬅️ В главное меню", callback_data=CBT.MAIN))
        lines.extend(("", "● — активный аккаунт панели",
                      "⚙️ Настроить — управление остановленным аккаунтом (например, если golden key перестал действовать)."))
        return "\n".join(lines), keyboard

    def refresh_account_center(self, call: CallbackQuery, offset: int = 0):
        text, keyboard = self._account_center_payload(offset)
        try:
            self.bot.edit_message_text(text, call.message.chat.id, call.message.id, reply_markup=keyboard)
        except ApiTelegramException as error:
            # Telegram returns 400 when a repeated action produces identical
            # text and markup. The state is already correct in this case.
            description = getattr(error, "result_json", {}).get("description", "")
            if "message is not modified" not in description.lower():
                raise

    def account_center_page(self, call: CallbackQuery):
        try:
            offset = int(call.data.split(":", 1)[1])
        except (ValueError, IndexError):
            offset = 0
        self.refresh_account_center(call, offset)
        self.bot.answer_callback_query(call.id)

    def add_account_flow_callback(self, call: CallbackQuery):
        result = self.bot.send_message(
            call.message.chat.id,
            "Введите короткое название аккаунта PLATA, например main или shop_2.\n"
            "Это имя используется только внутри PLATA (2–32 символа: латиница, цифры, _ или -).",
            reply_markup=skb.CLEAR_STATE_BTN(),
        )
        self.set_state(call.message.chat.id, result.id, call.from_user.id, "plata_add_account", {"step": "id"})
        self.bot.answer_callback_query(call.id)

    def add_account_flow_text(self, message: Message):
        state = self.get_state(message.chat.id, message.from_user.id)
        if not state:
            return
        value = (message.text or "").strip()
        data = state["data"]
        try:
            self.bot.delete_message(message.chat.id, message.id)
        except Exception:
            pass
        if data.get("step") == "id":
            if not re.fullmatch(r"[A-Za-z0-9_-]{2,32}", value):
                self.bot.send_message(message.chat.id, "Некорректный ID. Используйте 2–32 символа: латиница, цифры, _ или -.")
                return
            data.update(step="key", account_id=value)
            result = self.bot.send_message(message.chat.id, "Введите golden key аккаунта FunPay.", reply_markup=skb.CLEAR_STATE_BTN())
            self.set_state(message.chat.id, result.id, message.from_user.id, "plata_add_account", data)
            return
        if data.get("step") == "key":
            if len(value) != 32 or value != value.lower() or len(value.split()) != 1:
                self.bot.send_message(message.chat.id, "Некорректный golden key. Нужна строка из 32 строчных символов без пробелов.")
                return
            data.update(step="name", golden_key=value)
            result = self.bot.send_message(message.chat.id, "Введите название аккаунта (или отправьте - для имени по ID).", reply_markup=skb.CLEAR_STATE_BTN())
            self.set_state(message.chat.id, result.id, message.from_user.id, "plata_add_account", data)
            return
        if data.get("step") == "name":
            data.update(step="proxy", name=data["account_id"] if value == "-" else value[:80])
            result = self.bot.send_message(
                message.chat.id,
                "Введите прокси для этого аккаунта в формате <u>login:password@ip:port</u> или <u>ip:port</u>.\n"
                "Отправьте <code>-</code>, если прокси не нужен.",
                reply_markup=skb.CLEAR_STATE_BTN(),
            )
            self.set_state(message.chat.id, result.id, message.from_user.id, "plata_add_account", data)
            return
        registry = getattr(self.cardinal, "account_registry", None)
        if registry is None:
            self.clear_state(message.chat.id, message.from_user.id)
            self.bot.send_message(message.chat.id, "Реестр аккаунтов PLATA не инициализирован.")
            return
        proxy = None
        if value != "-":
            try:
                proxy = plata_tools.normalize_proxy(value)
            except ValueError:
                self.bot.send_message(message.chat.id, "Некорректный прокси. Используйте формат <u>login:password@ip:port</u> или <u>ip:port</u>.")
                return
        name = data.get("name") or data["account_id"]
        try:
            profile = registry.create_from_base(data["account_id"], name, data["golden_key"])
            runtime = getattr(self, "runtime", None)
            if runtime is not None and proxy:
                try:
                    proxy, _ = plata_tools.register_proxy(proxy)
                    runtime.sync_proxy_pool()
                    runtime.set_proxy(profile.account_id, proxy)
                except Exception:
                    logger.debug("TRACEBACK", exc_info=True)
                    self.bot.send_message(message.chat.id,
                                          "⚠️ Аккаунт создан, но прокси не применился — задайте его в карточке аккаунта.")
            if runtime is not None:
                runtime.start_profile(profile)
        except ValueError as error:
            messages = {"Invalid account ID": "Некорректный ID аккаунта.", "Invalid golden_key": "Некорректный golden key.", "Account already exists": "Аккаунт с таким ID уже существует."}
            self.bot.send_message(message.chat.id, messages.get(str(error), "Не удалось создать аккаунт."))
            self.clear_state(message.chat.id, message.from_user.id)
            return
        except Exception as error:
            self.clear_state(message.chat.id, message.from_user.id)
            self.bot.send_message(message.chat.id, f"Профиль создан, но не запущен: <code>{html.escape(str(error)[:200])}</code>")
            return
        self.clear_state(message.chat.id, message.from_user.id)
        proxy_note = f"\n🔌 Прокси: <code>{html.escape(proxy)}</code>" if proxy else ""
        self.bot.send_message(message.chat.id,
                              f"✅ Аккаунт <b>{html.escape(profile.name)}</b> добавлен и запущен.{proxy_note}")

    def account_update_key_text(self, message: Message):
        """Сохраняет новый golden key профиля; работает и для остановленного аккаунта."""
        state = self.get_state(message.chat.id, message.from_user.id)
        if not state:
            return
        data = state["data"]
        account_id = str(data.get("account_id") or "")
        try:
            self.bot.delete_message(message.chat.id, message.id)
        except Exception:
            pass
        value = (message.text or "").strip()
        if len(value) != 32 or value != value.lower() or not value.isalnum():
            self.bot.send_message(message.chat.id,
                                  "Некорректный golden key. Нужна строка из 32 строчных символов (латиница и цифры).")
            return
        runtime = getattr(self, "runtime", None)
        registry = getattr(self.cardinal, "account_registry", None)
        profile = registry.get(account_id) if registry is not None else None
        if runtime is None or profile is None:
            self.clear_state(message.chat.id, message.from_user.id)
            self.bot.send_message(message.chat.id, "Аккаунт не найден.")
            return
        try:
            profile = runtime.update_golden_key(account_id, value)
        except ValueError:
            self.bot.send_message(message.chat.id, "Некорректный golden key.")
            return
        self.clear_state(message.chat.id, message.from_user.id)
        if not profile.enabled:
            self.bot.send_message(message.chat.id, "🔑 Golden key обновлён. Аккаунт отключён — включите его "
                                                   "кнопкой ▶️ Включить в 👤 Аккаунты.")
            return
        try:
            runtime.start_profile(profile)
            runtime.select(account_id)
        except Exception as error:
            try:
                runtime.select(account_id)
            except Exception:
                logger.debug("TRACEBACK", exc_info=True)
            self.bot.send_message(message.chat.id,
                                  "🔑 Golden key сохранён, но запуск не удался:\n"
                                  f"<code>{html.escape(str(error)[:200])}</code>\n\n"
                                  "Откройте ⚙️ Настроить в 👤 Аккаунты, чтобы проверить настройки.")
            return
        self.bot.send_message(message.chat.id,
                              f"✅ Golden key обновлён, аккаунт <b>{html.escape(profile.name)}</b> запущен.")
        self.bot.send_message(message.chat.id, self._main_menu_text(), reply_markup=skb.SETTINGS_SECTIONS())

    def account_center_action(self, call: CallbackQuery):
        parts = call.data.split(":")
        if len(parts) != 4:
            self.bot.answer_callback_query(call.id, "Некорректное действие.", show_alert=True)
            return
        account_id, action = parts[1], parts[2]
        try:
            offset = int(parts[3])
        except ValueError:
            offset = 0
        runtime = getattr(self, "runtime", None)
        try:
            if action == "select":
                runtime.select(account_id)
            elif action == "configure":
                runtime.select(account_id)
                self.bot.answer_callback_query(call.id, "Аккаунт выбран для настройки")
                if runtime.is_offline(account_id):
                    self.bot.send_message(
                        call.message.chat.id,
                        "⚠️ Аккаунт не запущен: изменения сохраняются в его конфиги, "
                        "а запуск — кнопкой ▶️ Запустить в 👤 Аккаунты.",
                    )
                self.bot.send_message(call.message.chat.id, self._main_menu_text(),
                                      reply_markup=skb.SETTINGS_SECTIONS())
                self.refresh_account_center(call, offset)
                return
            elif action == "key":
                profile = runtime.registry.get(account_id) if runtime is not None else None
                if profile is None:
                    self.bot.answer_callback_query(call.id, "Аккаунт не найден.", show_alert=True)
                    return
                self.bot.answer_callback_query(call.id)
                self._ask_golden_key(call.message.chat.id, call.from_user.id, account_id, offset)
                return
            elif action == "stats":
                runtime.select(account_id)
                self.bot.answer_callback_query(call.id)
                self.send_sales_stats(call.message)
                return
            elif action == "restart":
                runtime.restart_profile(account_id)
                runtime.select(account_id)
            elif action == "disable":
                runtime.disable(account_id)
            elif action == "enable":
                runtime.enable(account_id)
                runtime.start_profile(runtime.registry.get(account_id))
                runtime.select(account_id)
            else:
                raise KeyError(account_id)
        except Exception as error:
            self.bot.answer_callback_query(call.id, f"Не удалось выполнить: {str(error)[:120]}", show_alert=True)
            return
        self.bot.answer_callback_query(call.id, "Готово")
        self.refresh_account_center(call, offset)

    def plata_menu_callback(self, call: CallbackQuery):
        section = call.data.split(":", 1)[1]
        if section == "back":
            self.bot.edit_message_text(
                self._main_menu_text(),
                call.message.chat.id,
                call.message.id,
                reply_markup=skb.SETTINGS_SECTIONS(),
            )
            self.bot.answer_callback_query(call.id)
            return
        handlers = {
            "accounts": self.send_accounts,
            "automation": self.send_automation_center,
            "notifications": self.send_notifications_center,
            "stats": self.send_sales_stats,
            "stats_all": self.send_all_sales_stats,
            "health": self.account_health,
            "plugins": self.send_plugins_menu,
            "modules": self.send_modules_menu,
        }
        handler = handlers.get(section)
        if handler is None:
            self.bot.answer_callback_query(call.id)
            return
        handler(call.message)
        self.bot.answer_callback_query(call.id)

    def send_plugins_menu(self, message: Message):
        self.bot.send_message(message.chat.id, _("desc_pl"),
                              reply_markup=kb.plugins_list(self.cardinal, 0))

    def send_automation_center(self, message: Message):
        cfg = self.cardinal.MAIN_CFG
        def enabled(section, key):
            try:
                return "🟢" if cfg[section].getboolean(key) else "🔴"
            except (KeyError, ValueError):
                return "⚪"
        text = ("<b>⚙️ Центр автоматизации</b>\n\n"
                f"{enabled('FunPay', 'autoRaise')} Автоподнятие лотов\n"
                f"{enabled('FunPay', 'autoRestore')} Автовосстановление лотов\n"
                f"{enabled('FunPay', 'autoDisable')} Автоотключение пустых лотов\n"
                f"{enabled('Greetings', 'sendGreetings')} Приветствие покупателей\n"
                f"{enabled('OrderConfirm', 'sendReply')} Ответ после подтверждения\n\n"
                "Переключайте автоматические функции кнопками ниже. Детальные настройки вынесены в главное меню.")
        self.bot.send_message(message.chat.id, text, reply_markup=kb.main_settings(self.cardinal))

    def send_notifications_center(self, message: Message):
        chat_id = message.chat.id
        types = self._configurable_notification_types()
        enabled_count = sum(self.is_notification_enabled(chat_id, item) for item in types)
        text = ("<b>🔔 Центр уведомлений</b>\n\n"
                f"Для текущего чата включено: <b>{enabled_count}/{len(types)}</b> событий.\n\n"
                "Можно отдельно настроить сообщения, заказы, отзывы, выдачу товара и состояние лотов.")
        keyboard = K().add(B("🔔 Настроить события", callback_data=f"{CBT.CATEGORY}:tg")).add(
            B("✅ Включить все уведомления", callback_data="plata_notify:essential_on")).add(
            B("🔕 Выключить все уведомления", callback_data="plata_notify:essential_off")).add(
            B("⬅️ Назад", callback_data="plata_menu:back"))
        self.bot.send_message(message.chat.id, text, reply_markup=keyboard)

    def notification_center_callback(self, call: CallbackQuery):
        action = call.data.split(":", 1)[1]
        value = action == "essential_on"
        chat_id = str(call.message.chat.id)
        self.notification_settings.setdefault(chat_id, {})
        for item in self._configurable_notification_types():
            self.notification_settings[chat_id][item] = int(value)
        utils.save_notification_settings(self.notification_settings)
        types = self._configurable_notification_types()
        enabled_count = sum(self.is_notification_enabled(chat_id, item) for item in types)
        text = ("<b>🔔 Центр уведомлений</b>\n\n"
                f"Для текущего чата включено: <b>{enabled_count}/{len(types)}</b> событий.\n\n"
                "Можно отдельно настроить сообщения, заказы, отзывы, выдачу товара и состояние лотов.")
        keyboard = K().add(B("🔔 Настроить события", callback_data=f"{CBT.CATEGORY}:tg")).add(
            B("✅ Включить все уведомления", callback_data="plata_notify:essential_on")).add(
            B("🔕 Выключить все уведомления", callback_data="plata_notify:essential_off")).add(
            B("⬅️ Назад", callback_data="plata_menu:back"))
        self.bot.edit_message_text(text, call.message.chat.id, call.message.id, reply_markup=keyboard)
        self.bot.answer_callback_query(call.id, "Все уведомления включены" if value else "Все уведомления выключены")
        return

    @staticmethod
    def _configurable_notification_types() -> tuple[str, ...]:
        return (
            NotificationTypes.new_message,
            NotificationTypes.command,
            NotificationTypes.new_order,
            NotificationTypes.order_confirmed,
            NotificationTypes.lots_restore,
            NotificationTypes.lots_deactivate,
            NotificationTypes.delivery,
            NotificationTypes.lots_raise,
            NotificationTypes.review,
            NotificationTypes.bot_start,
            NotificationTypes.other,
        )

    def send_modules_menu(self, message: Message):
        text, keyboard = self._modules_menu_payload()
        self.bot.send_message(message.chat.id, text, reply_markup=keyboard)

    @staticmethod
    def _modules_menu_payload():
        text = "<b>🦊 Встроенные модули PLATA</b>\n\nВыберите модуль для управления."
        keyboard = K().row(
            B("🔔 Напоминание о заказе", callback_data="plata_module:reminder:menu"),
            B("⭐ Ответы на отзывы", callback_data="plata_module:review:menu"),
        ).row(
            B("📋 Старые заказы", callback_data="plata_module:old_orders:run"),
        ).row(
            B("⬅️ Назад", callback_data="plata_menu:back"),
        )
        return text, keyboard

    def reminder_module_menu(self, call: CallbackQuery):
        from plata_modules import confirm_reminder
        account_id = str(getattr(self.cardinal, "account_profile_id", "primary"))
        data = confirm_reminder._settings(account_id)
        units = {"seconds": "секунд", "minutes": "минут", "hours": "часов", "days": "дней"}
        text = ("<b>🔔 Напоминание о подтверждении заказа</b>\n\n"
                f"Состояние: {'включено' if data['enabled'] else 'выключено'}\n"
                f"Задержка: {data['delay']} {units.get(data.get('unit'), 'минут')}\n"
                f"Аккаунт: {html.escape(self._account_display_name(account_id))}")
        keyboard = K().row(
            B("⏻ Включить / выключить", callback_data="plata_module:reminder:toggle"),
            B("⏱ Задержка", callback_data="plata_module:reminder:delay"),
        ).row(
            B("🕒 Единица времени", callback_data="plata_module:reminder:unit"),
            B("⬅️ Назад", callback_data="plata_module:home:open"),
        )
        self.bot.edit_message_text(text, call.message.chat.id, call.message.id, reply_markup=keyboard)

    def review_module_menu(self, call: CallbackQuery):
        from plata_modules import review_reply
        account_id = str(getattr(self.cardinal, "account_profile_id", "primary"))
        data = review_reply._settings(account_id)
        keyboard = K().add(B(f"{'🟢' if data.get('enabled') else '🔴'} Модуль включён", callback_data="plata_module:review:toggle"))
        for star in range(1, 6):
            item = data["replies"][str(star)]
            keyboard.row(B(f"{'🟢' if item.get('enabled') else '🔴'} {'⭐' * star}", callback_data=f"plata_module:review:star:{star}"),
                         B("✏️ Текст", callback_data=f"plata_module:review:edit:{star}"))
        deleted = data["replies"]["6"]
        keyboard.row(B(f"{'🟢' if deleted.get('enabled') else '🔴'} 🗑 Удалённый отзыв", callback_data="plata_module:review:star:6"),
                     B("✏️ Текст", callback_data="plata_module:review:edit:6"))
        keyboard.row(B("⬅️ Назад", callback_data="plata_module:home:open"))
        text = "<b>⭐ Ответы на отзывы</b>\n\nВыберите оценку для включения или изменения текста."
        without_text = [key for key, item in data["replies"].items() if item.get("enabled") and not item.get("text")]
        if without_text:
            labels = ", ".join("удалённый отзыв" if key == "6" else "⭐" * int(key) for key in sorted(without_text, key=int))
            text += f"\n\n⚠️ Ответ включён без текста: {labels}. Нажмите «✏️ Текст»."
        self.bot.edit_message_text(text, call.message.chat.id, call.message.id, reply_markup=keyboard)

    def review_module_edit(self, call: CallbackQuery, star: str):
        result = self.bot.send_message(call.message.chat.id, f"Введите текст ответа для {'удалённого отзыва' if star == '6' else '⭐' * int(star)}.",
                                       reply_markup=skb.CLEAR_STATE_BTN())
        self.set_state(call.message.chat.id, result.id, call.from_user.id, "plata_review_edit", {"star": star})

    def review_module_edit_text(self, message: Message):
        from plata_modules import review_reply
        state = self.get_state(message.chat.id, message.from_user.id)
        star = state["data"]["star"]
        self.clear_state(message.chat.id, message.from_user.id, True)
        data = review_reply._settings(str(getattr(self.cardinal, "account_profile_id", "primary")))
        data["replies"][star] = {"enabled": True, "text": "" if message.text == "-" else message.text}
        review_reply._save(str(getattr(self.cardinal, "account_profile_id", "primary")), data)
        self.bot.send_message(message.chat.id, "✅ Текст ответа сохранён и включён.")

    def module_callback(self, call: CallbackQuery):
        from plata_modules import confirm_reminder, review_reply
        parts = call.data.split(":")
        if len(parts) < 3:
            self.bot.answer_callback_query(call.id)
            return
        account_id = str(getattr(self.cardinal, "account_profile_id", "primary"))
        if parts[1] == "home" and parts[2] == "open":
            text, keyboard = self._modules_menu_payload()
            self.bot.edit_message_text(text, call.message.chat.id, call.message.id, reply_markup=keyboard)
            self.bot.answer_callback_query(call.id)
            return
        if parts[1] == "old_orders" and parts[2] == "run":
            if self._selected_account_offline():
                self.bot.answer_callback_query(call.id, "Аккаунт не запущен — данные FunPay недоступны.",
                                               show_alert=True)
                return
            from plata_modules.old_orders import send_orders
            send_orders(self.cardinal, call.message)
            self.bot.answer_callback_query(call.id)
            return
        if parts[1] == "review" and parts[2] == "menu":
            self.review_module_menu(call)
            self.bot.answer_callback_query(call.id)
            return
        if parts[1] == "reminder" and parts[2] == "menu":
            self.reminder_module_menu(call)
            self.bot.answer_callback_query(call.id)
            return
        if parts[1] == "review" and len(parts) == 4 and parts[2] == "star":
            data = review_reply._settings(account_id)
            star = parts[3]
            data["replies"].setdefault(star, {"enabled": False, "text": ""})["enabled"] = not data["replies"][star].get("enabled", False)
            review_reply._save(account_id, data)
            self.review_module_menu(call)
            self.bot.answer_callback_query(call.id)
            return
        if parts[1] == "review" and len(parts) == 4 and parts[2] == "edit":
            self.review_module_edit(call, parts[3])
            self.bot.answer_callback_query(call.id)
            return
        if parts[1] == "profile" and parts[2] == "run":
            if self._selected_account_offline():
                self.bot.answer_callback_query(call.id, "Аккаунт не запущен — статистика профиля недоступна.",
                                               show_alert=True)
                return
            from plata_modules.profile_stats import send_stats
            send_stats(self.cardinal, call.message)
            self.bot.answer_callback_query(call.id)
            return
        if parts[1] == "review" and parts[2] == "toggle":
            data = review_reply._settings(account_id)
            data["enabled"] = not data.get("enabled", False)
            review_reply._save(account_id, data)
        elif parts[1] != "reminder":
            self.bot.answer_callback_query(call.id)
            return
        else:
            data = confirm_reminder._settings(account_id)
            if parts[2] == "toggle":
                data["enabled"] = not data["enabled"]
            elif parts[2] == "delay":
                values = [1, 5, 15, 30, 60]
                data["delay"] = values[(values.index(data["delay"]) + 1) % len(values)] if data["delay"] in values else 1
            elif parts[2] == "unit":
                values = ["seconds", "minutes", "hours", "days"]
                data["unit"] = values[(values.index(data["unit"]) + 1) % len(values)] if data["unit"] in values else "minutes"
            confirm_reminder._save_account(account_id, data)
        self.reminder_module_menu(call)
        self.bot.answer_callback_query(call.id, "Настройка сохранена")

    def reminder_text(self, m: Message):
        from plata_modules import confirm_reminder
        value = self._command_argument(m)
        if not value:
            self.bot.send_message(m.chat.id, "Укажите текст после команды. Можно использовать <code>{order_id}</code>.\n"
                                             "Пример: <code>/reminder_text Подтвердите заказ {order_id}</code>")
            return
        account_id = str(getattr(self.cardinal, "account_profile_id", "primary"))
        data = confirm_reminder._settings(account_id)
        try:
            value.format(order_id="123")
        except (KeyError, ValueError):
            self.bot.send_message(m.chat.id, "В тексте разрешён только шаблон <code>{order_id}</code>.")
            return
        data["text"] = value
        confirm_reminder._save_account(account_id, data)
        self.bot.send_message(m.chat.id, "Текст напоминания сохранён.")

    def review_reply(self, m: Message):
        from plata_modules import review_reply
        parts = (m.text or "").split(maxsplit=2)
        if len(parts) != 3 or parts[1] not in {"1", "2", "3", "4", "5", "6", "deleted"}:
            self.bot.send_message(m.chat.id, "Использование: <code>/review_reply 5 Спасибо за отзыв!</code>\n"
                                             "Для удалённого отзыва используйте <code>deleted</code>.")
            return
        account_id = str(getattr(self.cardinal, "account_profile_id", "primary"))
        data = review_reply._settings(account_id)
        key = "6" if parts[1] == "deleted" else parts[1]
        data.setdefault("replies", {}).setdefault(key, {})["text"] = parts[2]
        data["replies"][key]["enabled"] = True
        review_reply._save(account_id, data)
        self.bot.send_message(m.chat.id, "Ответ на отзыв сохранён и включён.")


    @staticmethod
    def _command_argument(m: Message) -> str | None:
        parts = (m.text or "").split(maxsplit=1)
        return parts[1].strip() if len(parts) == 2 and parts[1].strip() else None


    def account_health(self, m: Message):
        runtime = getattr(self, "runtime", None)
        if runtime is None:
            self.bot.send_message(m.chat.id, "Runtime PLATA не инициализирован.")
            return
        lines = ["<b>Состояние аккаунтов PLATA</b>", ""]
        for account_id, status in runtime.health().items():
            live_ok, live_detail = runtime.check_account(account_id)
            if status["error"]:
                state = "🔴 ошибка"
                detail = html.escape(status["error"][:160])
            elif status["running"] and status["thread_alive"]:
                state = "🟢 работает"
                uptime = cardinal_tools.time_to_str(status["uptime"] or 0)
                event_age = (f", событие {cardinal_tools.time_to_str(status['last_event_age'])} назад"
                             if status["last_event_age"] is not None else "")
                detail = f"@{html.escape(status['username'] or account_id)}, работает {uptime}{event_age}; " \
                         f"{'FunPay доступен' if live_ok else 'FunPay недоступен'}"
            elif status["enabled"]:
                state = "🟡 запускается"
                detail = "ожидание polling"
            else:
                state = "⚪ отключён"
                detail = ""
            lines.append(f"<b>{html.escape(status['name'])}</b> "
                         f"<code>{html.escape(account_id)}</code> — {state} {detail}")
        self.bot.send_message(m.chat.id, "\n".join(lines),
                              reply_markup=K().add(B("⬅️ Назад", callback_data="plata_menu:back")))

    def act_change_cookie(self, m: Message):
        """
        Активирует режим ввода golden_key. При нескольких аккаунтах сначала предлагает выбрать аккаунт.
        """
        profiles = self._account_profiles()
        if len(profiles) > 1:
            runtime = getattr(self, "runtime", None)
            keyboard = K()
            for profile in profiles:
                marker = "🟢" if runtime is not None and runtime.get(profile.account_id) is not None else "⚪"
                keyboard.add(B(f"{marker} {profile.name} · {profile.account_id}",
                               callback_data=f"gk:{profile.account_id}"))
            keyboard.add(B("⬅️ Отмена", callback_data=CBT.MAIN))
            self.bot.send_message(m.chat.id,
                                  "🔑 Для какого аккаунта меняем golden key?\n"
                                  "🟢 — запущен, ⚪ — остановлен.",
                                  reply_markup=keyboard)
            return
        account_id = (profiles[0].account_id if profiles
                      else str(getattr(self.cardinal, "account_profile_id", "primary")))
        self._ask_golden_key(m.chat.id, m.from_user.id, account_id)

    def _account_profiles(self) -> list:
        """Профили аккаунтов из реестра (пустой список, если реестр недоступен)."""
        registry = getattr(self.cardinal, "account_registry", None)
        if registry is None:
            return []
        try:
            return registry.list()
        except Exception:
            logger.debug("TRACEBACK", exc_info=True)
            return []

    def _ask_golden_key(self, chat_id: int, user_id: int, account_id: str, offset: int = 0) -> None:
        """
        Просит golden key выбранного аккаунта.

        Для запущенного аккаунта используется проверка через FunPay, для остановленного —
        сохранение в конфиг без сети с последующей попыткой запуска.
        """
        runtime = getattr(self, "runtime", None)
        instance = runtime.get(account_id) if runtime is not None else None
        if runtime is None or instance is not None:
            if runtime is not None:
                try:
                    runtime.select(account_id)
                except Exception:
                    logger.debug("TRACEBACK", exc_info=True)
            result = self.bot.send_message(chat_id, _("act_change_golden_key"), reply_markup=skb.CLEAR_STATE_BTN())
            self.set_state(chat_id, result.id, user_id, CBT.CHANGE_GOLDEN_KEY)
            return
        profile = runtime.registry.get(account_id)
        name = profile.name if profile is not None else account_id
        result = self.bot.send_message(
            chat_id,
            f"🔑 Введите новый golden key для аккаунта <b>{html.escape(name)}</b> "
            f"<i>{html.escape(account_id)}</i>.\n"
            "Это 32 строчных символа (латиница и цифры). После сохранения аккаунт попробует запуститься.",
            reply_markup=skb.CLEAR_STATE_BTN(),
        )
        self.set_state(chat_id, result.id, user_id, "plata_update_key",
                       {"account_id": account_id, "offset": offset})

    def golden_key_select(self, call: CallbackQuery):
        """Выбор аккаунта для смены golden key из команды /golden_key."""
        account_id = call.data.split(":", 1)[1] if ":" in call.data else ""
        registry = getattr(self.cardinal, "account_registry", None)
        if (registry.get(account_id) if registry is not None else None) is None:
            self.bot.answer_callback_query(call.id, "Аккаунт не найден.", show_alert=True)
            return
        self.bot.answer_callback_query(call.id)
        try:
            self.bot.delete_message(call.message.chat.id, call.message.id)
        except Exception:
            logger.debug("TRACEBACK", exc_info=True)
        self._ask_golden_key(call.message.chat.id, call.from_user.id, account_id)

    def change_cookie(self, m: Message):
        """
        Меняет golden_key аккаунта FunPay.
        """
        self.clear_state(m.chat.id, m.from_user.id, True)
        golden_key = m.text
        if len(golden_key) != 32 or golden_key != golden_key.lower() or len(golden_key.split()) != 1:
            self.bot.send_message(m.chat.id, _("cookie_incorrect_format"))
            return
        self.bot.delete_message(m.chat.id, m.id)
        new_account = Account(golden_key, self.cardinal.account.user_agent, proxy=self.cardinal.proxy,
                              locale=self.cardinal.account.locale)
        try:
            new_account.get()
        except:
            logger.warning("Произошла ошибка")  # locale
            logger.debug("TRACEBACK", exc_info=True)
            self.bot.send_message(m.chat.id, _("cookie_error"))
            return

        one_acc = False
        if new_account.id == self.cardinal.account.id or self.cardinal.account.id is None:
            one_acc = True
            self.cardinal.account.golden_key = golden_key
            try:
                self.cardinal.account.get()
            except:
                logger.warning("Произошла ошибка")  # locale
                logger.debug("TRACEBACK", exc_info=True)
                self.bot.send_message(m.chat.id, _("cookie_error"))
                return
            accs = f" (<a href='https://funpay.com/users/{new_account.id}/'>{new_account.username}</a>)"
        else:
            accs = f" (<a href='https://funpay.com/users/{self.cardinal.account.id}/'>" \
                   f"{self.cardinal.account.username}</a> ➔ <a href='https://funpay.com/users/{new_account.id}/'>" \
                   f"{new_account.username}</a>)"

        self.cardinal.MAIN_CFG.set("FunPay", "golden_key", golden_key)
        self.cardinal.save_config(self.cardinal.MAIN_CFG, "configs/_main.cfg")
        self.bot.send_message(m.chat.id, f'{_("cookie_changed", accs)}{_("cookie_changed2") if not one_acc else ""}',
                              disable_web_page_preview=True)

    def update_profile(self, c: CallbackQuery):
        if self._selected_account_offline():
            self.bot.answer_callback_query(c.id, "Аккаунт не запущен — обновление профиля недоступно.",
                                           show_alert=True)
            return
        new_msg = self.bot.send_message(c.message.chat.id, _("updating_profile"))
        try:
            self.cardinal.account.get()
            self.cardinal.balance = self.cardinal.get_balance()
        except:
            self.bot.edit_message_text(_("profile_updating_error"), new_msg.chat.id, new_msg.id)
            logger.debug("TRACEBACK", exc_info=True)
            self.bot.answer_callback_query(c.id)
            return

        self.bot.delete_message(new_msg.chat.id, new_msg.id)
        self.bot.edit_message_text(utils.generate_profile_text(self.cardinal), c.message.chat.id,
                                   c.message.id, reply_markup=skb.REFRESH_BTN())

    def act_manual_delivery_test(self, m: Message):
        """
        Активирует режим ввода названия лота для ручной генерации ключа теста автовыдачи.
        """
        result = self.bot.send_message(m.chat.id, _("create_test_ad_key"), reply_markup=skb.CLEAR_STATE_BTN())
        self.set_state(m.chat.id, result.id, m.from_user.id, CBT.MANUAL_AD_TEST)

    def manual_delivery_text(self, m: Message):
        """
        Генерирует ключ теста автовыдачи (ручной режим).
        """
        self.clear_state(m.chat.id, m.from_user.id, True)
        lot_name = m.text.strip()
        key = "".join(random.sample(string.ascii_letters + string.digits, 50))
        self.cardinal.delivery_tests[key] = lot_name

        logger.info(_("log_new_ad_key", m.from_user.username, m.from_user.id, lot_name, key))
        self.bot.send_message(m.chat.id, _("test_ad_key_created", utils.escape(lot_name), key))

    def act_ban(self, m: Message):
        """
        Активирует режим ввода никнейма пользователя, которого нужно добавить в ЧС.
        """
        result = self.bot.send_message(m.chat.id, _("act_blacklist"), reply_markup=skb.CLEAR_STATE_BTN())
        self.set_state(m.chat.id, result.id, m.from_user.id, CBT.BAN)

    def ban(self, m: Message):
        """
        Добавляет пользователя в ЧС.
        """
        self.clear_state(m.chat.id, m.from_user.id, True)
        nickname = m.text.strip()

        if nickname in self.cardinal.blacklist:
            self.bot.send_message(m.chat.id, _("already_blacklisted", nickname))
            return

        self.cardinal.blacklist.append(nickname)
        cardinal_tools.cache_blacklist(self.cardinal.blacklist)
        logger.info(_("log_user_blacklisted", m.from_user.username, m.from_user.id, nickname))
        self.bot.send_message(m.chat.id, _("user_blacklisted", nickname))

    def act_unban(self, m: Message):
        """
        Активирует режим ввода никнейма пользователя, которого нужно удалить из ЧС.
        """
        result = self.bot.send_message(m.chat.id, _("act_unban"), reply_markup=skb.CLEAR_STATE_BTN())
        self.set_state(m.chat.id, result.id, m.from_user.id, CBT.UNBAN)

    def unban(self, m: Message):
        """
        Удаляет пользователя из ЧС.
        """
        self.clear_state(m.chat.id, m.from_user.id, True)
        nickname = m.text.strip()
        if nickname not in self.cardinal.blacklist:
            self.bot.send_message(m.chat.id, _("not_blacklisted", nickname))
            return
        self.cardinal.blacklist.remove(nickname)
        cardinal_tools.cache_blacklist(self.cardinal.blacklist)
        logger.info(_("log_user_unbanned", m.from_user.username, m.from_user.id, nickname))
        self.bot.send_message(m.chat.id, _("user_unbanned", nickname))

    def send_ban_list(self, m: Message):
        """
        Отправляет ЧС.
        """
        if not self.cardinal.blacklist:
            self.bot.send_message(m.chat.id, _("blacklist_empty"))
            return
        blacklist = ", ".join(f"<code>{i}</code>" for i in sorted(self.cardinal.blacklist, key=lambda x: x.lower()))
        self.bot.send_message(m.chat.id, blacklist)

    def act_edit_watermark(self, m: Message):
        """
        Активирует режим ввода вотемарки сообщений.
        """
        watermark = self.cardinal.MAIN_CFG["Other"]["watermark"]
        watermark = f"\n<code>{utils.escape(watermark)}</code>" if watermark else ""
        result = self.bot.send_message(m.chat.id, _("act_edit_watermark").format(watermark),
                                       reply_markup=skb.CLEAR_STATE_BTN())
        self.set_state(m.chat.id, result.id, m.from_user.id, CBT.EDIT_WATERMARK)

    def edit_watermark(self, m: Message):
        self.clear_state(m.chat.id, m.from_user.id, True)
        watermark = m.text if m.text != "-" else ""
        if re.fullmatch(r"\[[a-zA-Z]+]", watermark):
            self.bot.reply_to(m, _("watermark_error"))
            return

        preview = f"<a href=\"https://sfunpay.com/s/chat/zb/wl/zbwl4vwc8cc1wsftqnx5.jpg\">⁢</a>" if not \
            utils.has_brand_mark(watermark) else \
            f"<a href=\"https://sfunpay.com/s/chat/kd/8i/kd8isyquw660kcueck3g.jpg\">⁢</a>"
        self.cardinal.MAIN_CFG["Other"]["watermark"] = watermark
        self.cardinal.save_config(self.cardinal.MAIN_CFG, "configs/_main.cfg")
        if watermark:
            logger.info(_("log_watermark_changed", m.from_user.username, m.from_user.id, watermark))
            self.bot.reply_to(m, preview + _("watermark_changed", watermark))
        else:
            logger.info(_("log_watermark_deleted", m.from_user.username, m.from_user.id))
            self.bot.reply_to(m, preview + _("watermark_deleted"))

    def send_logs(self, m: Message):
        """
        Отправляет файл логов.
        """
        if not os.path.exists("logs/log.log"):
            self.bot.send_message(m.chat.id, _("logfile_not_found"))
        else:
            self.bot.send_message(m.chat.id, _("logfile_sending"))
            try:
                with open("logs/log.log", "r", encoding="utf-8") as f:
                    self.bot.send_document(m.chat.id, f,
                                           caption=f'{_("gs_old_msg_mode").replace("{} ", "") if self.cardinal.old_mode_enabled else ""}')
                    f.seek(0)
                    file_content = f.read()
                    if "TRACEBACK" in file_content:
                        file_content, right = file_content.rsplit("TRACEBACK", 1)
                        file_content = "\n[".join(file_content.rsplit("\n[", 2)[-2:])
                        right = right.split("\n[", 1)[0]  # locale
                        result = f"<b>Текст последней ошибки:</b>\n\n[{utils.escape(file_content)}TRACEBACK{utils.escape(right)}"
                        while result:
                            text, result = result[:4096], result[4096:]
                            self.bot.send_message(m.chat.id, text)
                            time.sleep(0.5)
                    else:
                        self.bot.send_message(m.chat.id, "<b>Ошибок в последнем лог-файле не обнаружено.</b>")  # locale
            except:
                logger.warning("Не удалось отправить лог-файл")
                logger.debug("TRACEBACK", exc_info=True)
                self.bot.send_message(m.chat.id, _("logfile_error"))

    def del_logs(self, m: Message):
        """
        Удаляет старые лог-файлы.
        """
        logger.info(
            f"[IMPORTANT] Удаляю логи по запросу пользователя $MAGENTA@{m.from_user.username} (id: {m.from_user.id})$RESET.")
        deleted = 0  # locale
        for file in os.listdir("logs"):
            if not file.endswith(".log"):
                try:
                    os.remove(f"logs/{file}")
                    deleted += 1
                except:
                    continue
        self.bot.send_message(m.chat.id, _("logfile_deleted").format(deleted))

    def about(self, m: Message):
        """
        Отправляет информацию о текущей версии бота.
        """
        self.bot.send_message(m.chat.id, _("about", self.cardinal.VERSION))

    def check_updates(self, m: Message):
        curr_tag = f"v{self.cardinal.VERSION}"
        releases = updater.get_new_releases(curr_tag)
        if isinstance(releases, int):
            errors = {
                1: ["update_no_tags", ()],
                2: ["update_lasted", (curr_tag,)],
                3: ["update_get_error", ()],
            }
            self.bot.send_message(m.chat.id, _(errors[releases][0], *errors[releases][1]))
            return
        for release in releases:
            self.bot.send_message(m.chat.id, _("update_available", release.name, release.description))
            time.sleep(1)
        self.bot.send_message(m.chat.id, _("update_update"))

    def get_backup(self, m: Message):
        logger.info(
            f"[IMPORTANT] Получаю бэкап по запросу пользователя $MAGENTA@{m.from_user.username} (id: {m.from_user.id})$RESET.")
        if os.path.exists("backup.zip"):  # locale
            with open(file_path := "backup.zip", 'rb') as file:
                modification_time = os.path.getmtime(file_path)
                formatted_time = time.strftime('%d.%m.%Y %H:%M:%S', time.localtime(modification_time))
                try:
                    self.bot.send_document(chat_id=m.chat.id, document=InputFile(file),
                                           caption=f'{_("update_backup")}\n\n{formatted_time}')
                except:
                    logger.warning("Не удалось отправить бэкап")
                    logger.debug("TRACEBACK", exc_info=True)
                    self.bot.send_message(m.chat.id, _("update_backup_send_error"))

        else:
            self.bot.send_message(m.chat.id, _("update_backup_not_found"))

    def create_backup(self, m: Message):
        if updater.create_backup():
            self.bot.send_message(m.chat.id, _("update_backup_error"))
            return False
        self.get_backup(m)
        return True

    def update(self, m: Message):
        curr_tag = f"v{self.cardinal.VERSION}"
        releases = updater.get_new_releases(curr_tag)
        if isinstance(releases, int):
            errors = {
                1: ["update_no_tags", ()],
                2: ["update_lasted", (curr_tag,)],
                3: ["update_get_error", ()],
            }
            self.bot.send_message(m.chat.id, _(errors[releases][0], *errors[releases][1]))
            return

        if not self.create_backup(m):
            return
        release = releases[-1]
        if updater.download_zip(release.sources_link) \
                or (release_folder := updater.extract_update_archive()) == 1:
            self.bot.send_message(m.chat.id, _("update_download_error"))
            return
        self.bot.send_message(m.chat.id, _("update_downloaded").format(release.name, str(len(releases) - 1)))

        if updater.install_release(release_folder):
            self.bot.send_message(m.chat.id, _("update_install_error"))
            return

        if getattr(sys, 'frozen', False):
            self.bot.send_message(m.chat.id, _("update_done_exe"))
        else:
            self.bot.send_message(m.chat.id, _("update_done"))

    def send_system_info(self, m: Message):
        """
        Отправляет информацию о нагрузке на систему.
        """
        current_time = int(time.time())
        uptime = current_time - self.cardinal.start_time

        ram = psutil.virtual_memory()
        cpu_usage = "\n".join(
            f"    CPU {i}:  <code>{l}%</code>" for i, l in enumerate(psutil.cpu_percent(percpu=True)))
        self.bot.send_message(m.chat.id, _("sys_info", cpu_usage, psutil.Process().cpu_percent(),
                                           ram.total // 1048576, ram.used // 1048576, ram.free // 1048576,
                                           psutil.Process().memory_info().rss // 1048576,
                                           cardinal_tools.time_to_str(uptime), m.chat.id))

    def restart_cardinal(self, m: Message):
        """
        Перезапускает кардинал.
        """
        self.bot.send_message(m.chat.id, _("restarting"))
        cardinal_tools.restart_program()

    def ask_power_off(self, m: Message):
        """
        Просит подтверждение на отключение PLATA.
        """
        self.bot.send_message(m.chat.id, _("power_off_0"), reply_markup=kb.power_off(self.cardinal.instance_id, 0))

    def cancel_power_off(self, c: CallbackQuery):
        """
        Отменяет выключение (удаляет клавиатуру с кнопками подтверждения).
        """
        self.bot.edit_message_text(_("power_off_cancelled"), c.message.chat.id, c.message.id)
        self.bot.answer_callback_query(c.id)

    def power_off(self, c: CallbackQuery):
        """
        Отключает PLATA.
        """
        split = c.data.split(":")
        state = int(split[1])
        instance_id = int(split[2])

        if instance_id != self.cardinal.instance_id:
            self.bot.edit_message_text(_("power_off_error"), c.message.chat.id, c.message.id)
            self.bot.answer_callback_query(c.id)
            return

        if state == 6:
            self.bot.edit_message_text(_("power_off_6"), c.message.chat.id, c.message.id)
            self.bot.answer_callback_query(c.id)
            cardinal_tools.shut_down()
            return

        self.bot.edit_message_text(_(f"power_off_{state}"), c.message.chat.id, c.message.id,
                                   reply_markup=kb.power_off(instance_id, state))
        self.bot.answer_callback_query(c.id)

    # Чат FunPay
    def act_send_funpay_message(self, c: CallbackQuery):
        """
        Активирует режим ввода сообщения для отправки его в чат FunPay.
        """
        split = c.data.split(":")
        node_id = int(split[1])
        try:
            username = split[2]
        except IndexError:
            username = None
        result = self.bot.send_message(c.message.chat.id, _("enter_msg_text"), reply_markup=skb.CLEAR_STATE_BTN())
        self.set_state(c.message.chat.id, result.id, c.from_user.id,
                       CBT.SEND_FP_MESSAGE, {"node_id": node_id, "username": username})
        self.bot.answer_callback_query(c.id)

    def send_funpay_message(self, message: Message):
        """
        Отправляет сообщение в чат FunPay.
        """
        data = self.get_state(message.chat.id, message.from_user.id)["data"]
        node_id, username = data["node_id"], data["username"]
        self.clear_state(message.chat.id, message.from_user.id, True)
        response_text = message.text.strip()
        result = self.cardinal.send_message(node_id, response_text, username, watermark=False)
        if result:
            self.bot.reply_to(message, _("msg_sent", node_id, username),
                              reply_markup=kb.reply(node_id, username, again=True, extend=True))
        else:
            self.bot.reply_to(message, _("msg_sending_error", node_id, username),
                              reply_markup=kb.reply(node_id, username, again=True, extend=True))

    def act_upload_image(self, m: Message):
        """
        Активирует режим ожидания изображения для последующей выгрузки на FunPay.
        """
        cbt = CBT.UPLOAD_CHAT_IMAGE if m.text.startswith("/upload_chat_img") else CBT.UPLOAD_OFFER_IMAGE
        result = self.bot.send_message(m.chat.id, _("send_img"), reply_markup=skb.CLEAR_STATE_BTN())
        self.set_state(m.chat.id, result.id, m.from_user.id, cbt)

    def act_upload_backup(self, m: Message):
        """
        Активирует режим ожидания бэкапа.
        """
        result = self.bot.send_message(m.chat.id, _("send_backup"), reply_markup=skb.CLEAR_STATE_BTN())
        self.set_state(m.chat.id, result.id, m.from_user.id, CBT.UPLOAD_BACKUP)

    def act_edit_greetings_text(self, c: CallbackQuery):
        variables = ["v_date", "v_date_text", "v_full_date_text", "v_time", "v_full_time", "v_username",
                     "v_message_text", "v_chat_id", "v_chat_name", "v_photo", "v_sleep"]
        text = f"{_('v_edit_greeting_text')}\n\n{_('v_list')}:\n" + "\n".join(_(i) for i in variables)
        result = self.bot.send_message(c.message.chat.id, text, reply_markup=skb.CLEAR_STATE_BTN())
        self.set_state(c.message.chat.id, result.id, c.from_user.id, CBT.EDIT_GREETINGS_TEXT)
        self.bot.answer_callback_query(c.id)

    def edit_greetings_text(self, m: Message):
        self.clear_state(m.chat.id, m.from_user.id, True)
        self.cardinal.MAIN_CFG["Greetings"]["greetingsText"] = m.text
        logger.info(_("log_greeting_changed", m.from_user.username, m.from_user.id, m.text))
        self.cardinal.save_config(self.cardinal.MAIN_CFG, "configs/_main.cfg")
        keyboard = K() \
            .row(B(_("gl_back"), callback_data=f"{CBT.CATEGORY}:gr"),
                 B(_("gl_edit"), callback_data=CBT.EDIT_GREETINGS_TEXT))
        self.bot.reply_to(m, _("greeting_changed"), reply_markup=keyboard)

    def act_edit_greetings_cooldown(self, c: CallbackQuery):
        text = _('v_edit_greeting_cooldown')
        result = self.bot.send_message(c.message.chat.id, text, reply_markup=skb.CLEAR_STATE_BTN())
        self.set_state(c.message.chat.id, result.id, c.from_user.id, CBT.EDIT_GREETINGS_COOLDOWN)
        self.bot.answer_callback_query(c.id)

    def edit_greetings_cooldown(self, m: Message):
        self.clear_state(m.chat.id, m.from_user.id, True)
        try:
            cooldown = float(m.text)
        except:
            self.bot.reply_to(m, _("gl_error_try_again"))
            return
        self.cardinal.MAIN_CFG["Greetings"]["greetingsCooldown"] = str(cooldown)
        logger.info(_("log_greeting_cooldown_changed", m.from_user.username, m.from_user.id, m.text))
        self.cardinal.save_config(self.cardinal.MAIN_CFG, "configs/_main.cfg")
        keyboard = K() \
            .row(B(_("gl_back"), callback_data=f"{CBT.CATEGORY}:gr"),
                 B(_("gl_edit"), callback_data=CBT.EDIT_GREETINGS_COOLDOWN))
        self.bot.reply_to(m, _("greeting_cooldown_changed").format(m.text), reply_markup=keyboard)

    def act_edit_order_confirm_reply_text(self, c: CallbackQuery):
        variables = ["v_date", "v_date_text", "v_full_date_text", "v_time", "v_full_time", "v_username",
                     "v_order_id", "v_order_link", "v_order_title", "v_game", "v_category", "v_category_fullname",
                     "v_photo", "v_sleep"]
        text = f"{_('v_edit_order_confirm_text')}\n\n{_('v_list')}:\n" + "\n".join(_(i) for i in variables)
        result = self.bot.send_message(c.message.chat.id, text, reply_markup=skb.CLEAR_STATE_BTN())
        self.set_state(c.message.chat.id, result.id, c.from_user.id, CBT.EDIT_ORDER_CONFIRM_REPLY_TEXT)
        self.bot.answer_callback_query(c.id)

    def edit_order_confirm_reply_text(self, m: Message):
        self.clear_state(m.chat.id, m.from_user.id, True)
        self.cardinal.MAIN_CFG["OrderConfirm"]["replyText"] = m.text
        logger.info(_("log_order_confirm_changed", m.from_user.username, m.from_user.id, m.text))
        self.cardinal.save_config(self.cardinal.MAIN_CFG, "configs/_main.cfg")
        keyboard = K() \
            .row(B(_("gl_back"), callback_data=f"{CBT.CATEGORY}:oc"),
                 B(_("gl_edit"), callback_data=CBT.EDIT_ORDER_CONFIRM_REPLY_TEXT))
        self.bot.reply_to(m, _("order_confirm_changed"), reply_markup=keyboard)

    def act_edit_review_reply_text(self, c: CallbackQuery):
        stars = int(c.data.split(":")[1])
        variables = ["v_date", "v_date_text", "v_full_date_text", "v_time", "v_full_time", "v_username",
                     "v_order_id", "v_order_link", "v_order_title", "v_order_params",
                     "v_order_desc_and_params", "v_order_desc_or_params", "v_game", "v_category", "v_category_fullname"]
        text = f"{_('v_edit_review_reply_text', '⭐' * stars)}\n\n{_('v_list')}:\n" + "\n".join(_(i) for i in variables)
        result = self.bot.send_message(c.message.chat.id, text, reply_markup=skb.CLEAR_STATE_BTN())
        self.set_state(c.message.chat.id, result.id, c.from_user.id, CBT.EDIT_REVIEW_REPLY_TEXT, {"stars": stars})
        self.bot.answer_callback_query(c.id)

    def edit_review_reply_text(self, m: Message):
        stars = self.get_state(m.chat.id, m.from_user.id)["data"]["stars"]
        self.clear_state(m.chat.id, m.from_user.id, True)
        self.cardinal.MAIN_CFG["ReviewReply"][f"star{stars}ReplyText"] = m.text
        logger.info(_("log_review_reply_changed", m.from_user.username, m.from_user.id, stars, m.text))
        self.cardinal.save_config(self.cardinal.MAIN_CFG, "configs/_main.cfg")
        keyboard = K() \
            .row(B(_("gl_back"), callback_data=f"{CBT.CATEGORY}:rr"),
                 B(_("gl_edit"), callback_data=f"{CBT.EDIT_REVIEW_REPLY_TEXT}:{stars}"))
        self.bot.reply_to(m, _("review_reply_changed", '⭐' * stars), reply_markup=keyboard)

    def open_reply_menu(self, c: CallbackQuery):
        """
        Открывает меню ответа на сообщение (callback используется в кнопках "назад").
        """
        split = c.data.split(":")
        node_id, username, again = int(split[1]), split[2], int(split[3])
        extend = True if len(split) > 4 and int(split[4]) else False
        self.bot.edit_message_reply_markup(c.message.chat.id, c.message.id,
                                           reply_markup=kb.reply(node_id, username, bool(again), extend))

    def extend_new_message_notification(self, c: CallbackQuery):
        """
        "Расширяет" уведомление о новом сообщении.
        """
        chat_id, username = c.data.split(":")[1:]
        try:
            chat = self.cardinal.account.get_chat(int(chat_id))
        except:
            self.bot.answer_callback_query(c.id)
            self.bot.send_message(c.message.chat.id, _("get_chat_error"))
            return

        text = ""
        if chat.looking_link:
            text += f"<b><i>{_('viewing')}:</i></b>\n<a href=\"{chat.looking_link}\">{chat.looking_text}</a>\n\n"

        messages = chat.messages[-10:]
        last_message_author_id = -1
        last_by_bot = False
        last_badge = None
        last_by_vertex = False
        for i in messages:
            if i.author_id == last_message_author_id and i.by_bot == last_by_bot and i.badge == last_badge and \
                    last_by_vertex == i.by_vertex:
                author = ""
            elif i.author_id == self.cardinal.account.id:
                author = f"<i><b>🤖 {_('you')} (<i>PLATA</i>):</b></i> " if i.by_bot else f"<i><b>🫵 {_('you')}:</b></i> "
                if i.is_autoreply:
                    author = f"<i><b>📦 {_('you')} ({i.badge}):</b></i> "
            elif i.author_id == 0:
                author = f"<i><b>🔵 {i.author}: </b></i>"
            elif i.is_employee:
                author = f"<i><b>🆘 {i.author} ({i.badge}): </b></i>"
            elif i.author == i.chat_name:
                author = f"<i><b>👤 {i.author}: </b></i>"
                if i.is_autoreply:
                    author = f"<i><b>🛍️ {i.author} ({i.badge}):</b></i> "
                elif i.author in self.cardinal.blacklist:
                    author = f"<i><b>🚷 {i.author}: </b></i>"
                elif i.by_bot:
                    author = f"<i><b>🦊 {i.author}: </b></i>"
                elif i.by_vertex:
                    author = f"<i><b>🐺 {i.message.author}: </b></i>"
            else:
                author = f"<i><b>🆘 {i.author} ({_('support')}): </b></i>"
            msg_text = f"<code>{utils.escape(i.text)}</code>" if i.text else \
                f"<a href=\"{i.image_link}\">" \
                f"{self.cardinal.show_image_name and not (i.author_id == self.cardinal.account.id and i.by_bot) and i.image_name or _('photo')}</a>"
            text += f"{author}{msg_text}\n\n"
            last_message_author_id = i.author_id
            last_by_bot = i.by_bot
            last_badge = i.badge
            last_by_vertex = i.by_vertex

        self.bot.edit_message_text(text, c.message.chat.id, c.message.id,
                                   reply_markup=kb.reply(int(chat_id), username, False, False))

    # Ордер
    def ask_confirm_refund(self, call: CallbackQuery):
        """
        Просит подтвердить возврат денег.
        """
        split = call.data.split(":")
        order_id, node_id, username = split[1], int(split[2]), split[3]
        keyboard = kb.new_order(order_id, username, node_id, confirmation=True)
        self.bot.edit_message_reply_markup(call.message.chat.id, call.message.id, reply_markup=keyboard)
        self.bot.answer_callback_query(call.id)

    def cancel_refund(self, call: CallbackQuery):
        """
        Отменяет возврат.
        """
        split = call.data.split(":")
        order_id, node_id, username = split[1], int(split[2]), split[3]
        keyboard = kb.new_order(order_id, username, node_id)
        self.bot.edit_message_reply_markup(call.message.chat.id, call.message.id, reply_markup=keyboard)
        self.bot.answer_callback_query(call.id)

    def refund(self, c: CallbackQuery):
        """
        Оформляет возврат за заказ.
        """
        split = c.data.split(":")
        order_id, node_id, username = split[1], int(split[2]), split[3]
        new_msg = None
        attempts = 3
        while attempts:
            try:
                self.cardinal.account.refund(order_id)
                break
            except:
                if not new_msg:
                    new_msg = self.bot.send_message(c.message.chat.id, _("refund_attempt", order_id, attempts))
                else:
                    self.bot.edit_message_text(_("refund_attempt", order_id, attempts), new_msg.chat.id, new_msg.id)
                attempts -= 1
                time.sleep(1)

        else:
            self.bot.edit_message_text(_("refund_error", order_id), new_msg.chat.id, new_msg.id)

            keyboard = kb.new_order(order_id, username, node_id)
            self.bot.edit_message_reply_markup(c.message.chat.id, c.message.id, reply_markup=keyboard)
            self.bot.answer_callback_query(c.id)
            return

        if not new_msg:
            self.bot.send_message(c.message.chat.id, _("refund_complete", order_id))
        else:
            self.bot.edit_message_text(_("refund_complete", order_id), new_msg.chat.id, new_msg.id)

        keyboard = kb.new_order(order_id, username, node_id, no_refund=True)
        self.bot.edit_message_reply_markup(c.message.chat.id, c.message.id, reply_markup=keyboard)
        self.bot.answer_callback_query(c.id)

    def open_order_menu(self, c: CallbackQuery):
        split = c.data.split(":")
        node_id, username, order_id, no_refund = int(split[1]), split[2], split[3], bool(int(split[4]))
        self.bot.edit_message_reply_markup(c.message.chat.id, c.message.id,
                                           reply_markup=kb.new_order(order_id, username, node_id, no_refund=no_refund))

    # Панель управления
    def open_cp(self, c: CallbackQuery):
        """
        Открывает основное меню настроек (редактирует сообщение).
        """
        self.bot.edit_message_text(self._main_menu_text(), c.message.chat.id, c.message.id,
                                   reply_markup=skb.SETTINGS_SECTIONS())
        self.bot.answer_callback_query(c.id)

    def open_cp2(self, c: CallbackQuery):
        """
        Открывает 2 страницу основного меню настроек (редактирует сообщение).
        """
        self.bot.edit_message_text(_("desc_more"), c.message.chat.id, c.message.id,
                                   reply_markup=skb.SETTINGS_SECTIONS_2())
        self.bot.answer_callback_query(c.id)

    def switch_param(self, c: CallbackQuery):
        """
        Переключает настройки PLATA.
        """
        split = c.data.split(":")
        section, option = split[1], split[2]
        if section == "FunPay" and option == "oldMsgGetMode":
            self.cardinal.switch_msg_get_mode()
        else:
            self.cardinal.MAIN_CFG[section][option] = str(int(not int(self.cardinal.MAIN_CFG[section][option])))
            self.cardinal.save_config(self.cardinal.MAIN_CFG, "configs/_main.cfg")

        sections = {
            "FunPay": kb.main_settings,
            "BlockList": kb.blacklist_settings,
            "NewMessageView": kb.new_message_view_settings,
            "Greetings": kb.greeting_settings,
            "OrderConfirm": kb.order_confirm_reply_settings,
            "ReviewReply": kb.review_reply_settings
        }
        if section == "Telegram":
            self.bot.edit_message_reply_markup(c.message.chat.id, c.message.id,
                                               reply_markup=kb.authorized_users(self.cardinal, offset=int(split[3])))
        elif section == "FunPay":
            self.bot.edit_message_reply_markup(c.message.chat.id, c.message.id,
                                               reply_markup=kb.main_settings(self.cardinal))
        else:
            self.bot.edit_message_reply_markup(c.message.chat.id, c.message.id,
                                               reply_markup=sections[section](self.cardinal))
        logger.info(_("log_param_changed", c.from_user.username, c.from_user.id, option, section,
                      self.cardinal.MAIN_CFG[section][option]))
        self.bot.answer_callback_query(c.id)

    def switch_chat_notification(self, c: CallbackQuery):
        try:
            callback_type, raw_chat_id, notification_type = c.data.split(":", 2)
            chat_id = int(raw_chat_id)
        except (TypeError, ValueError):
            self.bot.answer_callback_query(c.id, "Не удалось изменить настройку.", show_alert=True)
            return

        valid_types = {
            value for key, value in vars(NotificationTypes).items()
            if not key.startswith("_") and isinstance(value, str)
        }
        if notification_type not in valid_types:
            self.bot.answer_callback_query(c.id, "Неизвестный тип уведомления.", show_alert=True)
            return

        result = self.toggle_notification(chat_id, notification_type)
        logger.info(_("log_notification_switched", c.from_user.username, c.from_user.id,
                      notification_type, c.message.chat.id, result))
        self.bot.edit_message_reply_markup(c.message.chat.id, c.message.id,
                                           reply_markup=kb.notifications_settings(self.cardinal, chat_id))
        self.bot.answer_callback_query(c.id, "Уведомление включено" if result else "Уведомление отключено")

    def open_settings_section(self, c: CallbackQuery):
        """
        Открывает выбранную категорию настроек.
        """
        #
        section = c.data.split(":")[1]
        sections = {
            "lang": (_("desc_lang"), kb.language_settings, [self.cardinal]),
            "main": (_("desc_gs"), kb.main_settings, [self.cardinal]),
            "tg": (_("desc_ns", c.message.chat.id), kb.notifications_settings, [self.cardinal, c.message.chat.id]),
            "bl": (_("desc_bl"), kb.blacklist_settings, [self.cardinal]),
            "ar": (_("desc_ar"), skb.AR_SETTINGS, []),
            "ad": (_("desc_ad"), skb.AD_SETTINGS, []),
            "mv": (_("desc_mv"), kb.new_message_view_settings, [self.cardinal]),
            "rr": (_("desc_or"), kb.review_reply_settings, [self.cardinal]),
            "gr": (_("desc_gr", utils.escape(self.cardinal.MAIN_CFG['Greetings']['greetingsText'])),
                   kb.greeting_settings, [self.cardinal]),
            "oc": (_("desc_oc", utils.escape(self.cardinal.MAIN_CFG['OrderConfirm']['replyText'])),
                   kb.order_confirm_reply_settings, [self.cardinal])
        }

        curr = sections[section]
        self.bot.edit_message_text(curr[0], c.message.chat.id, c.message.id, reply_markup=curr[1](*curr[2]))
        self.bot.answer_callback_query(c.id)

    # Прочее
    def cancel_action(self, call: CallbackQuery):
        """
        Обнуляет состояние пользователя по кнопке "Отмена" (CBT.CLEAR_STATE).
        """
        result = self.clear_state(call.message.chat.id, call.from_user.id, True)
        if result is None:
            self.bot.answer_callback_query(call.id)

    def param_disabled(self, c: CallbackQuery):
        """
        Отправляет сообщение о том, что параметр отключен в глобальных переключателях.
        """
        self.bot.answer_callback_query(c.id, _("param_disabled"), show_alert=True)

    def _is_plata_owner(self, user_id: int) -> bool:
        return utils.get_plata_owner_id(self.authorized_users) == int(user_id)

    def analytics_report(self, m: Message):
        arg = self._command_argument(m)
        days = {"day": 1, "week": 7, "month": 30}.get((arg or "month").lower(), 30)
        report = plata_analytics.get_report(days=days)
        totals = ", ".join(f"{value} {currency}" for currency, value in report["totals"].items()) or "нет данных"
        products = "\n".join(f"• {html.escape(str(name))}: {count}" for name, count in report["top_products"]) or "нет данных"
        buyers = "\n".join(f"• @{html.escape(str(name))}: {count}" for name, count in report["top_buyers"]) or "нет данных"
        rub_total = report["totals"].get("RUB", 0)
        average = rub_total / report["sales"] if report["sales"] else 0
        self.bot.send_message(m.chat.id, f"<b>Аналитика PLATA за {days} дн.</b>\n\n"
                              f"Заказов: <b>{report['orders']}</b>\nПродаж: <b>{report['sales']}</b>\n"
                              f"Возвратов: <b>{report['refunds']}</b>\nОборот: <b>{html.escape(totals)}</b>\n\n"
                              f"Средний чек: <b>{average:.2f} RUB</b>\n\n"
                              f"<b>Топ товаров</b>\n{products}\n\n<b>Топ покупателей</b>\n{buyers}",
                              reply_markup=K().add(B("⬅️ Назад", callback_data="plata_menu:back")))

    def analytics(self, m: Message):
        self.analytics_report(m)

    def plugin_help(self, m: Message):
        text = ("<b>🧩 Управление плагинами</b>\n\n"
                "<code>/plugins_audit</code> — проверить плагины и зависимости.\n"
                "<code>/plugin_copy UUID</code> — создать резервную копию.\n"
                "<code>/plugin_recover UUID</code> — восстановить последнюю копию.\n"
                "<code>/plugin_access UUID all</code> — включить плагин для всех аккаунтов.\n"
                "<code>/plugin_access UUID ID1 ID2</code> — включить только для выбранных аккаунтов.\n\n"
                "📦 В карточке плагина — кнопка установки недостающих библиотек.\n\n"
                "UUID указан в карточке плагина в разделе «Плагины».")
        self.bot.send_message(m.chat.id, text,
                              reply_markup=K().add(B("⬅️ Назад", callback_data="plata_menu:back")))

    def plugins_audit(self, m: Message):
        results = plata_plugins.audit_all()
        runtime_missing = plata_plugins.load_missing()
        loaded_plugins = {os.path.basename(item.path): uuid for uuid, item in self.cardinal.plugins.items()}
        good = sum(item["ok"] for item in results)
        bad = len(results) - good
        lines = [f"<b>Аудит плагинов PLATA</b>\n✅ корректных: {good}\n⚠️ проблемных: {bad}"]
        keyboard = K()
        buttons = 0
        for item in results:
            uuid = loaded_plugins.get(item["file"])
            key = uuid or f"file:{item['file']}"
            missing = sorted(set(item.get("missing_dependencies", [])) |
                             set((runtime_missing.get(key) or {}).get("modules") or []))
            if item["ok"] and not missing:
                continue
            detail = ", ".join(item["missing"] + missing) or item["error"] or "ошибка"
            lines.append(f"• <code>{html.escape(item['file'])}</code>: {html.escape(detail)}")
            if missing and buttons < 8:
                keyboard.add(B(_("pl_install_deps") + f" · {item['file']}", None,
                               f"{CBT.INSTALL_PLUGIN_DEPS}:{key}"))
                buttons += 1
        keyboard.add(B("⬅️ Назад", callback_data="plata_menu:back"))
        self.bot.send_message(m.chat.id, "\n".join(lines), reply_markup=keyboard)

    def send_review_reply_text(self, c: CallbackQuery):
        stars = int(c.data.split(":")[1])
        text = self.cardinal.MAIN_CFG["ReviewReply"][f"star{stars}ReplyText"]
        keyboard = K() \
            .row(B(_("gl_back"), callback_data=f"{CBT.CATEGORY}:rr"),
                 B(_("gl_edit"), callback_data=f"{CBT.EDIT_REVIEW_REPLY_TEXT}:{stars}"))
        if not text:
            self.bot.send_message(c.message.chat.id, _("review_reply_empty", "⭐" * stars), reply_markup=keyboard)
        else:
            self.bot.send_message(c.message.chat.id, _("review_reply_text", "⭐" * stars,
                                                       self.cardinal.MAIN_CFG['ReviewReply'][f'star{stars}ReplyText']),
                                  reply_markup=keyboard)
        self.bot.answer_callback_query(c.id)

    def send_old_mode_help_text(self, c: CallbackQuery):
        self.bot.answer_callback_query(c.id)
        self.bot.send_message(c.message.chat.id, _("old_mode_help"))

    def empty_callback(self, c: CallbackQuery):
        self.bot.answer_callback_query(c.id, "PLATA")

    def switch_lang(self, c: CallbackQuery):
        lang = c.data.split(":")[1]
        Localizer(lang)
        self.cardinal.MAIN_CFG["Other"]["language"] = lang
        self.cardinal.save_config(self.cardinal.MAIN_CFG, "configs/_main.cfg")
        if localizer.current_language == "en":
            self.bot.answer_callback_query(c.id, "The translation may be incomplete.", show_alert=True)
        elif localizer.current_language == "uk":
            self.bot.answer_callback_query(c.id, "Переклад може бути неповним.", show_alert=True)
        elif localizer.current_language == "ru":
            self.bot.answer_callback_query(c.id, '«А я сейчас вам покажу, откуда на Беларусь готовилось нападение»',
                                           show_alert=True)
        c.data = f"{CBT.CATEGORY}:lang"
        self.open_settings_section(c)

    def __register_handlers(self):
        """
        Регистрирует хэндлеры всех команд.
        """
        self.mdw_handler(self.setup_chat_notifications, update_types=['message'])
        self.msg_handler(self.reg_admin, func=lambda msg: msg.from_user.id not in self.authorized_users,
                         content_types=['text', 'document', 'photo', 'sticker'])
        self.cbq_handler(self.ignore_unauthorized_users, lambda c: c.from_user.id not in self.authorized_users)
        self.cbq_handler(self.param_disabled, lambda c: c.data.startswith(CBT.PARAM_DISABLED))
        self.msg_handler(self.run_file_handlers, content_types=["photo", "document"],
                         func=lambda m: self.is_file_handler(m))

        self.msg_handler(self.send_settings_menu, commands=["menu", "start"])
        self.msg_handler(self.send_profile, commands=["profile"])
        self.msg_handler(self.send_sales_stats, commands=["stats"])
        self.msg_handler(self.send_all_sales_stats, commands=["stats_all"])
        self.msg_handler(self.send_accounts, commands=["accounts"])
        # Account operations are available only through the account center UI.
        self.msg_handler(self.act_change_cookie, commands=["golden_key"])
        self.msg_handler(self.change_cookie, func=lambda m: self.check_state(m.chat.id, m.from_user.id,
                                                                             CBT.CHANGE_GOLDEN_KEY))
        self.msg_handler(self.add_account_flow_text,
                         func=lambda m: self.check_state(m.chat.id, m.from_user.id, "plata_add_account"))
        self.msg_handler(self.account_update_key_text,
                         func=lambda m: self.check_state(m.chat.id, m.from_user.id, "plata_update_key"))
        self.cbq_handler(self.update_profile, lambda c: c.data == CBT.UPDATE_PROFILE)
        self.msg_handler(self.act_manual_delivery_test, commands=["test_lot"])
        self.msg_handler(self.act_upload_image, commands=["upload_chat_img", "upload_offer_img"])
        self.msg_handler(self.act_upload_backup, commands=["upload_backup"])
        self.cbq_handler(self.act_edit_greetings_text, lambda c: c.data == CBT.EDIT_GREETINGS_TEXT)
        self.msg_handler(self.edit_greetings_text,
                         func=lambda m: self.check_state(m.chat.id, m.from_user.id, CBT.EDIT_GREETINGS_TEXT))
        self.cbq_handler(self.act_edit_greetings_cooldown, lambda c: c.data == CBT.EDIT_GREETINGS_COOLDOWN)
        self.msg_handler(self.edit_greetings_cooldown,
                         func=lambda m: self.check_state(m.chat.id, m.from_user.id, CBT.EDIT_GREETINGS_COOLDOWN))
        self.cbq_handler(self.act_edit_order_confirm_reply_text, lambda c: c.data == CBT.EDIT_ORDER_CONFIRM_REPLY_TEXT)
        self.msg_handler(self.edit_order_confirm_reply_text,
                         func=lambda m: self.check_state(m.chat.id, m.from_user.id, CBT.EDIT_ORDER_CONFIRM_REPLY_TEXT))
        self.cbq_handler(self.act_edit_review_reply_text, lambda c: c.data.startswith(f"{CBT.EDIT_REVIEW_REPLY_TEXT}:"))
        self.msg_handler(self.edit_review_reply_text,
                         func=lambda m: self.check_state(m.chat.id, m.from_user.id, CBT.EDIT_REVIEW_REPLY_TEXT))
        self.msg_handler(self.manual_delivery_text,
                         func=lambda m: self.check_state(m.chat.id, m.from_user.id, CBT.MANUAL_AD_TEST))
        self.msg_handler(self.act_ban, commands=["ban"])
        self.msg_handler(self.ban, func=lambda m: self.check_state(m.chat.id, m.from_user.id, CBT.BAN))
        self.msg_handler(self.act_unban, commands=["unban"])
        self.msg_handler(self.unban, func=lambda m: self.check_state(m.chat.id, m.from_user.id, CBT.UNBAN))
        self.msg_handler(self.send_ban_list, commands=["black_list"])
        self.msg_handler(self.act_edit_watermark, commands=["watermark"])
        self.msg_handler(self.edit_watermark,
                         func=lambda m: self.check_state(m.chat.id, m.from_user.id, CBT.EDIT_WATERMARK))
        self.msg_handler(self.send_logs, commands=["logs"])
        self.msg_handler(self.del_logs, commands=["del_logs"])
        self.msg_handler(self.about, commands=["about"])
        self.msg_handler(self.check_updates, commands=["check_updates"])
        self.msg_handler(self.update, commands=["update"])
        self.msg_handler(self.get_backup, commands=["get_backup"])
        self.msg_handler(self.create_backup, commands=["create_backup"])
        self.msg_handler(self.send_system_info, commands=["sys"])
        self.msg_handler(self.restart_cardinal, commands=["restart"])
        self.msg_handler(self.ask_power_off, commands=["power_off"])
        self.msg_handler(self.analytics_report, commands=["analytics_report"])
        self.msg_handler(self.analytics, commands=["analytics"])
        self.msg_handler(self.plugin_help, commands=["plugin_help"])
        self.msg_handler(self.review_module_edit_text, func=lambda m: self.check_state(m.chat.id, m.from_user.id, "plata_review_edit"))
        self.msg_handler(self.review_reply, commands=["review_reply"])
        self.msg_handler(self.reminder_text, commands=["reminder_text"])
        self.msg_handler(self.plugins_audit, commands=["plugins_audit"])
        self.cbq_handler(self.send_review_reply_text, lambda c: c.data.startswith(f"{CBT.SEND_REVIEW_REPLY_TEXT}:"))

        self.cbq_handler(self.act_send_funpay_message, lambda c: c.data.startswith(f"{CBT.SEND_FP_MESSAGE}:"))
        self.cbq_handler(self.open_reply_menu, lambda c: c.data.startswith(f"{CBT.BACK_TO_REPLY_KB}:"))
        self.cbq_handler(self.extend_new_message_notification, lambda c: c.data.startswith(f"{CBT.EXTEND_CHAT}:"))
        self.msg_handler(self.send_funpay_message,
                         func=lambda m: self.check_state(m.chat.id, m.from_user.id, CBT.SEND_FP_MESSAGE))
        self.cbq_handler(self.ask_confirm_refund, lambda c: c.data.startswith(f"{CBT.REQUEST_REFUND}:"))
        self.cbq_handler(self.cancel_refund, lambda c: c.data.startswith(f"{CBT.REFUND_CANCELLED}:"))
        self.cbq_handler(self.refund, lambda c: c.data.startswith(f"{CBT.REFUND_CONFIRMED}:"))
        self.cbq_handler(self.open_order_menu, lambda c: c.data.startswith(f"{CBT.BACK_TO_ORDER_KB}:"))
        self.cbq_handler(self.open_cp, lambda c: c.data == CBT.MAIN)
        self.cbq_handler(self.open_cp2, lambda c: c.data == CBT.MAIN2)
        self.cbq_handler(self.open_settings_section, lambda c: c.data.startswith(f"{CBT.CATEGORY}:"))
        self.cbq_handler(self.switch_param, lambda c: c.data.startswith(f"{CBT.SWITCH}:"))
        self.cbq_handler(self.switch_chat_notification, lambda c: c.data.startswith(f"{CBT.SWITCH_TG_NOTIFICATIONS}:"))
        self.cbq_handler(self.power_off, lambda c: c.data.startswith(f"{CBT.SHUT_DOWN}:"))
        self.cbq_handler(self.cancel_power_off, lambda c: c.data == CBT.CANCEL_SHUTTING_DOWN)
        self.cbq_handler(self.cancel_action, lambda c: c.data == CBT.CLEAR_STATE)
        self.cbq_handler(self.send_old_mode_help_text, lambda c: c.data == CBT.OLD_MOD_HELP)
        self.cbq_handler(self.empty_callback, lambda c: c.data == CBT.EMPTY)
        self.cbq_handler(self.switch_lang, lambda c: c.data.startswith(f"{CBT.LANG}:"))
        self.cbq_handler(self.add_account_flow_callback, lambda c: c.data == "pa:add")
        self.cbq_handler(self.account_center_action, lambda c: c.data.startswith("pa:"))
        self.cbq_handler(self.golden_key_select, lambda c: c.data.startswith("gk:"))
        self.cbq_handler(self.account_center_page, lambda c: c.data.startswith("pp:"))
        self.cbq_handler(self.plata_menu_callback, lambda c: c.data.startswith("plata_menu:"))
        self.cbq_handler(self.module_callback, lambda c: c.data.startswith("plata_module:"))
        self.cbq_handler(self.notification_center_callback, lambda c: c.data.startswith("plata_notify:"))

    def send_notification(self, text: str | None, keyboard: K | None = None,
                          notification_type: str = utils.NotificationTypes.other, photo: bytes | None = None,
                          pin: bool = False):
        """
        Отправляет сообщение во все чаты для уведомлений из self.notification_settings.

        :param text: текст уведомления.
        :param keyboard: экземпляр клавиатуры.
        :param notification_type: тип уведомления.
        :param photo: фотография (если нужна).
        :param pin: закреплять ли сообщение.
        """
        kwargs = {}
        if keyboard is not None:
            kwargs["reply_markup"] = keyboard
        to_delete = []
        results = {}
        for chat_id in self.notification_settings:
            if notification_type != utils.NotificationTypes.important_announcement and \
                    not self.is_notification_enabled(chat_id, notification_type):
                continue

            try:
                if photo:
                    msg = self.bot.send_photo(chat_id, photo, text, **kwargs)
                else:
                    msg = self.bot.send_message(chat_id, text, **kwargs)

                if notification_type == utils.NotificationTypes.bot_start:
                    self.init_messages.append((msg.chat.id, msg.id))

                if pin:
                    self.bot.pin_chat_message(msg.chat.id, msg.id)
                results[str(chat_id)] = {"ok": True, "message_id": msg.id}
            except Exception as e:
                results[str(chat_id)] = {"ok": False, "error": str(e)[:300]}
                logger.error(_("log_tg_notification_error", chat_id))
                logger.debug("TRACEBACK", exc_info=True)
                if isinstance(e, ApiTelegramException) and (
                        e.result.status_code == 403 or e.result.status_code == 400 and
                        (e.result_json.get('description') in \
                         ("Bad Request: group chat was upgraded to a supergroup chat", "Bad Request: chat not found"))):
                    to_delete.append(chat_id)
                continue
        for chat_id in to_delete:
            if chat_id in self.notification_settings:
                del self.notification_settings[chat_id]
                utils.save_notification_settings(self.notification_settings)
        return results

    def add_command_to_menu(self, command: str, help_text: str) -> None:
        """
        Добавляет команду в список команд (в кнопке menu).

        :param command: текст команды.

        :param help_text: текст справки.
        """
        self.commands[command] = help_text

    def setup_commands(self):
        """
        Устанавливает меню команд.
        """
        for lang in (None, *localizer.languages.keys()):
            commands = [BotCommand(f"/{i}", _(self.commands[i], language=lang)) for i in self.commands]
            self.bot.set_my_commands(commands, language_code=lang)

    def edit_bot(self):
        """
        Изменяет описания и название бота.
        """

        name = self.bot.get_me().full_name
        limit = 64
        add_to_name = ["FunPay Bot | Бот ФанПей", "FunPay Bot", "FunPayBot", "FunPay"]
        new_name = name
        if "vertex" in new_name.lower():
            new_name = ""
        new_name = new_name.split("ㅤ")[0].strip()
        if "funpay" not in new_name.lower():
            for m_name in add_to_name:
                if len(new_name) + 2 + len(m_name) <= limit:
                    new_name = f"{(new_name + ' ').ljust(limit - len(m_name) - 1, 'ㅤ')} {m_name}"
                    break
            if new_name != name:
                self.bot.set_my_name(new_name)
        sh_text = "PLATA — автоматизация продаж и управление FunPay через Telegram"
        res = self.bot.get_my_short_description().short_description
        if res != sh_text:
            self.bot.set_my_short_description(sh_text)
        for i in [None, *localizer.languages.keys()]:
            res = self.bot.get_my_description(i).description
            text = (f"PLATA v{self.cardinal.VERSION}\n\n"
                    "Управление FunPay через Telegram: несколько аккаунтов, автовыдача, "
                    "автоответы, аналитика, уведомления и плагины.\n\n"
                    "🔄 @funpayplata · 🧩 @quantumdeals")
            if res != text:
                self.bot.set_my_description(text, language_code=i)

    def init(self):
        self.__register_handlers()
        logger.info(_("log_tg_initialized"))

    def run(self):
        """
        Запускает поллинг.
        """
        self.send_notification(_("bot_started"), notification_type=utils.NotificationTypes.bot_start)
        self.notify_pending_missing_dependencies()
        k_err = 0
        while True:
            try:
                logger.info(_("log_tg_started", self.bot.user.username))
                self.bot.infinity_polling(logger_level=logging.DEBUG)
            except:
                k_err += 1
                logger.error(_("log_tg_update_error", k_err))
                logger.debug("TRACEBACK", exc_info=True)
                time.sleep(10)
