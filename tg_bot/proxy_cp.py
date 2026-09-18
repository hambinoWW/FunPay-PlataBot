"""
В данном модуле описаны функции для ПУ настроек прокси.
Модуль реализован в виде плагина.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING
from tg_bot import utils, static_keyboards as skb, keyboards as kb, CBT
import telebot.apihelper
from Utils.plata_tools import validate_proxy, check_proxy, build_proxy
from Utils import plata_tools
import plata_accounts
from telebot.types import InlineKeyboardMarkup as K, InlineKeyboardButton as B

if TYPE_CHECKING:
    from cardinal import Cardinal
from tg_bot import keyboards as kb, CBT
from telebot.types import CallbackQuery, Message
import logging
from threading import Thread
from locales.localizer import Localizer

logger = logging.getLogger("TGBot")
localizer = Localizer()
_ = localizer.translate


def init_proxy_cp(crd: Cardinal, *args):
    tg = crd.telegram
    bot = tg.bot
    pr_dict = {}

    def check_one_proxy(proxy: str):
        try:
            d = {
                "http": proxy,
                "https": proxy
            }
            pr_dict[proxy] = check_proxy(d)
        except:
            pass

    def check_proxies():
        if crd.MAIN_CFG["Proxy"].getboolean("enable") and crd.MAIN_CFG["Proxy"].getboolean("check"):
            while True:
                for proxy in crd.proxy_dict.values():
                    check_one_proxy(proxy)
                time.sleep(3600)

    Thread(target=check_proxies, daemon=True).start()

    def sync_pool() -> dict:
        """
        Перечитывает общий список прокси с диска (его меняют и другие аккаунты).
        """
        runtime = getattr(crd, "runtime", None)
        if runtime is not None:
            return runtime.sync_proxy_pool()
        pool = plata_tools.load_proxy_dict()
        crd.proxy_dict = pool
        return pool

    def accounts_using_proxy(proxy: str) -> list[str]:
        """
        Возвращает названия аккаунтов, у которых настроен указанный прокси.
        """
        registry = getattr(crd, "account_registry", None)
        if registry is None:
            return []
        names = []
        for profile in registry.list():
            configured = plata_accounts.read_account_proxy(profile.config_path)
            if configured and configured == proxy:
                names.append(profile.name or profile.account_id)
        return names

    def open_proxy_list(c: CallbackQuery):
        """
        Открывает список прокси.
        """
        offset = int(c.data.split(":")[1])
        sync_pool()
        registry = getattr(crd, "account_registry", None)
        account_id = getattr(crd, "account_profile_id", "primary")
        profile = registry.get(account_id) if registry is not None else None
        account = profile.name if profile is not None else account_id
        text = f'\n\nПрокси: {"вкл." if crd.MAIN_CFG["Proxy"].getboolean("enable") else "выкл."}\n' \
               f'Проверка прокси: {"вкл." if crd.MAIN_CFG["Proxy"].getboolean("check") else "выкл."}\n' \
               + _("prx_account", utils.escape(account), utils.escape(str(account_id)))
        bot.edit_message_text(f'{_("desc_proxy")}{text}', c.message.chat.id, c.message.id,
                              reply_markup=kb.proxy(crd, offset, pr_dict))

    def save_proxy(proxy: str) -> None:
        """
        Записывает прокси в конфиг активного аккаунта и применяет его сразу.
        """
        proxy_dict = plata_tools.build_proxy_dict(proxy)
        crd.MAIN_CFG["Proxy"]["enable"] = "1"
        crd.MAIN_CFG["Proxy"]["proxy"] = proxy
        crd.save_config(crd.MAIN_CFG, "configs/_main.cfg")
        crd.proxy = proxy_dict
        if crd.account is not None:
            crd.account.proxy = proxy_dict or None

    def act_add_proxy(c: CallbackQuery):
        """
        Активирует режим ввода прокси для добавления.
        """
        offset = int(c.data.split(":")[-1])
        result = bot.send_message(c.message.chat.id, _("act_proxy"), reply_markup=skb.CLEAR_STATE_BTN())
        crd.telegram.set_state(result.chat.id, result.id, c.from_user.id, CBT.ADD_PROXY, {"offset": offset})
        bot.answer_callback_query(c.id)

    def add_proxy(m: Message):
        """
        Добавляет прокси.
        """
        offset = tg.get_state(m.chat.id, m.from_user.id)["data"]["offset"]
        kb = K().add(B(_("gl_back"), callback_data=f"{CBT.PROXY}:{offset}"))
        tg.clear_state(m.chat.id, m.from_user.id, True)
        proxy = m.text
        try:
            proxy_str = plata_tools.normalize_proxy(proxy)
            if proxy_str in sync_pool().values():
                bot.send_message(m.chat.id, _("proxy_already_exists").format(utils.escape(proxy_str)), reply_markup=kb)
                return
            plata_tools.register_proxy(proxy_str)
            sync_pool()
            bot.send_message(m.chat.id, _("proxy_added").format(utils.escape(proxy_str)), reply_markup=kb)
            Thread(target=check_one_proxy, args=(proxy_str,), daemon=True).start()
        except ValueError:
            bot.send_message(m.chat.id, _("proxy_format"), reply_markup=kb)
        except:
            bot.send_message(m.chat.id, _("proxy_adding_error"), reply_markup=kb)
            logger.debug("TRACEBACK", exc_info=True)

    def choose_proxy(c: CallbackQuery):
        """
        Выбор прокси из списка.
        """
        q, offset, proxy_id = c.data.split(":")
        offset = int(offset)
        proxy_id = int(proxy_id)
        proxy = crd.proxy_dict.get(proxy_id)
        c.data = f"{CBT.PROXY}:{offset}"
        if not proxy:
            open_proxy_list(c)
            return

        scheme, login, password, ip, port = validate_proxy(proxy)
        proxy = build_proxy(scheme, login, password, ip, port)
        save_proxy(proxy)
        open_proxy_list(c)

    def delete_proxy(c: CallbackQuery):
        """
        Удаление прокси.
        """
        q, offset, proxy_id = c.data.split(":")
        offset = int(offset)
        proxy_id = int(proxy_id)
        c.data = f"{CBT.PROXY}:{offset}"
        pool = sync_pool()
        proxy = pool.get(proxy_id)
        if proxy:
            used_by = accounts_using_proxy(proxy)
            if used_by:
                bot.answer_callback_query(c.id, _("proxy_undeletable_account").format(", ".join(used_by)),
                                          show_alert=True)
                return
            now_proxy = crd.account.proxy
            if not now_proxy or now_proxy.get("http") != proxy:
                pool.pop(proxy_id, None)
                plata_tools.cache_proxy_dict(pool)
                sync_pool()
                if proxy in pr_dict:
                    del pr_dict[proxy]
                logger.info(f"Прокси {proxy} удалены.")
            else:
                bot.answer_callback_query(c.id, _("proxy_undeletable"), show_alert=True)
                return

        open_proxy_list(c)

    tg.cbq_handler(open_proxy_list, lambda c: c.data.startswith(f"{CBT.PROXY}:"))
    tg.cbq_handler(act_add_proxy, lambda c: c.data.startswith(f"{CBT.ADD_PROXY}:"))
    tg.cbq_handler(choose_proxy, lambda c: c.data.startswith(f"{CBT.CHOOSE_PROXY}:"))
    tg.cbq_handler(delete_proxy, lambda c: c.data.startswith(f"{CBT.DELETE_PROXY}:"))
    tg.msg_handler(add_proxy, func=lambda m: crd.telegram.check_state(m.chat.id, m.from_user.id, CBT.ADD_PROXY))


BIND_TO_PRE_INIT = [init_proxy_cp]
