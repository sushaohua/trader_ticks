"""Smoke tests for trader_ticks (no Futu OpenD required)."""
import json
import os
import sys
import tempfile
import shutil
import unittest
from unittest import mock
from unittest.mock import MagicMock

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


class TestImports(unittest.TestCase):
    def test_core_modules_import(self):
        from core.parquet_engine import ParquetStorageEngine
        from core.futu_client import FutuTickListener
        self.assertTrue(ParquetStorageEngine)
        self.assertTrue(FutuTickListener)


class TestParquetEngine(unittest.TestCase):
    def test_append_and_close(self):
        from core.parquet_engine import ParquetStorageEngine

        cfg_path = os.path.join(PROJECT_ROOT, "configs", "futu_settings.json")
        with open(cfg_path, encoding="utf-8") as f:
            cfg = json.load(f)
        td = tempfile.mkdtemp()
        try:
            cfg = json.loads(json.dumps(cfg))
            cfg["storage"]["base_archive_dir"] = td
            cfg["storage"]["flush_threshold"] = 2
            eng = ParquetStorageEngine(cfg, "HK")
            tick = {
                "code": "HK.TEST",
                "price": 1.0,
                "volume": 100,
                "turnover": 100.0,
                "ticker_direction": "BUY",
                "bid_price": 0.9,
                "ask_price": 1.1,
            }
            eng.append_tick("HK.TEST", tick)
            eng.append_tick("HK.TEST", {**tick, "price": 1.1, "volume": 200})
            eng.close_all()
            import glob
            import pandas as pd

            files = glob.glob(os.path.join(td, "**", "*.parquet"), recursive=True)
            self.assertEqual(len(files), 1)
            df = pd.read_parquet(files[0])
            self.assertEqual(len(df), 2)
        finally:
            shutil.rmtree(td, ignore_errors=True)


class TestFutuListener(unittest.TestCase):
    def test_on_recv_rsp_calls_super(self):
        import queue
        from core.futu_client import FutuTickListener
        from futu import RET_OK
        import pandas as pd

        q = queue.Queue()
        listener = FutuTickListener(q)
        row = {
            "code": "HK.00700",
            "price": 100.0,
            "volume": 500,
            "turnover": 50000.0,
            "ticker_direction": "BUY",
            "bid_price": 99.9,
            "ask_price": 100.1,
        }
        content = pd.DataFrame([row])
        with mock.patch.object(
            FutuTickListener.__bases__[0],
            "on_recv_rsp",
            return_value=(RET_OK, content),
        ):
            ret, _ = listener.on_recv_rsp(MagicMock())
        self.assertEqual(ret, RET_OK)
        self.assertEqual(q.get()["code"], "HK.00700")


class TestDailyReport(unittest.TestCase):
    def test_find_latest_trading_data_exists(self):
        from analyzer import daily_report

        self.assertTrue(callable(daily_report.find_latest_trading_data))


if __name__ == "__main__":
    unittest.main()
