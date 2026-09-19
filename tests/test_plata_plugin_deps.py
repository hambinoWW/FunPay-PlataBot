"""Автоустановка недостающих библиотек плагинов."""

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import plata_plugins

from locales.localizer import Localizer
from tg_bot import CBT, keyboards
from tg_bot.bot import TGBot


ROOT = Path(__file__).resolve().parents[1]


class ExtractMissingModulesTests(unittest.TestCase):
    def test_extracts_module_from_traceback(self):
        text = "Traceback (most recent call last):\n  ...\nModuleNotFoundError: No module named 'telebot'\n"
        self.assertEqual(plata_plugins.extract_missing_modules(text), ["telebot"])

    def test_uses_root_module_and_deduplicates(self):
        text = ("ModuleNotFoundError: No module named 'google.cloud.storage'\n"
                "ModuleNotFoundError: No module named \"google\"\n")
        self.assertEqual(plata_plugins.extract_missing_modules(text), ["google"])

    def test_ignores_unrelated_errors(self):
        self.assertEqual(plata_plugins.extract_missing_modules("KeyError: 'shop'"), [])
        self.assertEqual(plata_plugins.extract_missing_modules(None), [])


class PackageNameTests(unittest.TestCase):
    def test_known_import_names_map_to_pypi_packages(self):
        self.assertEqual(plata_plugins.packages_for(["telebot"]), ["pyTelegramBotAPI"])
        self.assertEqual(plata_plugins.packages_for(["PIL"]), ["Pillow"])
        self.assertEqual(plata_plugins.packages_for(["cv2"]), ["opencv-python"])

    def test_unknown_module_name_is_kept(self):
        self.assertEqual(plata_plugins.packages_for(["some_lib"]), ["some_lib"])

    def test_packages_are_deduplicated(self):
        self.assertEqual(plata_plugins.packages_for(["PIL", "PIL.Image"]), ["Pillow"])

    def test_option_like_names_are_ignored(self):
        self.assertEqual(plata_plugins.packages_for(["--upgrade", "-e", "  "]), [])
        self.assertEqual(plata_plugins.packages_for(["--target", "some_lib"]), ["some_lib"])


