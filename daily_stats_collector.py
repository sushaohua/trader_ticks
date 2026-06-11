import os
import sys
import json
import time
import argparse
import logging
from datetime import datetime, timedelta
import pandas as pd
import clickhouse_connect
from futu import *

# =====================================================================
# 1. 配置日志与路径
# =====================================================================
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(PROJECT_ROOT, 'data', 'logs')
os.makedirs(LOG_DIR, exist_ok=True)
log_file_path = os.path.join(LOG_DIR, 'daily_stats_collector.log')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(threadName)s | %(message)s',
    handlers=[
        logging.FileHandler(log_file_path, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("DailyStatsCollector")

# 引入配置加载模块
sys.path.insert(0, PROJECT_ROOT)
from core.config import load_config

# =====================================================================
# 2. ClickHouse 与 灾备逻辑
# =====================================================================
FAILOVER_DIR = os.path.join(PROJECT_ROOT, "data", "daily_stats_failover")
os.makedirs(FAILOVER_DIR, exist_ok=True)

def connect_clickhouse(settings):
    """连接 ClickHouse，返回 client 和完整表名"""
    ch_cfg = settings["clickhouse"]
    host = ch_cfg["host"]
    port = int(ch_cfg["port"])
    username = ch_cfg["username"]
    password = ch_cfg["password"]
    database = ch_cfg.get("database", "stock_preview")
    full_table = f"{database}.daily_stock_stats"
    
    try:
        client = clickhouse_connect.get_client(
            host=host,
            port=port,
            username=username,
            password=password
        )
        # 自动建库
        client.command(f"CREATE DATABASE IF NOT EXISTS {database}")
        
        # 自动建表 DDL
        stats_ddl = f"""
        CREATE TABLE IF NOT EXISTS {full_table} (
            code LowCardinality(String),
            name LowCardinality(String),
            time Date,
            open Float64,
            high Float64,
            low Float64,
            close Float64,
            volume Int64,
            turnover Float64,
            pe_ratio Float64,
            turnover_rate Float64,
            change_rate Float64,
            last_close Float64,
            lot_size UInt32,
            stock_id UInt64,
            update_time DateTime DEFAULT now()
        ) ENGINE = MergeTree()
        PARTITION BY toYYYYMM(time)
        ORDER BY (code, time)
        SETTINGS index_granularity = 8192;
        """
        client.command(stats_ddl)
        
        # 兼容旧表升级逻辑
        client.command(f"ALTER TABLE {full_table} ADD COLUMN IF NOT EXISTS lot_size UInt32")
        client.command(f"ALTER TABLE {full_table} ADD COLUMN IF NOT EXISTS stock_id UInt64")
        
        return client, full_table
    except Exception as e:
        logger.error(f"❌ 无法连接 ClickHouse 数据库: {e}")
        return None, full_table

def spill_kline_to_disk(df):
    """当 ClickHouse 写入失败时，将日 K 线数据固化至本地灾备 Parquet 文件"""
    try:
        ts = int(time.time() * 1000)
        file_name = f"failover_kline_{ts}.parquet"
        file_path = os.path.join(FAILOVER_DIR, file_name)
        
        # 将 time 转换为 pandas 字符串或标准格式以防止序列化问题
        df_spill = df.copy()
        df_spill['time'] = df_spill['time'].apply(lambda x: x.strftime('%Y-%m-%d') if hasattr(x, 'strftime') else str(x))
        df_spill['update_time'] = df_spill['update_time'].apply(lambda x: x.strftime('%Y-%m-%d %H:%M:%S') if hasattr(x, 'strftime') else str(x))
        df_spill.to_parquet(file_path)
        logger.warning(f"💾 灾备溢出：ClickHouse 连接异常，已将 {len(df)} 条 K 线数据保存至本地: {file_path}")
    except Exception as ex:
        logger.critical(f"🚨 致命错误：日 K 线灾备本地溢出写入失败！错误: {ex}", exc_info=True)

def recovery_failover_data(client, full_table):
    """启动时检测灾备数据并尝试补录到 ClickHouse"""
    if not client:
        return
    try:
        files = sorted([f for f in os.listdir(FAILOVER_DIR) if f.startswith("failover_kline_") and f.endswith(".parquet")])
        if not files:
            return
        logger.info(f"⏳ 发现 {len(files)} 个日 K 线历史灾备数据包，启动异步补录...")
        for fname in files:
            file_path = os.path.join(FAILOVER_DIR, fname)
            try:
                df = pd.read_parquet(file_path)
                if not df.empty:
                    df['time'] = pd.to_datetime(df['time']).dt.date
                    df['update_time'] = pd.to_datetime(df['update_time'])
                    df['volume'] = df['volume'].astype('int64')
                    
                    if 'lot_size' not in df.columns:
                        df['lot_size'] = 0
                    df['lot_size'] = df['lot_size'].astype('uint32')
                    
                    if 'stock_id' not in df.columns:
                        df['stock_id'] = 0
                    df['stock_id'] = df['stock_id'].astype('uint64')
                    
                    client.insert_df(full_table, df)
                    logger.info(f"⚡ 成功补录灾备数据包 {fname} ({len(df)} 条) 到 ClickHouse")
                os.remove(file_path)
            except Exception as block_ex:
                logger.error(f"❌ 补录数据包 {fname} 失败: {block_ex}. 将在下一次运行时重新尝试。")
                break
    except Exception as e:
        logger.error(f"⚠️ 补录灾备数据运行异常: {e}")

# =====================================================================
# 3. 核心拉取流程
# =====================================================================
def load_watchlist(market):
    """读取 Watchlist 配置文件"""
    path = os.path.join(PROJECT_ROOT, "configs", f"watchlist_{market.lower()}.json")
    if not os.path.exists(path):
        logger.warning(f"⚠️ 找不到配置文件: {path}，跳过该市场")
        return []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get("stocks", [])
    except Exception as e:
        logger.error(f"❌ 读取 Watchlist 文件 {path} 异常: {e}")
        return []

def fetch_basic_info_map(quote_ctx, code_list):
    """
    批量获取指定股票代码的基本信息并返回映射字典：
    { code: { 'lot_size': lot_size, 'stock_id': stock_id } }
    """
    # 交易所映射
    market_map = {
        'HK': Market.HK,
        'US': Market.US,
        'SH': Market.SH,
        'SZ': Market.SZ
    }
    
    basic_info = {}
    if not code_list:
        return basic_info
        
    # 按市场前缀分组以调用 get_stock_basicinfo
    grouped_codes = {}
    for code in code_list:
        parts = code.split('.')
        if len(parts) == 2:
            mkt_prefix = parts[0].upper()
            grouped_codes.setdefault(mkt_prefix, []).append(code)
            
    for mkt_prefix, codes in grouped_codes.items():
        market = market_map.get(mkt_prefix)
        if not market:
            logger.warning(f"⚠️ 未知的市场前缀: {mkt_prefix}，跳过获取基本信息")
            continue
            
        logger.info(f"📡 正在批量获取 {mkt_prefix} 市场 {len(codes)} 只股票的基本信息...")
        time.sleep(0.5)  # 避免限频
        
        ret, df = quote_ctx.get_stock_basicinfo(market, SecurityType.STOCK, codes)
        if ret == RET_OK and not df.empty:
            for _, row in df.iterrows():
                c = row['code']
                basic_info[c] = {
                    'lot_size': int(row['lot_size']) if 'lot_size' in row and not pd.isna(row['lot_size']) else 0,
                    'stock_id': int(row['stock_id']) if 'stock_id' in row and not pd.isna(row['stock_id']) else 0
                }
        else:
            logger.error(f"❌ 批量获取 {mkt_prefix} 市场股票基本信息失败: {df}")
            
    return basic_info

def main():
    parser = argparse.ArgumentParser(description="日 K 线增量拉取与首次回溯历史收集器")
    parser.add_argument("--market", default="ALL", choices=["US", "HK", "CN", "ALL"], help="目标收集市场 (默认: ALL)")
    args = parser.parse_args()
    
    settings = load_config()
    
    # 1. 初始化 ClickHouse
    client, full_table = connect_clickhouse(settings)
    if client:
        logger.info(f"✅ ClickHouse 引擎已就绪: {full_table}")
        # 尝试补录可能存在的本地灾备数据
        recovery_failover_data(client, full_table)
    else:
        logger.warning(f"⚠️ 无法建立 ClickHouse 连接，本次获取的所有 K 线数据将直接固化到本地 Parquet 灾备目录中。")
    
    # 2. 读取现有股票的最大时间戳
    max_dates = {}
    if client:
        try:
            res = client.query(f"SELECT code, max(time) as max_time FROM {full_table} GROUP BY code").result_rows
            max_dates = {row[0]: row[1] for row in res}
            logger.info(f"📊 已从数据库加载 {len(max_dates)} 只标的的最新 K 线日期记录")
        except Exception as query_ex:
            logger.error(f"❌ 读取已有股票最新时间戳失败: {query_ex}. 首次运行标的将默认向前回溯 1 年")
            
    # 3. 组合待处理股票列表
    markets_to_process = ["HK", "US", "CN"] if args.market.upper() == "ALL" else [args.market.upper()]
    stocks_to_process = []
    for m in markets_to_process:
        stocks = load_watchlist(m)
        stocks_to_process.extend(stocks)
        
    # 去重
    stocks_to_process = list(dict.fromkeys(stocks_to_process))
    
    if not stocks_to_process:
        logger.info("ℹ️ 待处理股票列表为空，程序结束。")
        return
        
    logger.info(f"🚀 准备处理标的总计: {len(stocks_to_process)} 只")
    
    # 4. 建立富途通道
    quote_ctx = None
    success_count = 0
    fail_count = 0
    inserted_rows = 0
    spilled_rows = 0
    
    try:
        quote_ctx = OpenQuoteContext(host=settings["futu_opend"]["host"], port=settings["futu_opend"]["port"])
        logger.info("📡 成功建立富途 OpenD 接口连接")
        
        # 批量获取股票基本信息
        basic_info_map = fetch_basic_info_map(quote_ctx, stocks_to_process)
        
        now = datetime.now()
        end_date_str = now.strftime('%Y-%m-%d')
        
        for idx, code in enumerate(stocks_to_process, 1):
            logger.info(f"[{idx}/{len(stocks_to_process)}] 正在处理标的: {code}")
            
            # 计算起止日期
            max_date = max_dates.get(code)
            if max_date is None:
                # 首次拉取，回溯 1 年
                start_date = now - timedelta(days=365)
                start_date_str = start_date.strftime('%Y-%m-%d')
                logger.info(f"   └─ 🔍 首次拉取: 该股票在 ClickHouse 无记录，回溯拉取 1 年 ({start_date_str} 到 {end_date_str})")
            else:
                # 增量拉取：若 max_date 是 datetime.date 类型，加 1 天
                if isinstance(max_date, str):
                    max_date_parsed = datetime.strptime(max_date, '%Y-%m-%d').date()
                else:
                    max_date_parsed = max_date
                
                # 增量起止时间为 max_date + 1 天
                start_date = max_date_parsed + timedelta(days=1)
                start_date_str = start_date.strftime('%Y-%m-%d')
                
                if start_date_str > end_date_str:
                    logger.info(f"   └─ ⏩ 跳过拉取: 该标的最新日期已是 {max_date_parsed}，当前日期为 {end_date_str}，数据已是最新")
                    success_count += 1
                    continue
                else:
                    logger.info(f"   └─ 📈 增量拉取: 最新记录为 {max_date_parsed}，拉取区间 ({start_date_str} 到 {end_date_str})")
            
            # 调用富途拉取
            # 频率控制：防止触发 API 限频
            time.sleep(0.5)
            
            ret, df, page_req_key = quote_ctx.request_history_kline(
                code,
                start=start_date_str,
                end=end_date_str,
                ktype=KLType.K_DAY,
                autype=AuType.QFQ,
                fields=[KL_FIELD.ALL]
            )
            
            if ret != RET_OK:
                logger.error(f"   └─ ❌ 富途拉取历史 K 线接口返回错误 (code: {code}): {df}")
                fail_count += 1
                continue
                
            if df is None or df.empty:
                logger.info(f"   └─ 📭 富途未返回数据 (可能为非交易日或没有新产生的K线数据)")
                success_count += 1
                continue
                
            # 5. 数据清洗与加工
            try:
                # 重命名/规范化字段以匹配表结构
                df_clean = pd.DataFrame()
                df_clean['code'] = df['code']
                df_clean['name'] = df['name']
                df_clean['time'] = pd.to_datetime(df['time_key']).dt.date
                df_clean['open'] = df['open'].astype(float)
                df_clean['high'] = df['high'].astype(float)
                df_clean['low'] = df['low'].astype(float)
                df_clean['close'] = df['close'].astype(float)
                df_clean['volume'] = df['volume'].astype('int64')
                df_clean['turnover'] = df['turnover'].astype(float)
                df_clean['pe_ratio'] = df['pe_ratio'].astype(float)
                df_clean['turnover_rate'] = df['turnover_rate'].astype(float)
                df_clean['change_rate'] = df['change_rate'].astype(float)
                df_clean['last_close'] = df['last_close'].astype(float)
                
                info = basic_info_map.get(code, {'lot_size': 0, 'stock_id': 0})
                df_clean['lot_size'] = int(info['lot_size'])
                df_clean['stock_id'] = int(info['stock_id'])
                
                df_clean['update_time'] = datetime.now()
                
                # 应用层防重去重：过滤掉 <= max_date 的数据
                if max_date is not None:
                    df_clean = df_clean[df_clean['time'] > max_date_parsed]
                    
                if df_clean.empty:
                    logger.info(f"   └─ ⏩ 去重后无新增数据，跳过")
                    success_count += 1
                    continue
                
                # 6. 入库或灾备
                if client:
                    try:
                        client.insert_df(full_table, df_clean)
                        logger.info(f"   └─ ✅ 成功导入 ClickHouse 共 {len(df_clean)} 条日 K 线记录")
                        inserted_rows += len(df_clean)
                    except Exception as insert_ex:
                        logger.error(f"   └─ ⚠️ 写入 ClickHouse 异常: {insert_ex}. 触发本地灾备。")
                        spill_kline_to_disk(df_clean)
                        spilled_rows += len(df_clean)
                else:
                    spill_kline_to_disk(df_clean)
                    spilled_rows += len(df_clean)
                    
                success_count += 1
                
            except Exception as clean_ex:
                logger.error(f"   └─ ❌ 数据清洗/转换异常 (code: {code}): {clean_ex}", exc_info=True)
                fail_count += 1
                
    except Exception as global_ex:
        logger.critical(f"🚨 运行过程中捕获到全局致命异常: {global_ex}", exc_info=True)
    finally:
        if quote_ctx:
            quote_ctx.close()
            logger.info("🔌 富途 OpenD 接口连接已断开")
            
        logger.info("=====================================================================")
        logger.info("🏁 日 K 线增量拉取任务执行结束！统计报告如下:")
        logger.info(f"   ├─ 成功处理标的: {success_count} 只")
        logger.info(f"   ├─ 失败处理标的: {fail_count} 只")
        logger.info(f"   ├─ 成功入库行数: {inserted_rows} 行")
        logger.info(f"   └─ 灾备落盘行数: {spilled_rows} 行")
        logger.info("=====================================================================")

if __name__ == "__main__":
    main()
