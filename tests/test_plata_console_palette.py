"""Проверки консольной палитры (256-цветный вариант A)."""

import logging
import unittest
from unittest import mock

from Utils import logger as log_module


class TagPaletteTests(unittest.TestCase):
    """Теги в текстах логов заменяются на фиксированные 256-цветные оттенки."""

    def test_tags_map_to_fixed_256_colors(self):
        colored = log_module.add_colors("$YELLOW#1$RESET $MAGENTA@user$RESET $CYANtext$RESET")
        self.assertIn("\033[38;5;214m", colored)
        self.assertIn("\033[38;5;170m", colored)
        self.assertIn("\033[38;5;79m", colored)
        self.assertNotIn("$YELLOW", colored)

    def test_tag_stripper_keeps_template_variables(self):
        self.assertEqual(log_module.COLOR_TAG_RE.sub("", "$YELLOWstorage/x$RESET и $username"),
                         "storage/x и $username")

    def test_tag_stripper_handles_glued_uppercase_text(self):
        self.assertEqual(log_module.COLOR_TAG_RE.sub("", "$MAGENTATelegram бот запущен."),
                         "Telegram бот запущен.")


class FormatterTests(unittest.TestCase):
    """Форматтеры: в консоль - цвет, в файл - чистый текст."""

    def test_cli_format_keeps_level_color_and_neutral_text(self):
        formatter = log_module.CLILoggerFormatter()
        record = logging.LogRecord("PLATA", logging.WARNING, __file__, 1,
                                   "Лот $YELLOW#123$RESET не найден.", None, None)
        with mock.patch.object(log_module, "console_supports_256_colors", return_value=True):
            rendered = formatter.format(record)
        self.assertIn(log_module.COLOR_TIME, rendered)
        self.assertIn(log_module.COLOR_SEPARATOR, rendered)
        self.assertIn(log_module.LOG_COLORS[logging.WARNING], rendered)
        self.assertIn(log_module.COLOR_TEXT, rendered)
        self.assertIn("\033[38;5;214m", rendered)
        self.assertNotIn("$RESET", rendered)

    def test_file_format_strips_ansi_and_tags(self):
        formatter = log_module.FileLoggerFormatter()
        record = logging.LogRecord("PLATA", logging.INFO, __file__, 1,
                                   "Заказ $YELLOW#1$RESET выдан.", None, None)
        rendered = formatter.format(record)
        self.assertNotIn("\x1b", rendered)
        self.assertNotIn("$YELLOW", rendered)
        self.assertIn("Заказ #1 выдан.", rendered)


class ConsoleFallbackTests(unittest.TestCase):
    """Консоли без 256 цветов (старые Windows) получают ближайшие 16-цветные коды."""

    def test_capable_console_keeps_256_colors(self):
        with mock.patch.object(log_module, "console_supports_256_colors", return_value=True):
            self.assertEqual(log_module.adapt_console_colors("\033[38;5;214mX"), "\033[38;5;214mX")

    def test_legacy_console_gets_16_color_fallback(self):
        with mock.patch.object(log_module, "console_supports_256_colors", return_value=False):
            self.assertEqual(log_module.adapt_console_colors("\033[38;5;214mX\033[48;5;160mY"),
                             "\033[93mX\033[41mY")

    def test_cli_formatter_never_emits_256_codes_on_legacy_console(self):
        formatter = log_module.CLILoggerFormatter()
        record = logging.LogRecord("PLATA", logging.INFO, __file__, 1,
                                   "Товар $YELLOW#1$RESET выдан.", None, None)
        with mock.patch.object(log_module, "console_supports_256_colors", return_value=False):
            rendered = formatter.format(record)
        self.assertNotIn("38;5;", rendered)
        self.assertNotIn("48;5;", rendered)
        self.assertIn("\033[9", rendered)

    def test_every_palette_color_has_fallback(self):
        values = [log_module.COLOR_TIME, log_module.COLOR_SEPARATOR, log_module.COLOR_TEXT,
                  "\033[38;5;110m", *log_module.LOG_COLORS.values(), *log_module.TAG_COLORS.values()]
        for value in values:
            for base, index in log_module.SGR_256_RE.findall(value):
                table = log_module._FALLBACK_BG if base == "48" else log_module._FALLBACK_FG
                self.assertIn(int(index), table, value)

if __name__ == "__main__":
    unittest.main()
