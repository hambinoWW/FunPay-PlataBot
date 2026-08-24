import tempfile
import unittest
from pathlib import Path

import plata_plugins


class PluginScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_path = plata_plugins.SCOPES_PATH
        plata_plugins.SCOPES_PATH = Path(self.temp_dir.name) / "account_scopes.json"

    def tearDown(self):
        plata_plugins.SCOPES_PATH = self.old_path
        self.temp_dir.cleanup()

    def test_empty_scope_enables_plugin_for_every_account(self):
        plata_plugins.set_scope("plugin-id", [])
        self.assertTrue(plata_plugins.enabled_for_account("plugin-id", "shop1"))
        self.assertTrue(plata_plugins.enabled_for_account("plugin-id", "shop2"))

    def test_selected_scope_limits_plugin_to_assigned_accounts(self):
        plata_plugins.set_scope("plugin-id", ["shop2", "shop1", "shop1"])
        self.assertEqual(plata_plugins.load_scopes()["plugin-id"], ["shop1", "shop2"])
        self.assertTrue(plata_plugins.enabled_for_account("plugin-id", "shop1"))
        self.assertFalse(plata_plugins.enabled_for_account("plugin-id", "shop3"))


if __name__ == "__main__":
    unittest.main()
