import unittest

from locales.localizer import Localizer


class BrandingTests(unittest.TestCase):
    def test_legacy_brand_is_removed_from_visible_text(self):
        localizer = Localizer("ru")
        for language in ("ru", "en", "uk"):
            for key in ("about", "desc_gs", "cmd_restart", "cmd_power_off", "adv_description"):
                text = localizer.translate(key, "1.0", language=language)
                self.assertNotIn("FunPay Cardinal", text)
                self.assertNotIn("FunPayCardinal", text)
                self.assertNotIn("FPC", text)
                self.assertNotIn("@fpc_", text)
                self.assertIn("PLATA", text)

    def test_main_menu_labels_exist_in_all_languages(self):
        localizer = Localizer("ru")
        for language in ("ru", "en", "uk"):
            for key in ("mm_accounts", "mm_stats", "mm_more", "desc_more"):
                self.assertNotEqual(localizer.translate(key, language=language), key)


if __name__ == "__main__":
    unittest.main()
