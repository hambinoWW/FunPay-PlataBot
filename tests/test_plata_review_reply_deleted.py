"""Тесты модуля «Ответы на отзывы»: ответ на удалённый отзыв."""

import configparser
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from FunPayAPI.types import MessageTypes

from plata_modules import review_reply
from tg_bot.bot import TGBot


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


class FakeCardinal:
    account_profile_id = "primary"
    old_mode_enabled = False

    def __init__(self, order=None):
        self.order = order
        self.sent = []

    def get_order_from_object(self, obj):
        return self.order

    def send_message(self, chat_id, text, watermark=True):
        self.sent.append((chat_id, text, watermark))


def build_callback(data: str, message_id: int = 42):
    return SimpleNamespace(data=data, id="cb", message=SimpleNamespace(chat=SimpleNamespace(id=1), id=message_id),
                           from_user=SimpleNamespace(id=7, language_code="ru"))


def build_message(text: str):
    return SimpleNamespace(chat=SimpleNamespace(id=1), id=55, from_user=SimpleNamespace(id=7), text=text)


def button_callbacks(markup) -> list:
    if markup is None:
        return []
    return [button.callback_data for row in markup.keyboard for button in row]


class TempWorkdirTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_cwd = os.getcwd()
        os.chdir(self.temp_dir.name)

    def tearDown(self):
        os.chdir(self.old_cwd)
        self.temp_dir.cleanup()


class ReviewReplyPanelTests(TempWorkdirTestCase):
    """UI модуля позволяет задать текст ответа на удалённый отзыв."""

    def setUp(self):
        super().setUp()
        self.bot = FakeBot()
        self.panel = TGBot.__new__(TGBot)
        self.panel.bot = self.bot
        self.panel.user_states = {}
        self.panel.cardinal = SimpleNamespace(account_profile_id="primary", balance=None,
                                              account=SimpleNamespace(username=None, proxy=None))

    def test_menu_has_text_button_for_deleted_review(self):
        self.panel.review_module_menu(build_callback("plata_module:review:menu"))
        callbacks = button_callbacks(self.bot.markups[-1])
        self.assertIn("plata_module:review:star:6", callbacks)
        self.assertIn("plata_module:review:edit:6", callbacks)

    def test_edit_flow_saves_text_for_deleted_review(self):
        self.panel.module_callback(build_callback("plata_module:review:edit:6"))
        state = self.panel.get_state(1, 7)
        self.assertEqual(state["state"], "plata_review_edit")
        self.assertEqual(state["data"]["star"], "6")
        self.assertTrue(any("удалённого отзыва" in text for text in self.bot.sent))
        self.panel.review_module_edit_text(build_message("Спасибо, что были с нами!"))
        data = review_reply._settings("primary")
        self.assertEqual(data["replies"]["6"]["text"], "Спасибо, что были с нами!")
        self.assertTrue(data["replies"]["6"]["enabled"])
        self.assertIsNone(self.panel.get_state(1, 7))

    def test_command_saves_text_for_deleted_review(self):
        self.panel.review_reply(build_message("/review_reply deleted Спасибо, что были с нами!"))
        data = review_reply._settings("primary")
        self.assertEqual(data["replies"]["6"]["text"], "Спасибо, что были с нами!")
        self.assertTrue(data["replies"]["6"]["enabled"])

    def test_command_accepts_star_six_for_deleted_review(self):
        self.panel.review_reply(build_message("/review_reply 6 Спасибо за отзыв!"))
        self.assertEqual(review_reply._settings("primary")["replies"]["6"]["text"], "Спасибо за отзыв!")

    def test_menu_warns_when_reply_enabled_without_text(self):
        self.panel.module_callback(build_callback("plata_module:review:star:6"))
        self.assertTrue(review_reply._settings("primary")["replies"]["6"]["enabled"])
        self.panel.review_module_menu(build_callback("plata_module:review:menu"))
        self.assertIn("⚠️", self.bot.edits[-1])
        self.assertIn("удалённый отзыв", self.bot.edits[-1])


