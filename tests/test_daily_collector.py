import os
import sys
import shutil
import tempfile
import unittest
from unittest import mock
from datetime import datetime, date, timedelta
import pandas as pd

# 解析项目根路径以正确导入模块
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import daily_stats_collector

class TestDailyStatsCollector(unittest.TestCase):
    def setUp(self):
        # 创建一个临时的 failover 目录
        self.temp_failover_dir = tempfile.mkdtemp()
        self.patcher_failover = mock.patch('daily_stats_collector.FAILOVER_DIR', self.temp_failover_dir)
        self.patcher_failover.start()
        
    def tearDown(self):
        self.patcher_failover.stop()
        shutil.rmtree(self.temp_failover_dir, ignore_errors=True)

    @mock.patch('daily_stats_collector.clickhouse_connect.get_client')
    def test_connect_clickhouse_creates_schema(self, mock_get_client):
        """测试 ClickHouse 连接且自动建库建表"""
        mock_client = mock.MagicMock()
        mock_get_client.return_value = mock_client
        
        settings = {
            "clickhouse": {
                "host": "localhost",
                "port": 8123,
                "username": "test",
                "password": "pwd",
                "database": "test_db"
            }
        }
        
        client, full_table = daily_stats_collector.connect_clickhouse(settings)
        
        self.assertEqual(full_table, "test_db.daily_stock_stats")
        self.assertIsNotNone(client)
        
        # 验证是否执行了 DDL 和 CREATE DATABASE
        mock_client.command.assert_any_call("CREATE DATABASE IF NOT EXISTS test_db")
        # 寻找 DDL 语句
        ddl_calls = [call for call in mock_client.command.call_args_list if "CREATE TABLE IF NOT EXISTS" in call[0][0]]
        self.assertTrue(len(ddl_calls) > 0)

    def test_spill_and_recovery_flow(self):
        """测试灾备落盘与自动恢复补录的闭环流程"""
        # 准备假数据
        df_test = pd.DataFrame([{
            'code': 'HK.00700',
            'name': 'TENCENT',
            'time': date(2026, 6, 9),
            'open': 450.0,
            'high': 455.0,
            'low': 448.0,
            'close': 453.0,
            'volume': 500000,
            'turnover': 225000000.0,
            'pe_ratio': 20.0,
            'turnover_rate': 0.1,
            'change_rate': 0.5,
            'last_close': 450.0,
            'update_time': datetime(2026, 6, 11, 10, 0, 0)
        }])
        
        # 1. 模拟落盘
        daily_stats_collector.spill_kline_to_disk(df_test)
        
        # 验证文件是否产生
        files = os.listdir(self.temp_failover_dir)
        self.assertTrue(len(files) == 1)
        self.assertTrue(files[0].startswith("failover_kline_") and files[0].endswith(".parquet"))
        
        # 2. 模拟重放补录
        mock_client = mock.MagicMock()
        daily_stats_collector.recovery_failover_data(mock_client, "test_db.daily_stock_stats")
        
        # 验证 insert_df 是否被调用
        mock_client.insert_df.assert_called_once()
        args, kwargs = mock_client.insert_df.call_args
        self.assertEqual(args[0], "test_db.daily_stock_stats")
        df_recovered = args[1]
        self.assertEqual(df_recovered.iloc[0]['code'], 'HK.00700')
        self.assertEqual(df_recovered.iloc[0]['time'], date(2026, 6, 9))
        
        # 验证文件已被删除
        files_after = os.listdir(self.temp_failover_dir)
        self.assertEqual(len(files_after), 0)

    @mock.patch('daily_stats_collector.OpenQuoteContext')
    @mock.patch('daily_stats_collector.load_config')
    @mock.patch('daily_stats_collector.connect_clickhouse')
    @mock.patch('daily_stats_collector.load_watchlist')
    def test_main_incremental_logic(self, mock_load_watchlist, mock_connect, mock_load_config, mock_quote_context):
        """测试增量逻辑：已有时间戳，并且只拉取比最新日期更晚的数据，并执行过滤"""
        # 设置 Mock 返回
        mock_load_config.return_value = {
            "futu_opend": {"host": "127.0.0.1", "port": 11111},
            "clickhouse": {}
        }
        
        mock_client = mock.MagicMock()
        mock_connect.return_value = (mock_client, "stock_preview.daily_stock_stats")
        
        # Mock 数据库中存在的最大日期是 2026-06-09
        mock_client.query.return_value.result_rows = [
            ("HK.00700", date(2026, 6, 9))
        ]
        
        mock_load_watchlist.return_value = ["HK.00700"]
        
        # Mock 富途 OpenD 接口返回数据，包含 2026-06-09(重复) 和 2026-06-10(新增)
        mock_ctx = mock.MagicMock()
        mock_quote_context.return_value = mock_ctx
        
        df_futu = pd.DataFrame([
            {'code': 'HK.00700', 'name': 'TENCENT', 'time_key': '2026-06-09 00:00:00', 'open': 450.0, 'close': 453.0, 'high': 455.0, 'low': 448.0, 'volume': 500000.0, 'turnover': 225000000.0, 'pe_ratio': 20.0, 'turnover_rate': 0.1, 'change_rate': 0.5, 'last_close': 450.0},
            {'code': 'HK.00700', 'name': 'TENCENT', 'time_key': '2026-06-10 00:00:00', 'open': 453.0, 'close': 457.0, 'high': 458.0, 'low': 452.0, 'volume': 600000.0, 'turnover': 273000000.0, 'pe_ratio': 20.2, 'turnover_rate': 0.12, 'change_rate': 0.88, 'last_close': 453.0}
        ])
        
        mock_ctx.request_history_kline.return_value = (0, df_futu, None)
        
        # 运行 collector 的 main
        with mock.patch('sys.argv', ['daily_stats_collector.py', '--market', 'HK']):
            daily_stats_collector.main()
            
        # 1. 验证起止日期计算是否为 max_date + 1天 即 2026-06-10 到 今天
        mock_ctx.request_history_kline.assert_called_once()
        call_kwargs = mock_ctx.request_history_kline.call_args[1]
        self.assertEqual(call_kwargs['start'], '2026-06-10')
        
        # 2. 验证是否做了去重逻辑并写入了 ClickHouse (由于 2026-06-09 <= 数据库里已存在的最大日期 2026-06-09，应该被剔除，只有 2026-06-10 留存写入)
        mock_client.insert_df.assert_called_once()
        inserted_df = mock_client.insert_df.call_args[0][1]
        
        self.assertEqual(len(inserted_df), 1)
        self.assertEqual(inserted_df.iloc[0]['time'], date(2026, 6, 10))

if __name__ == '__main__':
    unittest.main()
