"""Тесты настройки остановленного аккаунта PLATA без запуска FunPay."""

import os
import tempfile
import unittest
from configparser import ConfigParser
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import plata_runtime
from plata_accounts import AccountProfile, AccountRegistry, read_account_proxy
from plata_runtime import PlataRuntime
from tg_bot import CBT
from tg_bot.bot import TGBot


MAIN_CONFIG_TEMPLATE = """\
[FunPay]
golden_key: {golden_key}
user_agent: Mozilla/5.0
autoRaise: 0
autoResponse: 0
autoDelivery: 0
multiDelivery: 0
autoRestore: 0
autoDisable: 0
oldMsgGetMode: 0
keepSentMessagesUnread: 0
locale: ru

[Telegram]
enabled: 0
token: 
secretKeyHash: hash
proxy: 
blockLogin: 0

[BlockList]
blockDelivery: 0
blockResponse: 0
blockNewMessageNotification: 0
blockNewOrderNotification: 0
blockCommandNotification: 0

[NewMessageView]
includeMyMessages: 1
includeFPMessages: 1
includeBotMessages: 1
notifyOnlyMyMessages: 0
notifyOnlyFPMessages: 0
notifyOnlyBotMessages: 0
showImageName: 1

[Greetings]
ignoreSystemMessages: 0
onlyNewChats: 0
sendGreetings: 0
greetingsText: Здравствуйте!
greetingsCooldown: 2

[OrderConfirm]
watermark: 1
sendReply: 0
replyText: Спасибо за покупку!

[ReviewReply]
star1Reply: 0
star2Reply: 0
star3Reply: 0
star4Reply: 0
star5Reply: 0
star1ReplyText: 
star2ReplyText: 
star3ReplyText: 
star4ReplyText: 
star5ReplyText: 

[Proxy]
enable: 0
proxy: 
check: 0

[Other]
watermark: 
requestsDelay: 5
language: ru
"""


def write_main_config(path: Path, golden_key: str = "a" * 32) -> Path:
    path.write_text(MAIN_CONFIG_TEMPLATE.format(golden_key=golden_key), encoding="utf-8")
    return path


def read_main_config(path: Path) -> ConfigParser:
    config = ConfigParser(delimiters=(":",), interpolation=None)
    config.optionxform = str
    with path.open("r", encoding="utf-8") as file:
        config.read_file(file)
    return config


class FakePlata:
    """Замена настоящего Plata: конфиги настоящие, сети и FunPay нет."""

    fail_init = False
    created = []

    def __init__(self, main_config, delivery_config, response_config, raw_response_config, version):
        self.MAIN_CFG = main_config
        self.AD_CFG = delivery_config
        self.AR_CFG = response_config
        self.RAW_AR_CFG = raw_response_config
        self.account = SimpleNamespace(golden_key=main_config["FunPay"]["golden_key"],
                                       proxy=None, username=None, active_sales=None)
        self.proxy = {}
        self.proxy_dict = {}
        self.balance = None
        self.telegram = None
        self.initialized = False
        self.running = False
        self.stopped = False
        FakePlata.created.append(self)

    def init(self, account_attempts=None):
        if FakePlata.fail_init:
            raise RuntimeError("golden key is invalid")
        self.initialized = True

    def run(self):
        self.running = True

    def stop(self):
        self.stopped = True


class FakeBot:
    def __init__(self):
        self.sent = []
        self.edits = []
        self.markups = []
        self.answers = []
        self.last_message_id = 100

    def send_message(self, chat_id, text, **kwargs):
        self.last_message_id += 1
        self.sent.append(text)
        self.markups.append(kwargs.get("reply_markup"))
        return SimpleNamespace(chat=SimpleNamespace(id=chat_id), id=self.last_message_id, text=text)

    def edit_message_text(self, text, chat_id, message_id, **kwargs):
        self.edits.append(text)
        self.markups.append(kwargs.get("reply_markup"))

    def answer_callback_query(self, callback_id, text=None, show_alert=None):
        self.answers.append(text)

    def delete_message(self, chat_id, message_id):
        pass


