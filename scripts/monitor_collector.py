import os
import sys
import time
import json
from datetime import datetime
import pytz
import clickhouse_connect
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich.live import Live
from rich.text import Text

# 解析项目根路径，用以寻找配置文件
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

console = Console()

def load_futu_settings():
    """加载配置文件中的 ClickHouse 信息"""
    local_path = os.path.join(PROJECT_ROOT, "configs", "futu_settings.local.json")
    default_path = os.path.join(PROJECT_ROOT, "configs", "futu_settings.json")
    
    path = local_path if os.path.exists(local_path) else default_path
    if not os.path.exists(path):
        return None
        
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None

def load_local_status():
    """读取本地收集进程的心跳与状态"""
    status_path = os.path.join(PROJECT_ROOT, "data", "collector_status.json")
    if not os.path.exists(status_path):
        return None
    try:
        with open(status_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None

def fetch_single_db_metrics(client, db_name):
    """查询单个数据库 ticks 与 order_books 表的实时指标"""
    try:
        # 1. 检查表是否存在
        exists_ticks_q = f"SELECT count() FROM system.tables WHERE database = '{db_name}' AND name = 'ticks'"
        exists_ticks = client.query(exists_ticks_q).result_rows[0][0] == 1
        
        exists_ob_q = f"SELECT count() FROM system.tables WHERE database = '{db_name}' AND name = 'order_books'"
        exists_ob = client.query(exists_ob_q).result_rows[0][0] == 1
        
        if not exists_ticks:
            return {
                "exists": False,
                "ticks_exists": False,
                "ob_exists": False,
                "ticks_total": 0,
                "ob_total": 0,
                "ticks_rate_1m": 0.0,
                "ticks_rate_5m": 0.0,
                "ob_rate_1m": 0.0,
                "ob_rate_5m": 0.0,
                "ticks_active_30s": False,
                "ob_active_30s": False,
                "stocks": []
            }
            
        table_path = f"{db_name}.ticks"
        
        # 2. 获取 ticks 总数据条数与写入速率
        ticks_total = client.query(f"SELECT count() FROM {table_path}").result_rows[0][0]
        rates_res = client.query(f"""
        SELECT 
            countIf(time >= now() - INTERVAL 1 MINUTE) as cnt_1m,
            countIf(time >= now() - INTERVAL 5 MINUTE) as cnt_5m
        FROM {table_path}
        """).result_rows[0]
        ticks_rate_1m = round(rates_res[0] / 60.0, 2)
        ticks_rate_5m = round(rates_res[1] / 300.0, 2)
        
        cnt_30s = client.query(f"SELECT count() FROM {table_path} WHERE time >= now() - INTERVAL 30 SECOND").result_rows[0][0]
        ticks_active_30s = cnt_30s > 0
        
        # 3. 获取 order_books 指标（如果存在）
        ob_total = 0
        ob_rate_1m = 0.0
        ob_rate_5m = 0.0
        ob_active_30s = False
        
        if exists_ob:
            ob_table_path = f"{db_name}.order_books"
            ob_total = client.query(f"SELECT count() FROM {ob_table_path}").result_rows[0][0]
            ob_rates_res = client.query(f"""
            SELECT 
                countIf(time >= now() - INTERVAL 1 MINUTE) as cnt_1m,
                countIf(time >= now() - INTERVAL 5 MINUTE) as cnt_5m
            FROM {ob_table_path}
            """).result_rows[0]
            ob_rate_1m = round(ob_rates_res[0] / 60.0, 2)
            ob_rate_5m = round(ob_rates_res[1] / 300.0, 2)
            
            ob_cnt_30s = client.query(f"SELECT count() FROM {ob_table_path} WHERE time >= now() - INTERVAL 30 SECOND").result_rows[0][0]
            ob_active_30s = ob_cnt_30s > 0
            
        # 4. 查询今日各标的的最新 Tick 与 OrderBook 时间、今日总条数
        if exists_ob:
            q_stocks = f"""
            SELECT 
                '{db_name}' as db,
                coalesce(t.code, ob.code) as code,
                t.last_tick_time as last_tick_time,
                t.tick_count as tick_count,
                ob.last_ob_time as last_ob_time,
                ob.ob_count as ob_count
            FROM (
                SELECT 
                    code, 
                    max(time) as last_tick_time, 
                    count() as tick_count 
                FROM {db_name}.ticks 
                WHERE time >= today() 
                GROUP BY code
            ) t
            FULL OUTER JOIN (
                SELECT 
                    code, 
                    max(time) as last_ob_time, 
                    count() as ob_count 
                FROM {db_name}.order_books 
                WHERE time >= today() 
                GROUP BY code
            ) ob
            ON t.code = ob.code
            ORDER BY coalesce(last_tick_time, last_ob_time) DESC
            LIMIT 15
            """
        else:
            q_stocks = f"""
            SELECT 
                '{db_name}' as db,
                code,
                max(time) as last_tick_time,
                count() as tick_count,
                CAST(NULL, 'Nullable(DateTime64(3, \'Asia/Shanghai\'))') as last_ob_time,
                toUInt64(0) as ob_count
            FROM {db_name}.ticks
            WHERE time >= today()
            GROUP BY code
            ORDER BY last_tick_time DESC
            LIMIT 15
            """
        stocks_res = client.query(q_stocks).result_rows
        
        return {
            "exists": True,
            "ticks_exists": True,
            "ob_exists": exists_ob,
            "ticks_total": ticks_total,
            "ob_total": ob_total,
            "ticks_rate_1m": ticks_rate_1m,
            "ticks_rate_5m": ticks_rate_5m,
            "ob_rate_1m": ob_rate_1m,
            "ob_rate_5m": ob_rate_5m,
            "ticks_active_30s": ticks_active_30s,
            "ob_active_30s": ob_active_30s,
            "stocks": stocks_res
        }
    except Exception as e:
        logger_err = f"获取数据库 {db_name} 指标异常: {e}"
        return {
            "exists": False,
            "ticks_exists": False,
            "ob_exists": False,
            "ticks_total": 0,
            "ob_total": 0,
            "ticks_rate_1m": 0.0,
            "ticks_rate_5m": 0.0,
            "ob_rate_1m": 0.0,
            "ob_rate_5m": 0.0,
            "ticks_active_30s": False,
            "ob_active_30s": False,
            "stocks": [],
            "error": logger_err
        }

def fetch_db_metrics(ch_config):
    """从 ClickHouse 远程查询 stock 与 stock_preview 的实时指标"""
    client = None
    try:
        client = clickhouse_connect.get_client(
            host=ch_config["host"],
            port=int(ch_config["port"]),
            username=ch_config["username"],
            password=ch_config["password"]
        )
        
        stock_metrics = fetch_single_db_metrics(client, "stock")
        preview_metrics = fetch_single_db_metrics(client, "stock_preview")
        
        # 合并两个库的活跃股票，并按时间降序排序
        all_stocks = []
        if stock_metrics["exists"]:
            all_stocks.extend(stock_metrics["stocks"])
        if preview_metrics["exists"]:
            all_stocks.extend(preview_metrics["stocks"])
            
        def get_time_key(row):
            # row: [db, code, last_tick_time, tick_count, last_ob_time, ob_count]
            t_tick = row[2]
            t_ob = row[4]
            t = t_tick if t_tick is not None else t_ob
            if t is None:
                return datetime.min.replace(tzinfo=pytz.utc)
            if t.tzinfo is None:
                return pytz.timezone('Asia/Shanghai').localize(t)
            return t
            
        all_stocks.sort(key=get_time_key, reverse=True)
        all_stocks = all_stocks[:20]  # 取前20条
        
        connected = True
        
        return {
            "connected": connected,
            "dbs": {
                "stock": stock_metrics,
                "stock_preview": preview_metrics
            },
            "stocks": all_stocks,
            "error": stock_metrics.get("error") or preview_metrics.get("error")
        }
    except Exception as e:
        return {
            "connected": False,
            "dbs": {
                "stock": {"exists": False, "ticks_exists": False, "ob_exists": False, "ticks_total": 0, "ob_total": 0, "ticks_rate_1m": 0.0, "ticks_rate_5m": 0.0, "ob_rate_1m": 0.0, "ob_rate_5m": 0.0, "ticks_active_30s": False, "ob_active_30s": False},
                "stock_preview": {"exists": False, "ticks_exists": False, "ob_exists": False, "ticks_total": 0, "ob_total": 0, "ticks_rate_1m": 0.0, "ticks_rate_5m": 0.0, "ob_rate_1m": 0.0, "ob_rate_5m": 0.0, "ticks_active_30s": False, "ob_active_30s": False}
            },
            "stocks": [],
            "error": str(e)
        }
    finally:
        if client:
            client.close()

def generate_dashboard():
    """渲染终端监控面板"""
    settings = load_futu_settings()
    local_status = load_local_status()
    
    if not settings or "clickhouse" not in settings:
        return Panel(
            Text("❌ 找不到有效的配置文件 configs/futu_settings.json 或缺失 clickhouse 配置项", style="bold red"),
            title="Trader Ticks 远程监控系统",
            border_style="red"
        )
        
    ch_config = settings["clickhouse"]
    metrics = fetch_db_metrics(ch_config)
    
    primary_db = ch_config.get("database", "stock_preview")
    primary_metrics = metrics["dbs"].get(primary_db, {"exists": False, "ticks_active_30s": False})
    
    if not metrics["connected"]:
        status_text = f"🔴 无法连接 ClickHouse 数据库 ({ch_config['host']})"
        border_color = "red"
    elif local_status and not local_status.get("db_connected", False):
        status_text = "🟡 数据库断开 (本地正在执行 Parquet 灾备溢出)"
        border_color = "yellow"
    elif primary_metrics.get("exists") and not primary_metrics.get("ticks_active_30s"):
        status_text = f"🟡 数据流疑似中断 (主库 {primary_db} 最近30秒无新Tick)"
        border_color = "yellow"
    else:
        status_text = f"🟢 主库 {primary_db} 数据流写入中 (活跃)"
        border_color = "green"
        
    # 格式化双库指标对比
    def get_db_status_line(name, m):
        if not m.get("exists"):
            return f"  └─ {name:15} | ❌ [red]未创建或不可达[/red]"
        ticks_active = "🟢 [green]活跃[/green]" if m.get("ticks_active_30s") else "⚪ [yellow]空闲/断流[/yellow]"
        ob_active = "🟢 [green]活跃[/green]" if m.get("ob_active_30s") else "⚪ [yellow]空闲/断流[/yellow]"
        
        if m.get("ob_exists"):
            ob_status_str = f"OrderBook: {ob_active} | 总行: [bold green]{m['ob_total']:11,}[/bold green] 行 | TPS: [bold yellow]{m['ob_rate_1m']:5.2f}[/bold yellow] / [bold yellow]{m['ob_rate_5m']:5.2f}[/bold yellow]"
        else:
            ob_status_str = "OrderBook: [red]未订阅/无盘口表[/red]"
            
        return (
            f"  └─ {name:15} | Ticks: {ticks_active} | 总行: [bold green]{m['ticks_total']:11,}[/bold green] 行 | TPS: [bold yellow]{m['ticks_rate_1m']:5.2f}[/bold yellow] / [bold yellow]{m['ticks_rate_5m']:5.2f}[/bold yellow]\n"
            f"                  | {ob_status_str}"
        )
        
    db_lines = []
    for db_name in ["stock", "stock_preview"]:
        db_lines.append(get_db_status_line(db_name, metrics["dbs"][db_name]))
    dbs_compare_text = "\n".join(db_lines)
        
    # 构建顶部指标面板
    local_heartbeat = local_status.get("last_heartbeat", "未知") if local_status else "未启动"
    local_queue = local_status.get("queue_size", 0) if local_status else 0
    local_buffer = local_status.get("buffer_size", 0) if local_status else 0
    local_ob_buffer = local_status.get("ob_buffer_size", 0) if local_status else 0
    failover_files = local_status.get("failover_files_count", 0) if local_status else 0
    engine_type = local_status.get("engine_type", "未知") if local_status else "未知"
    
    summary_text = (
        f"[bold]远程数据库状态[/bold]: {status_text}\n"
        f"ClickHouse 目标地址: [cyan]{ch_config['host']}:{ch_config['port']}[/cyan] | 当前配置主库: [cyan]{primary_db}[/cyan]\n"
        f"[bold]多数据库监控对比[/bold]:\n"
        f"{dbs_compare_text}\n"
        f"--------------------------------------------------------------------------------\n"
        f"[bold]本地收集进程心跳[/bold]: [cyan]{local_heartbeat}[/cyan] | 存储引擎: [cyan]{engine_type}[/cyan]\n"
        f"安全缓冲队列: [bold yellow]{local_queue}[/bold yellow] / 100,000 | 缓冲 (Ticks/OB): [bold yellow]{local_buffer}[/bold yellow] / [bold yellow]{local_ob_buffer}[/bold yellow] (阈值: {settings.get('storage', {}).get('flush_threshold', 1000)})\n"
        f"本地灾备积压文件数: [bold red]{failover_files}[/bold red]"
    )
    
    if metrics["error"]:
        summary_text += f"\n\n[bold red]数据库异常日志[/bold]: {metrics['error']}"
        
    # 构建下方标的明细 Table
    table = Table(title="📊 标的数据明细 (双库今日活跃前20名)", show_header=True, header_style="bold magenta")
    table.add_column("所属数据库", style="magenta", width=12)
    table.add_column("股票代码", style="cyan", width=10)
    table.add_column("最新 Tick 时间", style="yellow", width=13)
    table.add_column("Tick 时差", justify="right", width=9)
    table.add_column("累计 Tick 数", justify="right", style="green", width=11)
    table.add_column("最新 OrderBook 时间", style="yellow", width=17)
    table.add_column("OB 时差", justify="right", width=9)
    table.add_column("累计 OB 数", justify="right", style="green", width=11)
    
    now_tz = datetime.now(pytz.timezone('Asia/Shanghai'))
    for row in metrics["stocks"]:
        # row: [db, code, last_tick_time, tick_count, last_ob_time, ob_count]
        db, code, last_tick_time, tick_count, last_ob_time, ob_count = row
        
        # 格式化 Tick 时间与时差
        if last_tick_time:
            if last_tick_time.tzinfo is None:
                last_tick_time = pytz.timezone('Asia/Shanghai').localize(last_tick_time)
            diff_tick_secs = int((now_tz - last_tick_time).total_seconds())
            if diff_tick_secs < 0:
                diff_tick_secs = 0
            tick_diff_str = f"{diff_tick_secs}s"
            if diff_tick_secs > 10:
                tick_diff_str = f"[bold red]{diff_tick_secs}s[/bold red]"
            tick_time_str = last_tick_time.strftime('%H:%M:%S')
        else:
            tick_diff_str = "N/A"
            tick_time_str = "N/A"
            
        # 格式化 OrderBook 时间与时差
        if last_ob_time:
            if last_ob_time.tzinfo is None:
                last_ob_time = pytz.timezone('Asia/Shanghai').localize(last_ob_time)
            diff_ob_secs = int((now_tz - last_ob_time).total_seconds())
            if diff_ob_secs < 0:
                diff_ob_secs = 0
            ob_diff_str = f"{diff_ob_secs}s"
            if diff_ob_secs > 10:
                ob_diff_str = f"[bold red]{diff_ob_secs}s[/bold red]"
            ob_time_str = last_ob_time.strftime('%H:%M:%S')
        else:
            ob_diff_str = "N/A"
            ob_time_str = "N/A"
            
        table.add_row(
            db, 
            code, 
            tick_time_str, 
            tick_diff_str, 
            f"{tick_count:,}" if tick_count else "0", 
            ob_time_str, 
            ob_diff_str, 
            f"{ob_count:,}" if ob_count else "0"
        )
        
    layout = Layout()
    layout.split_column(
        Layout(Panel(summary_text, title="📡 Trader Ticks 收集器双库监控", border_style=border_color), size=14),
        Layout(table)
    )
    return layout

def main():
    if os.environ.get("ONCE") == "1":
        console.print(generate_dashboard())
        return
        
    console.clear()
    console.print("[bold green]🚀 启动 Trader Ticks 远程/本地流状态监控...[/bold green]")
    time.sleep(1)
    
    with Live(generate_dashboard(), refresh_per_second=1, screen=True) as live:
        try:
            while True:
                live.update(generate_dashboard())
                time.sleep(2)
        except KeyboardInterrupt:
            console.print("\n[bold green]👋 已退出状态监控。[/bold green]")

if __name__ == "__main__":
    main()
