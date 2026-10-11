import unittest
from datetime import date, datetime, timedelta

from app.services.advice import decide
from app.services.analysis import compute_metrics
from app.services.cleaning import detect_bundle, normalize_grade


def _trade(day, price, grade="PSA10", bundle=False, hour=12):
    current = date(2026, 1, 1) + timedelta(days=day)
    return {
        "id": f"{day}-{price}-{grade}-{bundle}",
        "price": price,
        "grade": grade,
        "is_bundle": bundle,
        "trade_date": current,
        "trade_datetime": datetime(current.year, current.month, current.day, hour, 0, 0),
        "card_name": "测试卡",
        "notes": None,
    }


class CleaningTests(unittest.TestCase):
    def test_grade(self):
        self.assertEqual(normalize_grade("PSA 10"), "PSA10")
        self.assertEqual(normalize_grade("PSA-10"), "PSA10")
        self.assertEqual(normalize_grade("pcg10"), "PCG10")
        self.assertEqual(normalize_grade(""), "其他")

    def test_bundle(self):
        self.assertTrue(detect_bundle("[套出] 宝可梦", None))
        self.assertTrue(detect_bundle("皮卡丘", "打包出售"))
        self.assertTrue(detect_bundle("A+B", None))
        self.assertFalse(detect_bundle("宝可梦 SV-P-260", "正常成交"))


class MetricTests(unittest.TestCase):
    def test_seven_day_return(self):
        records = [_trade(day, 100) for day in range(7)] + [_trade(day, 110) for day in range(7, 14)]
        metrics = compute_metrics(records)
        self.assertAlmostEqual(metrics["returns"]["d7"]["return"], 0.1, places=3)
        self.assertEqual(metrics["returns"]["d30"]["return"], None)
        self.assertTrue(any("30" in item for item in metrics["warnings"]))

    def test_bundle_and_grade_excluded(self):
        records = [
            _trade(0, 100),
            _trade(1, 100, grade="PSA9"),
            _trade(2, 9000, bundle=True),
            _trade(3, 120),
        ]
        metrics = compute_metrics(records)
        self.assertEqual(metrics["psa10_count"], 2)
        self.assertEqual(metrics["bundle_count"], 1)
        self.assertEqual(metrics["other_grade_count"], 1)
        self.assertLess(metrics["latest_price"], 200)

    def test_iqr_flags_spike(self):
        records = [_trade(day, 100 + day) for day in range(20)]
        records.append(_trade(21, 4100))
        metrics = compute_metrics(records)
        prices = [row["price"] for row in metrics["anomalies"]]
        self.assertIn(4100, prices)
        self.assertLess(metrics["high"], 4100)

    def test_advice_distribution(self):
        metrics = compute_metrics([_trade(day, 100) for day in range(7)] + [_trade(day, 130) for day in range(7, 14)])
        metrics["returns"]["d7"]["return"] = 0.23
        metrics["returns"]["d30"]["return"] = -0.02
        metrics["volume"]["change_7d"] = -0.71
        decision = decide(metrics)
        self.assertEqual(decision["action"], "卖出/减仓")


class PublishTests(unittest.TestCase):
    def test_rejects_a_non_database(self):
        from pathlib import Path

        from app.services.publish import sqlite_ok

        path = Path("/tmp/quant-not-a-db.bin")
        path.write_bytes(b"not a database")
        self.addCleanup(path.unlink, missing_ok=True)
        self.assertFalse(sqlite_ok(path))

    def test_schedule_stays_off_without_publish_mode(self):
        import os

        from app.services.publish import publish_status, schedule_publish

        os.environ.pop("QUANT_PUBLISH", None)
        schedule_publish()
        self.assertIsNone(publish_status())


if __name__ == "__main__":
    unittest.main()
