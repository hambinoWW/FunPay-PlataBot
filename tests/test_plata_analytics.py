import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import plata_analytics


def order(order_id: str, price: float, status: str = "PAID"):
    return SimpleNamespace(
        id=order_id,
        price=price,
        currency=SimpleNamespace(name="RUB"),
        buyer_username="buyer",
        description="Test lot",
        subcategory=SimpleNamespace(id=1),
        status=SimpleNamespace(name=status),
    )


class AnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_path = plata_analytics.ANALYTICS_PATH
        plata_analytics.ANALYTICS_PATH = Path(self.temp_dir.name) / "analytics.json"

    def tearDown(self):
        plata_analytics.ANALYTICS_PATH = self.old_path
        self.temp_dir.cleanup()

    def test_orders_are_isolated_by_account(self):
        item = order("1", 100)
        self.assertTrue(plata_analytics.record_order(item, "shop1"))
        self.assertTrue(plata_analytics.record_order(item, "shop2"))
        self.assertFalse(plata_analytics.record_order(item, "shop1"))

        self.assertEqual(plata_analytics.get_summary("shop1")["orders"], 1)
        self.assertEqual(plata_analytics.get_summary("shop2")["orders"], 1)
        self.assertEqual(plata_analytics.get_summary()["orders"], 2)

    def test_refund_is_excluded_from_turnover(self):
        item = order("1", 100)
        plata_analytics.record_order(item, "shop1")
        item.status = SimpleNamespace(name="REFUNDED")
        plata_analytics.update_order_status(item, "shop1")

        summary = plata_analytics.get_summary("shop1")
        self.assertEqual(summary["totals"], {})
        self.assertEqual(summary["statuses"], {"REFUNDED": 1})

    def test_report_contains_top_products_buyers_and_average_inputs(self):
        plata_analytics.record_order(order("1", 100), "shop1")
        item = order("2", 300)
        item.description = "Premium lot"
        item.buyer_username = "alice"
        plata_analytics.record_order(item, "shop1")
        report = plata_analytics.get_report(account_id="shop1")
        self.assertEqual(report["sales"], 2)
        self.assertEqual(report["totals"]["RUB"], 400)
        self.assertIn(("alice", 1), report["top_buyers"])
        self.assertIn(("Premium lot", 1), report["top_products"])


if __name__ == "__main__":
    unittest.main()
