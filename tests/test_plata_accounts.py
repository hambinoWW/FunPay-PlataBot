import json
import tempfile
import unittest
from pathlib import Path

from plata_accounts import AccountProfile, AccountRegistry


class AccountRegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.registry = AccountRegistry(self.root / "accounts.json")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_account_lifecycle(self):
        self.registry.add(AccountProfile("primary", "Main", "main.cfg"))
        self.registry.add(AccountProfile("shop2", "Second", "shop2.cfg"))

        self.assertEqual(self.registry.active_id(), "primary")
        self.registry.set_active("shop2")
        self.assertEqual(self.registry.active_id(), "shop2")

        self.registry.rename("shop2", "Renamed")
        self.assertEqual(self.registry.get("shop2").name, "Renamed")

        self.registry.set_enabled("shop2", False)
        self.assertFalse(self.registry.get("shop2").enabled)
        self.assertEqual(self.registry.active_id(), "primary")

        self.registry.remove("shop2")
        self.assertIsNone(self.registry.get("shop2"))

    def test_unknown_registry_fields_are_ignored(self):
        self.registry.path.write_text(json.dumps({
            "schema": 2,
            "active": "primary",
            "accounts": [{
                "account_id": "primary",
                "name": "Main",
                "config_path": "main.cfg",
                "enabled": True,
                "future_field": "value",
            }],
        }), encoding="utf-8")

        self.assertEqual(self.registry.list()[0].account_id, "primary")

    def test_invalid_account_id_is_rejected(self):
        base = self.root / "base.cfg"
        base.write_text("[FunPay]\ngolden_key: old\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.registry.create_from_base("Invalid ID", "Name", "a" * 32, str(base))

    def test_corrupt_profile_is_skipped(self):
        self.registry.path.write_text(json.dumps({"accounts": [None, {"account_id": "ok"}]}), encoding="utf-8")
        self.assertEqual(self.registry.list(), [])

    def test_profiles_are_independent(self):
        self.registry.add(AccountProfile("one", "One", "one.cfg"))
        self.registry.add(AccountProfile("two", "Two", "two.cfg"))
        self.registry.rename("one", "Changed")
        self.assertEqual(self.registry.get("one").name, "Changed")
        self.assertEqual(self.registry.get("two").name, "Two")


if __name__ == "__main__":
    unittest.main()
