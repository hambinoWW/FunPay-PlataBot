"""Проверки меню Telegram-команд PLATA."""

import ast
import inspect
import textwrap
import unittest
from unittest import mock

from locales.localizer import Localizer
from tg_bot.bot import TGBot


def menu_commands() -> dict:
    """Возвращает меню команд, извлечённое из исходника TGBot.__init__."""
    source = textwrap.dedent(inspect.getsource(TGBot.__init__))
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Attribute) and target.attr == "commands" for target in node.targets):
            return {key.value: value.value for key, value in zip(node.value.keys, node.value.values)}
    raise AssertionError("Словарь self.commands не найден")


class CommandMenuTests(unittest.TestCase):
    def test_removed_commands_are_absent_from_menu(self):
        commands = menu_commands()
        for name in ("remove_account", "rename_account", "update_account_key",
                     "use_account", "enable_account", "disable_account", "account_health"):
            self.assertNotIn(name, commands)
        self.assertIn("golden_key", commands)
        self.assertIn("accounts", commands)

    def test_menu_entries_have_translations(self):
        localizer = Localizer("ru")
        for name, key in menu_commands().items():
            for language in ("ru", "en", "uk"):
                self.assertNotEqual(localizer.translate(key, language=language), key, f"{name} ({language})")

    def test_change_cookie_alias_is_not_registered(self):
        panel = TGBot.__new__(TGBot)
        panel.authorized_users = set()
        panel.mdw_handler = mock.Mock()
        panel.msg_handler = mock.Mock()
        panel.cbq_handler = mock.Mock()
        panel._TGBot__register_handlers()
        registered = set()
        for call in panel.msg_handler.call_args_list:
            registered.update(call.kwargs.get("commands") or ())
        self.assertIn("golden_key", registered)
        self.assertNotIn("change_cookie", registered)

    def test_removed_command_methods_are_gone(self):
        for name in ("remove_account", "rename_account", "update_account_key",
                     "use_account", "enable_account", "disable_account"):
            self.assertFalse(hasattr(TGBot, name))

    def test_account_health_method_kept_for_button(self):
        self.assertTrue(hasattr(TGBot, "account_health"))


if __name__ == "__main__":
    unittest.main()