def build_callback(data: str, message_id: int = 42):
    return SimpleNamespace(data=data, id="cb", message=SimpleNamespace(chat=SimpleNamespace(id=1), id=message_id),
                           from_user=SimpleNamespace(id=7, language_code="ru"))


def build_message(text: str):
    return SimpleNamespace(chat=SimpleNamespace(id=1), id=55, from_user=SimpleNamespace(id=7), text=text)


def button_texts(markup) -> list[str]:
    if markup is None:
        return []
    return [button.text for row in markup.keyboard for button in row]


def button_callbacks(markup) -> list[str]:
    if markup is None:
        return []
    return [button.callback_data for row in markup.keyboard for button in row]


class OfflineAccountRuntimeTests(unittest.TestCase):
    """Аккаунт можно выбрать и настроить, даже если он не запущен."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.old_cwd = os.getcwd()
        os.chdir(self.root)
        (self.root / "configs").mkdir()
        (self.root / "configs" / "auto_delivery.cfg").write_text("", encoding="utf-8")
        (self.root / "configs" / "auto_response.cfg").write_text("", encoding="utf-8")
        self.config_path = write_main_config(self.root / "account.cfg")
        self.second_path = write_main_config(self.root / "second.cfg", "b" * 32)
        self.registry = AccountRegistry(self.root / "accounts.json")
        self.registry.add(AccountProfile("primary", "Main", str(self.config_path)))
        self.registry.add(AccountProfile("shop2", "Second", str(self.second_path)))
        self.runtime = PlataRuntime(self.registry, ConfigParser(), ConfigParser(), ConfigParser(), "test")
        self.telegram = SimpleNamespace(cardinal=None)
        self.runtime.telegram = self.telegram
        self.patcher = mock.patch.object(plata_runtime, "Plata", FakePlata)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        FakePlata.fail_init = False
        FakePlata.created = []

    def tearDown(self):
        os.chdir(self.old_cwd)
        self.temp_dir.cleanup()

    def test_select_stopped_account_opens_it_without_network(self):
        instance = self.runtime.select("primary")
        self.assertTrue(self.runtime.is_offline("primary"))
        self.assertIsNone(self.runtime.get("primary"))
        self.assertIs(instance, self.runtime.offline["primary"])
        self.assertIs(self.telegram.cardinal, instance)
        self.assertEqual(self.registry.active_id(), "primary")

    def test_select_disabled_account_is_rejected(self):
        self.registry.set_enabled("primary", False)
        with self.assertRaises(KeyError):
            self.runtime.select("primary")

    def test_failed_start_keeps_account_selectable(self):
        FakePlata.fail_init = True
        with self.assertRaises(RuntimeError):
            self.runtime.start_profile(self.registry.get("primary"))
        self.assertIn("primary", self.runtime.errors)
        self.assertTrue(self.runtime.is_offline("primary"))
        instance = self.runtime.select("primary")
        self.assertIs(self.telegram.cardinal, instance)

    def test_select_works_when_auto_configs_missing(self):
        (self.root / "configs" / "auto_delivery.cfg").unlink()
        (self.root / "configs" / "auto_response.cfg").unlink()
        instance = self.runtime.select("primary")
        self.assertTrue(self.runtime.is_offline("primary"))
        self.assertIsNotNone(instance)

    def test_offline_instance_keeps_changes_and_reuses_on_start(self):
        offline = self.runtime.select("primary")
        self.runtime.set_proxy("primary", "1.2.3.4:8080")
        self.assertEqual(offline.proxy, {"http": "http://1.2.3.4:8080", "https": "http://1.2.3.4:8080"})
        self.assertEqual(read_account_proxy(self.config_path), "http://1.2.3.4:8080")
        started = self.runtime.start_profile(self.registry.get("primary"))
        self.assertIs(started, offline)
        self.assertFalse(self.runtime.is_offline("primary"))
        self.assertIs(self.runtime.get("primary"), offline)
        self.assertTrue(offline.initialized)

    def test_update_golden_key_for_stopped_account(self):
        offline = self.runtime.select("primary")
        profile = self.runtime.update_golden_key("primary", "c" * 32)
        self.assertEqual(profile.account_id, "primary")
        self.assertEqual(read_main_config(self.config_path)["FunPay"]["golden_key"], "c" * 32)
        self.assertEqual(offline.MAIN_CFG["FunPay"]["golden_key"], "c" * 32)
        self.assertEqual(offline.account.golden_key, "c" * 32)

    def test_update_golden_key_rejects_invalid_value(self):
        self.runtime.select("primary")
        with self.assertRaises(ValueError):
            self.runtime.update_golden_key("primary", "слишком короткий")
        self.assertEqual(read_main_config(self.config_path)["FunPay"]["golden_key"], "a" * 32)

    def test_disable_offline_account_switches_panel_to_another(self):
        self.runtime.select("primary")
        self.runtime.disable("primary")
        self.assertFalse(self.runtime.is_offline("primary"))
        self.assertNotIn("primary", self.runtime.offline)
        self.assertEqual(self.registry.active_id(), "shop2")
        self.assertEqual(getattr(self.telegram.cardinal, "account_profile_id", None), "shop2")


class OfflineAccountPanelTests(unittest.TestCase):
    """Кнопки и тексты Telegram-панели для незапущенного аккаунта."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.old_cwd = os.getcwd()
        os.chdir(self.root)
        (self.root / "configs").mkdir()
        (self.root / "configs" / "auto_delivery.cfg").write_text("", encoding="utf-8")
        (self.root / "configs" / "auto_response.cfg").write_text("", encoding="utf-8")
        self.config_path = write_main_config(self.root / "account.cfg")
        self.second_path = write_main_config(self.root / "second.cfg", "b" * 32)
        self.registry = AccountRegistry(self.root / "accounts.json")
        self.registry.add(AccountProfile("primary", "Main", str(self.config_path)))
        self.registry.add(AccountProfile("shop2", "Second", str(self.second_path)))
        self.runtime = PlataRuntime(self.registry, ConfigParser(), ConfigParser(), ConfigParser(), "test")
        self.bot = FakeBot()
        self.panel = TGBot.__new__(TGBot)
        self.panel.bot = self.bot
        self.panel.runtime = self.runtime
        self.panel.user_states = {}
        self.panel.cardinal = SimpleNamespace(account_registry=self.registry, account_profile_id="primary",
                                              balance=None, account=SimpleNamespace(username=None, proxy=None))
        self.runtime.telegram = self.panel
        self.patcher = mock.patch.object(plata_runtime, "Plata", FakePlata)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        FakePlata.fail_init = False
        FakePlata.created = []

    def tearDown(self):
        os.chdir(self.old_cwd)
        self.temp_dir.cleanup()

    def test_stopped_account_has_configure_buttons(self):
        text, keyboard = self.panel._account_center_payload()
        labels = button_texts(keyboard)
        self.assertIn("⚙️ Настроить", labels)
        self.assertIn("▶️ Запустить", labels)
        self.assertIn("🔑 Golden key", labels)
        self.assertIn("ожидает запуска", text)

    def test_configure_action_selects_account_without_starting(self):
        self.panel.account_center_action(build_callback("pa:primary:configure:0"))
        self.assertTrue(self.runtime.is_offline("primary"))
        self.assertEqual(self.bot.answers[-1], "Аккаунт выбран для настройки")
        self.assertTrue(any("изменения сохраняются" in text for text in self.bot.sent))
        self.assertIn("настройка (не запущен)", self.bot.edits[-1])

    def test_main_menu_shows_offline_banner(self):
        self.runtime.select("primary")
        text = self.panel._main_menu_text()
        self.assertIn("🟠 Настройка без запуска", text)
        self.assertIn("Аккаунт не запущен — изменения сохраняются", text)

    def test_profile_is_blocked_while_offline(self):
        self.runtime.select("primary")
        self.panel.send_profile(build_message(""))
        self.assertIn("профиль FunPay появится после запуска", self.bot.sent[-1])

    def test_key_button_asks_for_key_and_saves_it(self):
        self.panel.account_center_action(build_callback("pa:primary:key:0"))
        state = self.panel.get_state(1, 7)
        self.assertEqual(state["state"], "plata_update_key")
        self.assertEqual(state["data"]["account_id"], "primary")
        self.panel.account_update_key_text(build_message("d" * 32))
        self.assertEqual(read_main_config(self.config_path)["FunPay"]["golden_key"], "d" * 32)
        self.assertIsNone(self.panel.get_state(1, 7))
        self.assertTrue(any("Golden key обновлён" in text for text in self.bot.sent))
        self.assertIsNotNone(self.runtime.get("primary"))

    def test_invalid_key_keeps_prompt_and_config(self):
        self.panel.account_center_action(build_callback("pa:primary:key:0"))
        self.panel.account_update_key_text(build_message("короткий"))
        self.assertEqual(self.panel.get_state(1, 7)["state"], "plata_update_key")
        self.assertEqual(read_main_config(self.config_path)["FunPay"]["golden_key"], "a" * 32)
        self.assertIn("Некорректный golden key", self.bot.sent[-1])

    def test_key_is_saved_even_when_start_fails(self):
        FakePlata.fail_init = True
        self.panel.account_center_action(build_callback("pa:primary:key:0"))
        self.panel.account_update_key_text(build_message("e" * 32))
        self.assertEqual(read_main_config(self.config_path)["FunPay"]["golden_key"], "e" * 32)
        self.assertTrue(any("запуск не удался" in text for text in self.bot.sent))
        self.assertTrue(self.runtime.is_offline("primary"))

    def test_golden_key_command_shows_account_picker(self):
        self.panel.act_change_cookie(build_message(""))
        self.assertIn("Для какого аккаунта", self.bot.sent[-1])
        callbacks = button_callbacks(self.bot.markups[-1])
        self.assertIn("gk:primary", callbacks)
        self.assertIn("gk:shop2", callbacks)
        self.assertIsNone(self.panel.get_state(1, 7))

    def test_golden_key_picker_uses_offline_flow_for_stopped_account(self):
        self.runtime.select("primary")
        self.panel.act_change_cookie(build_message(""))
        self.panel.golden_key_select(build_callback("gk:primary"))
        state = self.panel.get_state(1, 7)
        self.assertEqual(state["state"], "plata_update_key")
        self.assertEqual(state["data"]["account_id"], "primary")
        self.assertIn("Main", self.bot.sent[-1])

    def test_golden_key_picker_uses_live_flow_for_running_account(self):
        self.runtime.instances["shop2"] = SimpleNamespace(account_profile_id="shop2")
        self.panel.act_change_cookie(build_message(""))
        labels = button_texts(self.bot.markups[-1])
        self.assertTrue(any(label.startswith("🟢") and "shop2" in label for label in labels))
        self.panel.golden_key_select(build_callback("gk:shop2"))
        self.assertEqual(self.panel.get_state(1, 7)["state"], CBT.CHANGE_GOLDEN_KEY)
        self.assertEqual(self.registry.active_id(), "shop2")
        self.assertIsNotNone(self.runtime.get("shop2"))

    def test_golden_key_command_single_account_goes_straight_to_prompt(self):
        single = AccountRegistry(self.root / "single.json")
        single.add(AccountProfile("primary", "Main", str(self.config_path)))
        self.runtime.registry = single
        self.panel.cardinal.account_registry = single
        self.panel.act_change_cookie(build_message(""))
        self.assertNotIn("Для какого аккаунта", self.bot.sent[-1])
        state = self.panel.get_state(1, 7)
        self.assertEqual(state["state"], "plata_update_key")
        self.assertEqual(state["data"]["account_id"], "primary")


if __name__ == "__main__":
    unittest.main()