import os
import tempfile
import unittest
from configparser import ConfigParser
from pathlib import Path
from types import SimpleNamespace

from Utils import plata_tools
from plata_accounts import AccountProfile, AccountRegistry, read_account_proxy, write_account_proxy
from plata_runtime import PlataRuntime, apply_proxy_to_instance


def build_config(proxy_enabled: str = "0", proxy: str = "") -> ConfigParser:
    config = ConfigParser(delimiters=(":",), interpolation=None)
    config.optionxform = str
    config.read_string(f"[FunPay]\ngolden_key: {'a' * 32}\n[Proxy]\nenable: {proxy_enabled}\nproxy: {proxy}\n")
    return config


class AccountProxyConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.config_path = self.root / "account.cfg"
        self.config_path.write_text("[FunPay]\ngolden_key: " + "a" * 32 + "\n[Proxy]\nenable: 0\nproxy: \n",
                                    encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_proxy_roundtrip_normalizes_value(self):
        normalized = write_account_proxy(self.config_path, "1.2.3.4:8080")
        self.assertEqual(normalized, "http://1.2.3.4:8080")
        self.assertEqual(read_account_proxy(self.config_path), "http://1.2.3.4:8080")
        config = build_config()
        config.read(self.config_path, encoding="utf-8")
        self.assertEqual(config["Proxy"]["enable"], "1")

    def test_proxy_with_credentials_is_kept(self):
        normalized = write_account_proxy(self.config_path, "socks5://user:pass@10.0.0.1:1080")
        self.assertEqual(normalized, "socks5://user:pass@10.0.0.1:1080")
        self.assertEqual(read_account_proxy(self.config_path), normalized)

    def test_proxy_can_be_disabled(self):
        write_account_proxy(self.config_path, "1.2.3.4:8080")
        self.assertIsNone(write_account_proxy(self.config_path, None))
        self.assertIsNone(read_account_proxy(self.config_path))
        config = build_config()
        config.read(self.config_path, encoding="utf-8")
        self.assertEqual(config["Proxy"]["enable"], "0")
        self.assertEqual(config["Proxy"]["proxy"], "")

    def test_invalid_proxy_is_rejected(self):
        with self.assertRaises(ValueError):
            write_account_proxy(self.config_path, "not-a-proxy")
        self.assertIsNone(read_account_proxy(self.config_path))

    def test_disabled_proxy_is_not_reported(self):
        self.config_path.write_text("[FunPay]\ngolden_key: " + "a" * 32 +
                                    "\n[Proxy]\nenable: 0\nproxy: http://1.2.3.4:8080\n", encoding="utf-8")
        self.assertIsNone(read_account_proxy(self.config_path))

    def test_missing_config_is_safe(self):
        self.assertIsNone(read_account_proxy(self.root / "missing.cfg"))


class AccountRegistryProxyTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.old_cwd = os.getcwd()
        os.chdir(self.root)
        self.registry = AccountRegistry(self.root / "accounts.json")
        self.base = self.root / "base.cfg"
        self.base.write_text("[FunPay]\ngolden_key: " + "a" * 32 +
                             "\n[Proxy]\nenable: 1\nproxy: http://1.2.3.4:8080\n", encoding="utf-8")

    def tearDown(self):
        os.chdir(self.old_cwd)
        self.temp_dir.cleanup()

    def test_new_account_does_not_inherit_proxy(self):
        profile = self.registry.create_from_base("shop2", "Shop", "b" * 32, str(self.base))
        self.assertIsNone(read_account_proxy(profile.config_path))
        self.assertEqual(read_account_proxy(self.base), "http://1.2.3.4:8080")

    def test_accounts_keep_their_own_proxies(self):
        first = self.registry.create_from_base("one", "One", "b" * 32, str(self.base))
        second = self.registry.create_from_base("two", "Two", "c" * 32, str(self.base))
        write_account_proxy(first.config_path, "1.1.1.1:1111")
        write_account_proxy(second.config_path, "2.2.2.2:2222")
        self.assertEqual(read_account_proxy(first.config_path), "http://1.1.1.1:1111")
        self.assertEqual(read_account_proxy(second.config_path), "http://2.2.2.2:2222")


class RuntimeProxyTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.config_path = self.root / "account.cfg"
        self.config_path.write_text("[FunPay]\ngolden_key: " + "a" * 32 + "\n[Proxy]\nenable: 0\nproxy: \n",
                                    encoding="utf-8")
        self.registry = AccountRegistry(self.root / "accounts.json")
        self.registry.add(AccountProfile("primary", "Main", str(self.config_path)))
        self.runtime = PlataRuntime(self.registry, ConfigParser(), ConfigParser(), ConfigParser(), "test")
        self.instance = SimpleNamespace(MAIN_CFG=build_config(), proxy={},
                                        account=SimpleNamespace(proxy=None), proxy_dict={})
        self.runtime.instances["primary"] = self.instance

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_set_proxy_applies_to_running_account(self):
        self.runtime.set_proxy("primary", "9.9.9.9:3128")
        expected = {"http": "http://9.9.9.9:3128", "https": "http://9.9.9.9:3128"}
        self.assertEqual(self.instance.account.proxy, expected)
        self.assertEqual(self.instance.proxy, expected)
        self.assertEqual(self.instance.MAIN_CFG["Proxy"]["enable"], "1")
        self.assertEqual(self.instance.MAIN_CFG["Proxy"]["proxy"], "http://9.9.9.9:3128")
        self.assertEqual(read_account_proxy(self.config_path), "http://9.9.9.9:3128")

    def test_set_proxy_none_disables_proxy(self):
        self.runtime.set_proxy("primary", "9.9.9.9:3128")
        self.runtime.set_proxy("primary", None)
        self.assertIsNone(self.instance.account.proxy)
        self.assertEqual(self.instance.proxy, {})
        self.assertEqual(self.instance.MAIN_CFG["Proxy"]["enable"], "0")
        self.assertIsNone(read_account_proxy(self.config_path))

    def test_unknown_account_is_rejected(self):
        with self.assertRaises(KeyError):
            self.runtime.set_proxy("ghost", "1.2.3.4:8080")

    def test_invalid_proxy_keeps_config_untouched(self):
        with self.assertRaises(ValueError):
            self.runtime.set_proxy("primary", "bad-proxy")
        self.assertIsNone(read_account_proxy(self.config_path))
        self.assertIsNone(self.instance.account.proxy)

    def test_apply_proxy_without_proxy_section(self):
        instance = SimpleNamespace(MAIN_CFG=ConfigParser(), proxy={}, account=SimpleNamespace(proxy={}))
        apply_proxy_to_instance(instance, "1.2.3.4:8080")
        self.assertEqual(instance.MAIN_CFG["Proxy"]["proxy"], "http://1.2.3.4:8080")

    def test_sync_proxy_pool_updates_instances(self):
        old_cwd = os.getcwd()
        os.chdir(self.root)
        try:
            plata_tools.register_proxy("5.5.5.5:5555")
            pool = self.runtime.sync_proxy_pool()
            self.assertEqual(list(pool.values()), ["http://5.5.5.5:5555"])
            self.assertEqual(self.instance.proxy_dict, pool)
        finally:
            os.chdir(old_cwd)


class RegisterProxyTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_cwd = os.getcwd()
        os.chdir(self.temp_dir.name)

    def tearDown(self):
        os.chdir(self.old_cwd)
        self.temp_dir.cleanup()

    def test_register_proxy_adds_only_once(self):
        proxy, created = plata_tools.register_proxy("1.2.3.4:8080")
        self.assertTrue(created)
        self.assertEqual(proxy, "http://1.2.3.4:8080")
        proxy, created = plata_tools.register_proxy("http://1.2.3.4:8080")
        self.assertFalse(created)
        self.assertEqual(proxy, "http://1.2.3.4:8080")
        self.assertEqual(list(plata_tools.load_proxy_dict().values()), ["http://1.2.3.4:8080"])

    def test_register_invalid_proxy(self):
        with self.assertRaises(ValueError):
            plata_tools.register_proxy("1.2.3.4")

    def test_build_proxy_dict(self):
        self.assertEqual(plata_tools.build_proxy_dict(None), {})
        self.assertEqual(plata_tools.build_proxy_dict(""),
                         {})
        self.assertEqual(plata_tools.build_proxy_dict("1.2.3.4:8080"),
                         {"http": "http://1.2.3.4:8080", "https": "http://1.2.3.4:8080"})


if __name__ == "__main__":
    unittest.main()
