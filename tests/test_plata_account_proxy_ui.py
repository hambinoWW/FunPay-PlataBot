import os
import tempfile
import time
import unittest
from configparser import ConfigParser
from pathlib import Path
from types import SimpleNamespace

from Utils import plata_tools
from plata_accounts import AccountProfile, AccountRegistry, read_account_proxy
from plata_runtime import PlataRuntime
from tg_bot import account_proxy_cp


class FakeBot:
    def __init__(self):
        self.sent = []
        self.edits = []
        self.markups = []
        self.answers = []
        self.deleted = []
        self.last_message_id = 100

    def send_message(self, chat_id, text, **kwargs):
        self.last_message_id += 1
        self.sent.append((chat_id, text))
        return SimpleNamespace(chat=SimpleNamespace(id=chat_id), id=self.last_message_id, text=text)

    def edit_message_text(self, text, chat_id, message_id, **kwargs):
        self.edits.append(text)
        self.markups.append(kwargs.get("reply_markup"))

    def answer_callback_query(self, callback_id, text=None, show_alert=None):
        self.answers.append(text)

    def delete_message(self, chat_id, message_id):
        self.deleted.append(message_id)


class FakeTelegram:
    def __init__(self, bot):
        self.bot = bot
        self.states = {}
        self.callbacks = []
        self.messages = []
        self.center_renders = []

    def set_state(self, chat_id, message_id, user_id, state, data=None):
        self.states[(chat_id, user_id)] = {"state": state, "mid": message_id, "data": data or {}}

    def get_state(self, chat_id, user_id):
        return self.states.get((chat_id, user_id))

    def check_state(self, chat_id, user_id, state):
        current = self.states.get((chat_id, user_id))
        return bool(current and current["state"] == state)

    def clear_state(self, chat_id, user_id, del_msg=False):
        current = self.states.pop((chat_id, user_id), None)
        if current and del_msg:
            self.bot.delete_message(chat_id, current["mid"])
        return current["mid"] if current else None

    def cbq_handler(self, handler, func=None, **kwargs):
        self.callbacks.append((handler, func))

    def msg_handler(self, handler, **kwargs):
        self.messages.append((handler, kwargs.get("func")))

    def refresh_account_center(self, call, offset=0):
        self.center_renders.append(offset)


def build_callback(data: str, message_id: int = 42):
    return SimpleNamespace(data=data, id="cb", message=SimpleNamespace(chat=SimpleNamespace(id=1), id=message_id),
                           from_user=SimpleNamespace(id=7, language_code="ru"))


def button_texts(markup) -> list[str]:
    markup = markup.get("reply_markup") if isinstance(markup, dict) else markup
    if markup is None:
        return []
    return [button.text for row in markup.keyboard for button in row]


class AccountProxyPanelTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.old_cwd = os.getcwd()
        os.chdir(self.root)
        self.config_path = self.root / "account.cfg"
        self.config_path.write_text("[FunPay]\ngolden_key: " + "a" * 32 + "\n[Proxy]\nenable: 0\nproxy: \n",
                                    encoding="utf-8")
        self.registry = AccountRegistry(self.root / "accounts.json")
        self.registry.add(AccountProfile("primary", "Main", str(self.config_path)))
        self.runtime = PlataRuntime(self.registry, ConfigParser(), ConfigParser(), ConfigParser(), "test")
        self.bot = FakeBot()
        self.telegram = FakeTelegram(self.bot)
        self.cardinal = SimpleNamespace(telegram=self.telegram, runtime=self.runtime,
                                        account_registry=self.registry, account_profile_id="primary",
                                        account=SimpleNamespace(proxy=None))
        account_proxy_cp.init_account_proxy_cp(self.cardinal)

    def tearDown(self):
        os.chdir(self.old_cwd)
        self.temp_dir.cleanup()

    def callback(self, data: str):
        handler = next(handler for handler, func in self.telegram.callbacks if func(build_callback(data)))
        handler(build_callback(data))

    def send_text(self, text: str):
        handler = next(handler for handler, func in self.telegram.messages
                       if func(SimpleNamespace(chat=SimpleNamespace(id=1), from_user=SimpleNamespace(id=7))))
        handler(SimpleNamespace(chat=SimpleNamespace(id=1), id=55, from_user=SimpleNamespace(id=7), text=text))

    def test_panel_shows_account_without_proxy(self):
        self.callback("pap:primary:open:2")
        self.assertIn("Текущий прокси: <b>не задан</b>", self.bot.edits[-1])
        self.assertIn("🔌 <b>Прокси аккаунта</b>", self.bot.edits[-1])

    def test_add_proxy_message_flow(self):
        self.callback("pap:primary:add:3")
        self.assertTrue(self.telegram.states[(1, 7)]["state"] == account_proxy_cp.ACCOUNT_PROXY_STATE)
        self.send_text("1.2.3.4:8080")
        self.assertEqual(read_account_proxy(self.config_path), "http://1.2.3.4:8080")
        self.assertIn("http://1.2.3.4:8080", self.bot.edits[-1])
        self.assertFalse(self.telegram.check_state(1, 7, account_proxy_cp.ACCOUNT_PROXY_STATE))
        self.assertTrue(self.bot.deleted)

    def test_invalid_proxy_keeps_state_and_config(self):
        self.callback("pap:primary:add:0")
        self.send_text("не прокси")
        self.assertIsNone(read_account_proxy(self.config_path))
        self.assertTrue(self.telegram.check_state(1, 7, account_proxy_cp.ACCOUNT_PROXY_STATE))

    def test_message_without_state_is_ignored(self):
        message = SimpleNamespace(chat=SimpleNamespace(id=1), from_user=SimpleNamespace(id=7))
        self.assertTrue(all(not func(message) for _, func in self.telegram.messages))
        self.assertIsNone(read_account_proxy(self.config_path))

    def test_disable_proxy(self):
        self.callback("pap:primary:add:0")
        self.send_text("1.2.3.4:8080")
        self.callback("pap:primary:off:0")
        self.assertIsNone(read_account_proxy(self.config_path))
        self.assertIn("🚫 Прокси отключён.", self.bot.edits[-1])

    def test_choose_proxy_from_list(self):
        plata_tools.register_proxy("5.5.5.5:5555")
        self.callback("pap:primary:list:0:4")
        self.assertIn("Выберите прокси из общего списка:", self.bot.edits[-1])
        self.assertIn("5.5.5.5:5555", " ".join(button_texts(self.bot.markups[-1])))
        self.callback("pap:primary:use:0:4")
        self.assertEqual(read_account_proxy(self.config_path), "http://5.5.5.5:5555")
        self.assertEqual(self.telegram.center_renders, [])

    def test_unknown_account_is_reported(self):
        self.callback("pap:ghost:open:0")
        self.assertEqual(self.bot.answers[-1], "Аккаунт не найден.")

    def test_back_returns_to_account_center(self):
        self.callback("pap:primary:back:8")
        self.assertEqual(self.telegram.center_renders, [8])

    def test_check_proxy_updates_panel(self):
        self.callback("pap:primary:add:0")
        self.send_text("1.2.3.4:8080")
        original = plata_tools.check_proxy
        plata_tools.check_proxy = lambda proxy: True
        try:
            self.callback("pap:primary:check:0")
            deadline = time.time() + 3
            while time.time() < deadline and "✅ Прокси работает." not in self.bot.edits[-1]:
                time.sleep(0.05)
        finally:
            plata_tools.check_proxy = original
        self.assertIn("✅ Прокси работает.", self.bot.edits[-1])


if __name__ == "__main__":
    unittest.main()