class ReviewReplyModuleTests(TempWorkdirTestCase):
    """Модуль отправляет ответ, заданный для удалённого отзыва."""

    def test_deleted_review_reply_is_sent(self):
        data = review_reply._settings("primary")
        data["enabled"] = True
        data["replies"]["6"] = {"enabled": True, "text": "Спасибо, что были с нами!"}
        review_reply._save("primary", data)
        cardinal = FakeCardinal(SimpleNamespace())
        message = SimpleNamespace(type=MessageTypes.FEEDBACK_DELETED, chat_id=777, i_am_buyer=False, id=777)
        with mock.patch.object(review_reply, "format_order_text", lambda text, order: text):
            review_reply.on_message(cardinal, SimpleNamespace(message=message))
        self.assertEqual(cardinal.sent, [(777, "Спасибо, что были с нами!", True)])

    def test_deleted_review_without_text_is_skipped(self):
        data = review_reply._settings("primary")
        data["enabled"] = True
        data["replies"]["6"] = {"enabled": True, "text": ""}
        review_reply._save("primary", data)
        cardinal = FakeCardinal(SimpleNamespace())
        message = SimpleNamespace(type=MessageTypes.FEEDBACK_DELETED, chat_id=777, i_am_buyer=False, id=777)
        review_reply.on_message(cardinal, SimpleNamespace(message=message))
        self.assertEqual(cardinal.sent, [])


class _SyncThread:
    """Thread-заглушка: выполняет цель сразу в текущем потоке."""

    def __init__(self, target=None, args=(), kwargs=None, daemon=None, name=None):
        self.target, self.args, self.kwargs = target, args or (), kwargs or {}

    def start(self):
        if self.target:
            self.target(*self.args, **self.kwargs)

    def join(self):
        pass


class ReviewReplyNoDoubleReplyTests(TempWorkdirTestCase):
    """Старый механизм ответов не дублирует ответ, когда отвечает встроенный модуль."""

    def setUp(self):
        super().setUp()
        import handlers
        self.handlers = handlers
        config = configparser.ConfigParser()
        config.read_dict({"ReviewReply": {"star5Reply": "1", "star5ReplyText": "Старый ответ"}})
        self.order = SimpleNamespace(id=101, chat_id=777,
                                     review=SimpleNamespace(stars=5, text="Отзыв", hidden=False))
        self.sent_reviews = []
        self.cardinal = SimpleNamespace(
            old_mode_enabled=False, account_profile_id="primary", MAIN_CFG=config, telegram=None,
            get_order_from_object=lambda obj: self.order,
            account=SimpleNamespace(send_review=lambda order_id, text: self.sent_reviews.append((order_id, text))))
        self.event = SimpleNamespace(message=SimpleNamespace(
            type=MessageTypes.NEW_FEEDBACK, i_am_buyer=False, chat_id=777, id=777))

    def _run(self):
        with mock.patch.object(self.handlers, "Thread", _SyncThread), \
                mock.patch.object(self.handlers.plata_tools, "format_order_text", lambda text, order: text):
            self.handlers.process_review_handler(self.cardinal, self.event)

    def test_old_reply_is_sent_when_module_disabled(self):
        self._run()
        self.assertEqual(self.sent_reviews, [(101, "Старый ответ")])

    def test_old_reply_is_skipped_when_module_replies(self):
        data = review_reply._settings("primary")
        data["enabled"] = True
        data["replies"]["5"] = {"enabled": True, "text": "Ответ модуля"}
        review_reply._save("primary", data)
        self._run()
        self.assertEqual(self.sent_reviews, [])


class ReviewReplyCommandTests(unittest.TestCase):
    """Команда /review_reply действительно зарегистрирована в боте."""

    def test_review_reply_command_handler_is_registered(self):
        panel = TGBot.__new__(TGBot)
        panel.authorized_users = set()
        panel.mdw_handler = mock.Mock()
        panel.msg_handler = mock.Mock()
        panel.cbq_handler = mock.Mock()
        panel._TGBot__register_handlers()
        names = {getattr(call.args[0], "__name__", None) for call in panel.msg_handler.call_args_list if call.args}
        self.assertIn("review_reply", names)
        commands = {tuple(call.kwargs.get("commands") or ()) for call in panel.msg_handler.call_args_list}
        self.assertIn(("review_reply",), commands)


if __name__ == "__main__":
    unittest.main()
