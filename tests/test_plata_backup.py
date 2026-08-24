import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path

from Utils import updater


class BackupTests(unittest.TestCase):
    def test_backup_contains_multi_account_data(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "configs/accounts").mkdir(parents=True)
            (root / "storage/accounts/shop2/products").mkdir(parents=True)
            (root / "storage/cache/update").mkdir(parents=True)
            (root / "plugins").mkdir()
            (root / "configs/accounts.json").write_text(json.dumps({
                "accounts": [{"account_id": "shop2"}],
            }), encoding="utf-8")
            (root / "configs/accounts/shop2.cfg").write_text("[FunPay]\n", encoding="utf-8")
            (root / "storage/accounts/shop2/products/goods.txt").write_text("item", encoding="utf-8")
            (root / "storage/cache/update/temporary.txt").write_text("skip", encoding="utf-8")

            previous_cwd = os.getcwd()
            try:
                os.chdir(root)
                self.assertEqual(updater.create_backup(), 0)
            finally:
                os.chdir(previous_cwd)

            with zipfile.ZipFile(root / "backup.zip") as archive:
                names = set(archive.namelist())
                self.assertIn("configs/accounts.json", names)
                self.assertIn("configs/accounts/shop2.cfg", names)
                self.assertIn("storage/accounts/shop2/products/goods.txt", names)
                self.assertIn("plata-backup.json", names)
                self.assertNotIn("storage/cache/update/temporary.txt", names)
                manifest = json.loads(archive.read("plata-backup.json"))
                self.assertEqual(manifest["accounts"], 1)


if __name__ == "__main__":
    unittest.main()