class InstallCommandTests(unittest.TestCase):
    def test_install_runs_pip_with_current_interpreter(self):
        completed = mock.Mock(returncode=0, stdout="Successfully installed pyTelegramBotAPI", stderr="")
        with mock.patch("plata_plugins.subprocess.run", return_value=completed) as run:
            result = plata_plugins.install_dependencies(["telebot"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["packages"], ["pyTelegramBotAPI"])
        command = run.call_args[0][0]
        self.assertEqual(command[:3], [sys.executable, "-m", "pip"])
        self.assertIn("pyTelegramBotAPI", command)

    def test_install_reports_failure(self):
        completed = mock.Mock(returncode=1, stdout="", stderr="ERROR: no matching distribution")
        with mock.patch("plata_plugins.subprocess.run", return_value=completed):
            result = plata_plugins.install_dependencies(["nope-package-xyz"])
        self.assertFalse(result["ok"])
        self.assertIn("no matching", result["output"])

    def test_install_timeout_is_reported(self):
        timeout = plata_plugins.subprocess.TimeoutExpired("pip", 1)
        with mock.patch("plata_plugins.subprocess.run", side_effect=timeout):
            result = plata_plugins.install_dependencies(["telebot"])
        self.assertFalse(result["ok"])
        self.assertIn("Превышено время", result["output"])

    def test_empty_module_list_does_nothing(self):
        with mock.patch("plata_plugins.subprocess.run") as run:
            result = plata_plugins.install_dependencies([])
        self.assertFalse(result["ok"])
        run.assert_not_called()


class MissingStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_path = plata_plugins.MISSING_DEPS_PATH
        plata_plugins.MISSING_DEPS_PATH = Path(self.temp_dir.name) / "missing.json"

    def tearDown(self):
        plata_plugins.MISSING_DEPS_PATH = self.old_path
        self.temp_dir.cleanup()

    def test_record_returns_only_new_modules(self):
        self.assertEqual(plata_plugins.record_missing("uuid-1", ["telebot"]), ["telebot"])
        self.assertEqual(plata_plugins.record_missing("uuid-1", ["telebot", "PIL"]), ["PIL"])
        entry = plata_plugins.load_missing()["uuid-1"]
        self.assertEqual(entry["modules"], ["PIL", "telebot"])
        self.assertEqual(entry["source"], "runtime")

    def test_file_keys_are_supported(self):
        plata_plugins.record_missing("file:broken.py", ["cv2"], "load")
        self.assertEqual(plata_plugins.load_missing()["file:broken.py"]["modules"], ["cv2"])

    def test_clear_removes_entry(self):
        plata_plugins.record_missing("uuid-1", ["telebot"])
        plata_plugins.clear_missing("uuid-1")
        self.assertEqual(plata_plugins.load_missing(), {})

    def test_record_ignores_empty_input(self):
        self.assertEqual(plata_plugins.record_missing("", ["telebot"]), [])
        self.assertEqual(plata_plugins.record_missing("uuid-1", []), [])
        self.assertEqual(plata_plugins.load_missing(), {})

    def test_collect_merges_audit_and_runtime_entries(self):
        plugin_file = Path(self.temp_dir.name) / "broken.py"
        plugin_file.write_text("import plata_surely_missing_module_xyz\n", encoding="utf-8")
        plata_plugins.record_missing("uuid-1", ["telebot"], "runtime")
        missing = plata_plugins.collect_missing("uuid-1", plugin_file)
        self.assertIn("plata_surely_missing_module_xyz", missing)
        self.assertIn("telebot", missing)


class PluginCardKeyboardTests(unittest.TestCase):
    def _cardinal(self):
        plugin = SimpleNamespace(enabled=True, pinned=False, commands=[], settings_page=None)
        return SimpleNamespace(plugins={"uuid-1": plugin})

    def _callbacks(self, markup):
        return [button.callback_data for row in markup.keyboard for button in row]

    def test_install_button_appears_when_dependencies_missing(self):
        markup = keyboards.edit_plugin(self._cardinal(), "uuid-1", 0, missing_deps=["telebot"])
        self.assertIn(f"{CBT.INSTALL_PLUGIN_DEPS}:uuid-1", self._callbacks(markup))

    def test_install_button_hidden_without_missing_dependencies(self):
        markup = keyboards.edit_plugin(self._cardinal(), "uuid-1", 0)
        for data in self._callbacks(markup):
            self.assertFalse((data or "").startswith(f"{CBT.INSTALL_PLUGIN_DEPS}:"))


class CallbackConstantTests(unittest.TestCase):
    def test_install_callback_is_unique(self):
        values = [value for name, value in vars(CBT).items() if name.isupper() and isinstance(value, str)]
        self.assertEqual(values.count(CBT.INSTALL_PLUGIN_DEPS), 1)

    def test_plugins_panel_registers_install_handler(self):
        source = (ROOT / "tg_bot" / "plugins_cp.py").read_text(encoding="utf-8")
        self.assertIn("def install_plugin_deps", source)
        self.assertIn("CBT.INSTALL_PLUGIN_DEPS", source)

    def test_core_records_load_and_runtime_errors(self):
        source = (ROOT / "plata_core.py").read_text(encoding="utf-8")
        self.assertIn("plata_plugins.extract_missing_modules(traceback.format_exc())", source)
        self.assertIn("self.report_missing_dependency(func)", source)


class ReportMissingDependencyTests(unittest.TestCase):
    def test_plain_handler_is_ignored(self):
        panel = TGBot.__new__(TGBot)
        with mock.patch("plata_plugins.record_missing") as record:
            try:
                raise ModuleNotFoundError("No module named 'telebot'")
            except ModuleNotFoundError:
                result = TGBot.report_missing_dependency(panel, lambda message: None)
        self.assertFalse(result)
        record.assert_not_called()

    def test_plugin_handler_is_recorded_and_reported(self):
        panel = TGBot.__new__(TGBot)

        def handler(message):
            return None

        handler.plugin_uuid = "uuid-1"
        with mock.patch("plata_plugins.record_missing", return_value=["telebot"]) as record, \
                mock.patch.object(TGBot, "notify_missing_dependency") as notify:
            try:
                raise ModuleNotFoundError("No module named 'telebot'")
            except ModuleNotFoundError:
                result = TGBot.report_missing_dependency(panel, handler, chat_id=5)
        self.assertTrue(result)
        record.assert_called_once_with("uuid-1", ["telebot"], "runtime")
        notify.assert_called_once_with("uuid-1", ["telebot"], 5)

    def test_known_dependency_does_not_notify_again(self):
        panel = TGBot.__new__(TGBot)

        def handler(message):
            return None

        handler.plugin_uuid = "uuid-1"
        with mock.patch("plata_plugins.record_missing", return_value=[]), \
                mock.patch.object(TGBot, "notify_missing_dependency") as notify:
            try:
                raise ModuleNotFoundError("No module named 'telebot'")
            except ModuleNotFoundError:
                result = TGBot.report_missing_dependency(panel, handler)
        self.assertTrue(result)
        notify.assert_not_called()

    def test_handler_module_is_resolved_to_plugin(self):
        panel = TGBot.__new__(TGBot)
        plugin = SimpleNamespace(path=os.path.join("plugins", "demo.py"), name="Demo")
        panel.cardinal = SimpleNamespace(plugins={"uuid-9": plugin})

        def handler(message):
            return None

        handler.__module__ = "plugins.demo"
        with mock.patch("plata_plugins.record_missing", return_value=["telebot"]) as record, \
                mock.patch.object(TGBot, "notify_missing_dependency") as notify:
            try:
                raise ModuleNotFoundError("No module named 'telebot'")
            except ModuleNotFoundError:
                result = TGBot.report_missing_dependency(panel, handler, chat_id=3)
        self.assertTrue(result)
        record.assert_called_once_with("uuid-9", ["telebot"], "runtime")
        notify.assert_called_once_with("uuid-9", ["telebot"], 3)

    def test_unknown_module_of_builtin_handler_is_ignored(self):
        panel = TGBot.__new__(TGBot)
        panel.cardinal = SimpleNamespace(plugins={})

        def handler(message):
            return None

        handler.__module__ = "tg_bot.custom_module"
        self.assertIsNone(TGBot.plugin_key_for_handler(panel, handler))


class DependencyLocalizationTests(unittest.TestCase):
    KEYS = ("pl_install_deps", "pl_deps_installing", "pl_deps_installed", "pl_deps_install_err",
            "pl_deps_nothing", "pl_deps_restart", "pl_missing_deps_notify")

    def test_all_dependency_texts_are_translated(self):
        localizer = Localizer("ru")
        for key in self.KEYS:
            for language in ("ru", "en", "uk"):
                self.assertNotEqual(localizer.translate(key, language=language), key, f"{key} ({language})")


class FakeTelegram:
    def __init__(self):
        self.callbacks = {}
        self.bot = self
        self.messages = []
        self.answers = []

    def cbq_handler(self, handler, func, **kwargs):
        self.callbacks[handler.__name__] = handler

    def msg_handler(self, handler, **kwargs):
        return None

    def set_state(self, *args, **kwargs):
        return None

    def send_message(self, *args, **kwargs):
        self.messages.append((args, kwargs))
        return None

    def edit_message_text(self, *args, **kwargs):
        self.messages.append((args, kwargs))
        return None

    def answer_callback_query(self, *args, **kwargs):
        self.answers.append((args, kwargs))
        return None


class InstallFlowIntegrationTests(unittest.TestCase):
    """Кнопка в карточке плагина запускает установку и отчитывается о результате."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_path = plata_plugins.MISSING_DEPS_PATH
        plata_plugins.MISSING_DEPS_PATH = Path(self.temp_dir.name) / "missing.json"
        self.plugin_file = Path(self.temp_dir.name) / "demo_plugin.py"
        self.plugin_file.write_text("import plata_surely_missing_module_xyz\n", encoding="utf-8")

    def tearDown(self):
        plata_plugins.MISSING_DEPS_PATH = self.old_path
        self.temp_dir.cleanup()

    def _run_install(self, result):
        from tg_bot import plugins_cp

        telegram = FakeTelegram()
        plugin = SimpleNamespace(path=str(self.plugin_file), name="Demo", enabled=True, pinned=False,
                                 commands=[], settings_page=None)
        cardinal = SimpleNamespace(telegram=telegram, plugins={"uuid-1": plugin})
        plugins_cp.init_plugins_cp(cardinal)
        install = telegram.callbacks["install_plugin_deps"]
        query = SimpleNamespace(data=f"{CBT.INSTALL_PLUGIN_DEPS}:uuid-1", id="cb-1",
                                from_user=SimpleNamespace(username="admin", id=42),
                                message=SimpleNamespace(chat=SimpleNamespace(id=7), id=9))
        with mock.patch("plata_plugins.install_dependencies", return_value=result) as install_mock:
            install(query)
            deadline = time.time() + 5
            while time.time() < deadline and len(telegram.messages) < 2:
                time.sleep(0.01)
        return telegram, install_mock

    def test_successful_install_clears_state_and_reports(self):
        telegram, install_mock = self._run_install(
            {"ok": True, "packages": ["pyTelegramBotAPI"], "code": 0, "output": "installed"})
        install_mock.assert_called_once()
        self.assertGreaterEqual(len(telegram.messages), 2)
        final_text = telegram.messages[-1][0][0]
        self.assertIn("установлены", final_text)
        self.assertEqual(plata_plugins.load_missing(), {})

    def test_failed_install_keeps_state_and_shows_retry(self):
        plata_plugins.record_missing("uuid-1", ["plata_surely_missing_module_xyz"], "runtime")
        telegram, _ = self._run_install(
            {"ok": False, "packages": ["pyTelegramBotAPI"], "code": 1, "output": "ERROR: timeout"})
        final_text = telegram.messages[-1][0][0]
        self.assertIn("Не удалось", final_text)
        keyboard = telegram.messages[-1][1].get("reply_markup")
        callbacks = [button.callback_data for row in keyboard.keyboard for button in row]
        self.assertIn(f"{CBT.INSTALL_PLUGIN_DEPS}:uuid-1", callbacks)
        self.assertIn("uuid-1", plata_plugins.load_missing())

    def test_missing_plugin_file_is_reported(self):
        telegram = FakeTelegram()
        cardinal = SimpleNamespace(telegram=telegram, plugins={})
        from tg_bot import plugins_cp
        plugins_cp.init_plugins_cp(cardinal)
        install = telegram.callbacks["install_plugin_deps"]
        query = SimpleNamespace(data=f"{CBT.INSTALL_PLUGIN_DEPS}:file:ghost.py", id="cb-2",
                                from_user=SimpleNamespace(username="admin", id=42),
                                message=SimpleNamespace(chat=SimpleNamespace(id=7), id=9))
        install(query)
        self.assertTrue(telegram.answers)
        self.assertTrue(telegram.answers[-1][1].get("show_alert"))


if __name__ == "__main__":
    unittest.main()
