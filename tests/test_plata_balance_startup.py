"""Старт бота не должен падать, если баланс аккаунта не удалось получить."""

import unittest
from types import SimpleNamespace
from unittest import mock

import FunPayAPI
from FunPayAPI.common import enums

import plata_core
from Utils import exceptions as plata_exceptions
from Utils import plata_tools
from locales.localizer import Localizer


COMMON = enums.SubCategoryTypes.COMMON
CURRENCY = enums.SubCategoryTypes.CURRENCY


class FakeAccount:
    """Минимальный двойник FunPayAPI.Account для get_balance()."""

    def __init__(self, subcategories=None, lots=None, username="seller", account_id=1, active_sales=0):
        self._subcategories = subcategories if subcategories is not None else {}
        self._lots = lots or {}
        self.username = username
        self.id = account_id
        self.active_sales = active_sales
        self.requested = []
        self.balance_lot_ids = []

    def get(self):
        return None

    def get_sorted_subcategories(self):
        return self._subcategories

    def get_subcategory_public_lots(self, subcategory_type, subcategory_id):
        self.requested.append((subcategory_type, subcategory_id))
        return self._lots.get((subcategory_type, subcategory_id), [])

    def get_balance(self, lot_id):
        self.balance_lot_ids.append(lot_id)
        return FunPayAPI.types.Balance(100.0, 100.0, 0.0, 0.0, 0.0, 0.0)


def make_cardinal(account):
    cardinal = plata_core.Plata.__new__(plata_core.Plata)
    cardinal.account = account
    return cardinal


class GetBalanceTests(unittest.TestCase):
    def test_currency_subcategory_used_when_common_is_empty(self):
        account = FakeAccount({COMMON: {}, CURRENCY: {317: object()}},
                              {(CURRENCY, 317): [SimpleNamespace(id=777)]})
        balance = make_cardinal(account).get_balance()
        self.assertEqual(balance.total_rub, 100.0)
        self.assertEqual(account.balance_lot_ids, [777])

    def test_raises_when_account_has_no_subcategories(self):
        with self.assertRaises(plata_exceptions.BalanceGettingError):
            make_cardinal(FakeAccount({COMMON: {}})).get_balance()

    def test_raises_when_no_public_lots_found(self):
        account = FakeAccount({COMMON: {1: object(), 2: object()}})
        with self.assertRaises(plata_exceptions.BalanceGettingError):
            make_cardinal(account).get_balance(attempts=1)
        self.assertEqual(len(account.requested), 1)

    def test_network_error_is_not_swallowed(self):
        response = SimpleNamespace(status_code=500,
                                   request=SimpleNamespace(url="https://funpay.com/lots/1/", headers={}, body=None))

        class FailingAccount(FakeAccount):
            def get_subcategory_public_lots(self, subcategory_type, subcategory_id):
                raise FunPayAPI.exceptions.RequestFailedError(response)

        account = FailingAccount({COMMON: {1: object()}})
        with self.assertRaises(FunPayAPI.exceptions.RequestFailedError):
            make_cardinal(account).get_balance()


class StartupSurvivesMissingBalanceTests(unittest.TestCase):
    def test_init_account_falls_back_to_zero_balance(self):
        cardinal = make_cardinal(FakeAccount())

        def broken_balance(attempts=3):
            raise plata_exceptions.BalanceGettingError()

        cardinal.get_balance = broken_balance
        with mock.patch.object(plata_tools, "create_greeting_text", return_value="greeting"), \
                mock.patch.object(plata_tools, "set_console_title"):
            result = cardinal._Plata__init_account(1)
        self.assertTrue(result)
        self.assertIsNotNone(cardinal.balance)
        self.assertEqual(cardinal.balance.total_rub, 0.0)
        self.assertEqual(cardinal.balance.available_rub, 0.0)

    def test_init_account_keeps_other_errors_fatal(self):
        cardinal = make_cardinal(FakeAccount())

        def broken_balance(attempts=3):
            raise RuntimeError("boom")

        cardinal.get_balance = broken_balance
        with mock.patch.object(plata_tools, "create_greeting_text", return_value="greeting"), \
                mock.patch.object(plata_tools, "set_console_title"), \
                mock.patch("time.sleep"):
            result = cardinal._Plata__init_account(1)
        self.assertFalse(result)
        self.assertIsNone(getattr(cardinal, "balance", None))


class BalanceLocalizationTests(unittest.TestCase):
    def test_balance_texts_are_translated(self):
        localizer = Localizer("ru")
        for key in ("exc_balance_get_err", "crd_balance_get_warn"):
            for language in ("ru", "en", "uk"):
                self.assertNotEqual(localizer.translate(key, language=language), key, f"{key} ({language})")


if __name__ == "__main__":
    unittest.main()
