import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PublicBuildSecurityTests(unittest.TestCase):
    def test_public_build_has_no_gist_write_capability(self):
        sources = "\n".join(path.read_text(encoding="utf-8") for path in ROOT.rglob("*.py")
                            if "storage" not in path.parts and "tests" not in path.parts)
        self.assertNotIn("PLATA_GITHUB_TOKEN", sources)
        self.assertNotIn("broadcast_publish", sources)
        self.assertNotIn("requests.patch", sources)

    def test_official_gist_is_fixed_and_updates_are_disabled(self):
        identity = (ROOT / "plata_identity.py").read_text(encoding="utf-8")
        announcements = (ROOT / "announcements.py").read_text(encoding="utf-8")
        self.assertIn('DEFAULT_ANNOUNCEMENTS_GIST_ID = "8a32dc28ef2d33fa21ed67fd8edab486"', identity)
        self.assertIn('UPDATE_REPOSITORY = ""', identity)
        self.assertNotIn("PLATA_ANNOUNCEMENTS_GIST_ID", announcements)

    def test_zip_extraction_validates_member_paths(self):
        updater = (ROOT / "Utils" / "updater.py").read_text(encoding="utf-8")
        self.assertIn("def _safe_extract", updater)
        self.assertIn("Unsafe archive path", updater)


if __name__ == "__main__":
    unittest.main()
