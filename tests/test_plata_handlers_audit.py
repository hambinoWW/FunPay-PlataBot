"""Регрессии аудита: утилиты handlers и мёртвый callback-префикс аккаунтов."""

import configparser
import os
import tempfile
import unittest
from pathlib import Path

import handlers


class FakeCardinal:
    """Минимальный двойник PLATA для product_path()."""

    def __init__(self, root: str):
        self.root = root

    def product_path(self, file_name: str) -> str:
        return os.path.join(self.root, file_name)


def lot_section(file_name: str | None) -> configparser.SectionProxy:
    config = configparser.ConfigParser()
    config.add_section("Lot")
    if file_name is not None:
        config["Lot"]["productsFileName"] = file_name
    return config["Lot"]


class CheckProductsAmountTests(unittest.TestCase):
    """check_products_amount не должен падать с NameError."""

    def test_counts_products_from_lot_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "lot.txt"), "w", encoding="utf-8") as file:
                file.write("первый\nвторой\n")
            self.assertEqual(handlers.check_products_amount(FakeCardinal(tmp), lot_section("lot.txt")), 2)

    def test_missing_products_file_counts_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(handlers.check_products_amount(FakeCardinal(tmp), lot_section("nope.txt")), 0)

    def test_section_without_file_name_returns_one(self):
        self.assertEqual(handlers.check_products_amount(FakeCardinal("."), lot_section(None)), 1)


class UtilityReferenceTests(unittest.TestCase):
    """handlers.py не должен звать необъявленные утилиты."""

    def test_source_has_no_cardinal_tools_calls(self):
        source = Path(handlers.__file__).read_text(encoding="utf-8")
        self.assertNotIn("cardinal_tools.", source)

    def test_utility_functions_used_by_handlers_exist(self):
        for name in ("format_msg_text", "format_order_text", "count_products", "get_products",
                     "add_products", "cache_old_users"):
            self.assertTrue(callable(getattr(handlers.plata_tools, name, None)), name)


class DeadAccountCallbackTests(unittest.TestCase):
    """Удалённый callback-префикс plata_account: не должен вернуться."""

    def test_handler_is_removed(self):
        from tg_bot.bot import TGBot
        self.assertFalse(hasattr(TGBot, "switch_account_callback"))

    def test_prefix_is_absent_from_bot_source(self):
        from tg_bot import bot as bot_module
        source = Path(bot_module.__file__).read_text(encoding="utf-8")
        self.assertNotIn("plata_account:", source)


if __name__ == "__main__":
    unittest.main()
