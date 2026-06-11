import os
import sys
import time
import shutil
import tempfile
import unittest
from unittest import mock
from datetime import datetime
import pytz
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

# 解析项目根路径以正确导入模块
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from core.clickhouse_engine import ClickHouseStorageEngine

class TestClickHouseEngine(unittest.TestCase):
    def setUp(self):
        # 创建标准的模拟配置
        self.config = {
            "clickhouse": {
                "host": "103.118.254.69",
                "port": 8123,
                "username": "sushaohua",
                "password": "7758521.aA",
                "database": "stock_preview"
            },
            "storage": {
                "engine": "clickhouse",
                "flush_threshold": 3,
                "flush_interval_seconds": 2,
                "compression": "snappy"
            }
        }
        
    def test_timezone_parsing(self):
        """测试不同市场的 Tick 时间戳时区解析是否正确"""
        with mock.patch.object(ClickHouseStorageEngine, 'connect_db', return_value=True):
            with mock.patch.object(ClickHouseStorageEngine, '_recovery_worker', return_value=None):
                engine = ClickHouseStorageEngine(self.config, "HK")
                
                # 1. 港股测试 (北京时间 Asia/Shanghai)
                hk_tick = {
                    "code": "HK.00700",
                    "time": "2026-06-09 16:00:00.123",
                    "price": 450.0,
                    "volume": 100
                }
                processed_hk = engine.process_tick(hk_tick)
                self.assertEqual(processed_hk['time'].tzinfo.zone, 'Asia/Shanghai')
                self.assertEqual(processed_hk['time'].hour, 16)
                self.assertEqual(processed_hk['time'].minute, 0)
                
                # 2. 美股测试 (美东时间 America/New_York)
                us_tick = {
                    "code": "US.AAPL",
                    "time": "2026-06-09 09:30:00.500",
                    "price": 180.0,
                    "volume": 200
                }
                processed_us = engine.process_tick(us_tick)
                self.assertEqual(processed_us['time'].tzinfo.zone, 'America/New_York')
                self.assertEqual(processed_us['time'].hour, 9)
                self.assertEqual(processed_us['time'].minute, 30)

    def test_order_book_timezone_parsing(self):
        """测试 OrderBook 盘口数据的时间戳解析与时区化"""
        with mock.patch.object(ClickHouseStorageEngine, 'connect_db', return_value=True):
            with mock.patch.object(ClickHouseStorageEngine, '_recovery_worker', return_value=None):
                engine = ClickHouseStorageEngine(self.config, "HK")
                
                # 测试港股盘口
                hk_ob = {
                    "code": "HK.00700",
                    "name": "TENCENT",
                    "svr_recv_time_ask": "2026-06-09 16:08:10.939",
                    "svr_recv_time_bid": "2026-06-09 16:08:10.938",
                    "ask_prices": [453.4, 453.6],
                    "ask_volumes": [1000, 2000],
                    "ask_orders": [1, 2],
                    "bid_prices": [453.2, 453.0],
                    "bid_volumes": [3000, 4000],
                    "bid_orders": [3, 4]
                }
                processed_hk = engine.process_order_book(hk_ob)
                self.assertEqual(processed_hk['time'].tzinfo.zone, 'Asia/Shanghai')
                from datetime import datetime
                diff = (datetime.now(engine.tz_hk) - processed_hk['time']).total_seconds()
                self.assertTrue(abs(diff) < 10)
                self.assertEqual(processed_hk['ask_prices'][0], 453.4)
                self.assertEqual(processed_hk['bid_volumes'][1], 4000)

    def test_spill_to_disk_on_failure(self):
        """测试 ClickHouse Ticks 写入失败时，数据是否能正确溢出到本地灾备"""
        with mock.patch.object(ClickHouseStorageEngine, 'connect_db', return_value=True):
            with mock.patch.object(ClickHouseStorageEngine, '_recovery_worker', return_value=None):
                temp_failover_dir = tempfile.mkdtemp()
                
                engine = ClickHouseStorageEngine(self.config, "HK")
                engine.failover_dir = temp_failover_dir
                engine.db_connected = False
                engine.client = None
                
                tick1 = {"code": "HK.00700", "time": "2026-06-09 16:00:01.000", "price": 450.0}
                tick2 = {"code": "HK.00700", "time": "2026-06-09 16:00:02.000", "price": 451.0}
                tick3 = {"code": "HK.00700", "time": "2026-06-09 16:00:03.000", "price": 452.0}
                
                engine.append_tick("HK.00700", tick1)
                engine.append_tick("HK.00700", tick2)
                engine.append_tick("HK.00700", tick3)
                
                files = os.listdir(temp_failover_dir)
                self.assertTrue(any(f.startswith("failover_") and not f.startswith("failover_ob_") and f.endswith(".parquet") for f in files))
                
                parquet_file = os.path.join(temp_failover_dir, files[0])
                df = pd.read_parquet(parquet_file)
                self.assertEqual(len(df), 3)
                self.assertEqual(df.iloc[0]['code'], "HK.00700")
                
                shutil.rmtree(temp_failover_dir, ignore_errors=True)

    def test_order_book_spill_to_disk_on_failure(self):
        """测试 ClickHouse OrderBooks 写入失败时，数据溢出灾备逻辑"""
        with mock.patch.object(ClickHouseStorageEngine, 'connect_db', return_value=True):
            with mock.patch.object(ClickHouseStorageEngine, '_recovery_worker', return_value=None):
                temp_failover_dir = tempfile.mkdtemp()
                
                engine = ClickHouseStorageEngine(self.config, "HK")
                engine.failover_dir = temp_failover_dir
                engine.db_connected = False
                engine.client = None
                
                ob = {
                    "code": "HK.00700",
                    "name": "TENCENT",
                    "svr_recv_time_ask": "2026-06-09 16:08:10.000",
                    "ask_prices": [453.4], "ask_volumes": [1000], "ask_orders": [1],
                    "bid_prices": [453.2], "bid_volumes": [2000], "bid_orders": [2]
                }
                
                engine.append_order_book("HK.00700", ob)
                engine.append_order_book("HK.00700", ob)
                engine.append_order_book("HK.00700", ob) # 达到阈值 3 触发落盘
                
                files = os.listdir(temp_failover_dir)
                self.assertTrue(any(f.startswith("failover_ob_") and f.endswith(".parquet") for f in files))
                
                parquet_file = os.path.join(temp_failover_dir, [f for f in files if f.startswith("failover_ob_")][0])
                df = pd.read_parquet(parquet_file)
                self.assertEqual(len(df), 3)
                self.assertEqual(df.iloc[0]['code'], "HK.00700")
                self.assertEqual(list(df.iloc[0]['ask_prices']), [453.4])
                
                shutil.rmtree(temp_failover_dir, ignore_errors=True)

    @unittest.skipIf(os.environ.get("SKIP_INTEGRATION_TESTS"), "跳过 ClickHouse 集成测试")
    def test_database_integration(self):
        """真实的 ClickHouse Ticks 及 OrderBooks 写入集成测试 (如果网络通畅则运行)"""
        engine = ClickHouseStorageEngine(self.config, "HK")
        if not engine.db_connected:
            self.skipTest("ClickHouse 数据库不可达，跳过集成写入测试。")
            
        try:
            # 1. 验证 Ticks 写入
            test_seq = int(time.time() * 1000)
            tick = {
                "code": "HK.TEST_UNIT",
                "name": "TEST_STK",
                "time": "2026-06-09 10:00:00.123",
                "price": 10.5,
                "volume": 500,
                "turnover": 5250.0,
                "ticker_direction": "BUY",
                "sequence": test_seq,
                "type": "NORMAL",
                "push_data_type": "REALTIME"
            }
            engine.append_tick("HK.TEST_UNIT", tick)
            engine.flush_to_db()
            
            res = engine.client.query(f"SELECT * FROM {engine.full_table_path} WHERE code = 'HK.TEST_UNIT' AND sequence = {test_seq}").result_rows
            self.assertEqual(len(res), 1)
            self.assertEqual(res[0][0], "HK.TEST_UNIT")
            
            # 2. 验证 OrderBooks 写入
            ob = {
                "code": "HK.TEST_UNIT",
                "name": "TEST_STK",
                "svr_recv_time_ask": "2026-06-09 10:00:00.123",
                "ask_prices": [10.6, 10.7],
                "ask_volumes": [1000, 2000],
                "ask_orders": [1, 2],
                "bid_prices": [10.4, 10.3],
                "bid_volumes": [3000, 4000],
                "bid_orders": [3, 4]
            }
            engine.append_order_book("HK.TEST_UNIT", ob)
            engine.flush_ob_to_db()
            
            ob_res = engine.client.query(f"SELECT * FROM {engine.ob_full_table_path} WHERE code = 'HK.TEST_UNIT'").result_rows
            self.assertEqual(len(ob_res), 1)
            row = ob_res[0]
            # code=0, name=1, time=2, ask_prices=3, ask_volumes=4, ask_orders=5, bid_prices=6, bid_volumes=7, bid_orders=8
            self.assertEqual(row[0], "HK.TEST_UNIT")
            self.assertEqual(list(row[3]), [10.6, 10.7])
            self.assertEqual(list(row[7]), [3000, 4000])
            
            # 3. 清理测试行
            engine.client.command(f"ALTER TABLE {engine.full_table_path} DELETE WHERE code = 'HK.TEST_UNIT'")
            engine.client.command(f"ALTER TABLE {engine.ob_full_table_path} DELETE WHERE code = 'HK.TEST_UNIT'")
        finally:
            engine.close_all()

    @unittest.skipIf(os.environ.get("SKIP_INTEGRATION_TESTS"), "跳过 ClickHouse 集成测试")
    def test_daily_stock_stats_integration(self):
        """真实的 ClickHouse daily_stock_stats 日 K 线建表及写入集成测试"""
        engine = ClickHouseStorageEngine(self.config, "HK")
        if not engine.db_connected:
            self.skipTest("ClickHouse 数据库不可达，跳过集成写入测试。")
            
        try:
            # 验证表是否创建成功
            exists = engine.client.query(f"EXISTS TABLE {engine.stats_full_table_path}").result_rows[0][0]
            self.assertEqual(exists, 1)
            
            # 写入单条测试日 K 线数据
            from datetime import date
            
            test_df = pd.DataFrame([{
                'code': 'HK.TEST_DAILY',
                'name': 'TEST_STK',
                'time': date(2026, 6, 9),
                'open': 10.0,
                'high': 11.0,
                'low': 9.0,
                'close': 10.5,
                'volume': 10000,
                'turnover': 105000.0,
                'pe_ratio': 15.5,
                'turnover_rate': 0.05,
                'change_rate': 5.0,
                'last_close': 10.0,
                'update_time': datetime.now()
            }])
            
            engine.client.insert_df(engine.stats_full_table_path, test_df)
            
            # 验证是否写入成功
            res = engine.client.query(f"SELECT * FROM {engine.stats_full_table_path} WHERE code = 'HK.TEST_DAILY'").result_rows
            self.assertEqual(len(res), 1)
            self.assertEqual(res[0][0], "HK.TEST_DAILY")
            
            # 清理
            engine.client.command(f"ALTER TABLE {engine.stats_full_table_path} DELETE WHERE code = 'HK.TEST_DAILY'")
        finally:
            engine.close_all()

if __name__ == "__main__":
    unittest.main()
