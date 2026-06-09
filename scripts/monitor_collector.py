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
    """查询单个数据库 ticks 表的实时指标"""
    try:
        # 使用 system.tables 确保表存在，防范表未创建时报错
        exists_q = f"SELECT count() FROM system.tables WHERE database = '{db_name}' AND name = 'ticks'"
        exists = client.query(exists_q).result_rows[0][0] == 1
        if not exists:
            return {
                "exists": False,
                "rate_1m": 0.0,
                "rate_5m": 0.0,
                "active_30s": False,
                "total_rows": 0,
                "stocks": []
            }
            
        table_path = f"{db_name}.ticks"
        
        # 1. 获取数据库总数据条数
        q_total = f"SELECT count() FROM {table_path}"
        total_rows = client.query(q_total).result_rows[0][0]
        
        # 2. 查询最近 1 分钟和 5 分钟的写入数据量
        q_rates = f"""
        SELECT 
            countIf(time >= now() - INTERVAL 1 MINUTE) as cnt_1m,
            countIf(time >= now() - INTERVAL 5 MINUTE) as cnt_5m
        FROM {table_path}
        """
        rates_res = client.query(q_rates).result_rows[0]
        rate_1m = round(rates_res[0] / 60.0, 2)
        rate_5m = round(rates_res[1] / 300.0, 2)
        
        # 3. 检查最近 30 秒总写入数，用于判断是否断流
        q_30s = f"SELECT count() FROM {table_path} WHERE time >= now() - INTERVAL 30 SECOND"
        cnt_30s = client.query(q_30s).result_rows[0][0]
        
        # 4. 查询今日各标的的最新 Tick 时间和总条数
        q_stocks = f"""
        SELECT 
            '{db_name}' as db,
            code,
            max(time) as last_time,
            count() as total_count
        FROM {table_path}
        WHERE time >= today()
        GROUP BY code
        ORDER BY last_time DESC
        LIMIT 15
        """
        stocks_res = client.query(q_stocks).result_rows
        
        return {
            "exists": True,
            "rate_1m": rate_1m,
            "rate_5m": rate_5m,
            "active_30s": cnt_30s > 0,
            "total_rows": total_rows,
            "stocks": stocks_res
        }
    except Exception as e:
        logger_err = f"获取数据库 {db_name} 指标异常: {e}"
        # 回退为未连接/不存在表
        return {
            "exists": False,
            "rate_1m": 0.0,
            "rate_5m": 0.0,
            "active_30s": False,
            "total_rows": 0,
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
        
        # 合并两个库的活跃股票，并按 last_time 降序排序
        all_stocks = []
        if stock_metrics["exists"]:
            all_stocks.extend(stock_metrics["stocks"])
        if preview_metrics["exists"]:
            all_stocks.extend(preview_metrics["stocks"])
            
        def get_time_key(row):
            t = row[2]
            if t is None:
                return datetime.min.replace(tzinfo=pytz.utc)
            if t.tzinfo is None:
                return pytz.timezone('Asia/Shanghai').localize(t)
            return t
            
        all_stocks.sort(key=get_time_key, reverse=True)
        all_stocks = all_stocks[:20]  # 取前20条
        
        # 判断两个数据库连接状态
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
                "stock": {"exists": False, "rate_1m": 0.0, "rate_5m": 0.0, "active_30s": False, "total_rows": 0},
                "stock_preview": {"exists": False, "rate_1m": 0.0, "rate_5m": 0.0, "active_30s": False, "total_rows": 0}
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
    
    # 状态指示灯与主面板色调 (以配置文件指定的主数据库为准)
    primary_db = ch_config.get("database", "stock_preview")
    primary_metrics = metrics["dbs"].get(primary_db, {"exists": False, "active_30s": False})
    
    if not metrics["connected"]:
        status_text = f"🔴 无法连接 ClickHouse 数据库 ({ch_config['host']})"
        border_color = "red"
    elif local_status and not local_status.get("db_connected", False):
        status_text = "🟡 数据库断开 (本地正在执行 Parquet 灾备溢出)"
        border_color = "yellow"
    elif primary_metrics.get("exists") and not primary_metrics.get("active_30s"):
        status_text = f"🟡 数据流疑似中断 (主库 {primary_db} 最近30秒无新Tick)"
        border_color = "yellow"
    else:
        status_text = f"🟢 主库 {primary_db} 数据流写入中 (活跃)"
        border_color = "green"
        
    # 格式化双库指标对比
    def get_db_status_line(name, m):
        if not m.get("exists"):
            return f"  └─ {name:15} | ❌ [red]未创建或不可达[/red]"
        active = "🟢 [green]活跃[/green]" if m.get("active_30s") else "⚪ [yellow]空闲/断流[/yellow]"
        return (
            f"  └─ {name:15} | 状态: {active} | "
            f"总行数: [bold green]{m['total_rows']:11,}[/bold green] 行 | "
            f"速写 TPS (1m/5m): [bold yellow]{m['rate_1m']:5.2f}[/bold yellow] / [bold yellow]{m['rate_5m']:5.2f}[/bold yellow]"
        )
        
    db_lines = []
    for db_name in ["stock", "stock_preview"]:
        db_lines.append(get_db_status_line(db_name, metrics["dbs"][db_name]))
    dbs_compare_text = "\n".join(db_lines)
        
    # 构建顶部指标面板
    local_heartbeat = local_status.get("last_heartbeat", "未知") if local_status else "未启动"
    local_queue = local_status.get("queue_size", 0) if local_status else 0
    local_buffer = local_status.get("buffer_size", 0) if local_status else 0
    failover_files = local_status.get("failover_files_count", 0) if local_status else 0
    engine_type = local_status.get("engine_type", "未知") if local_status else "未知"
    
    summary_text = (
        f"[bold]远程数据库状态[/bold]: {status_text}\n"
        f"ClickHouse 目标地址: [cyan]{ch_config['host']}:{ch_config['port']}[/cyan] | 当前配置主库: [cyan]{primary_db}[/cyan]\n"
        f"[bold]多数据库监控对比[/bold]:\n"
        f"{dbs_compare_text}\n"
        f"--------------------------------------------------------------------------------\n"
        f"[bold]本地收集进程心跳[/bold]: [cyan]{local_heartbeat}[/cyan] | 存储引擎: [cyan]{engine_type}[/cyan]\n"
        f"线程安全缓冲队列: [bold yellow]{local_queue}[/bold yellow] / 100,000 | 内存 Buffer 大小: [bold yellow]{local_buffer}[/bold yellow] / {settings.get('storage', {}).get('flush_threshold', 1000)}\n"
        f"本地网络故障灾备文件积压数: [bold red]{failover_files}[/bold red]"
    )
    
    if metrics["error"]:
        summary_text += f"\n\n[bold red]数据库异常日志[/bold]: {metrics['error']}"
        
    # 构建下方标的明细 Table
    table = Table(title="📊 标的数据明细 (双库今日活跃前20名)", show_header=True, header_style="bold magenta")
    table.add_column("所属数据库", style="magenta", width=15)
    table.add_column("股票代码", style="cyan", width=12)
    table.add_column("最新 Tick 时间 (展示时区)", style="yellow", width=25)
    table.add_column("最后时差 (秒)", justify="right", width=15)
    table.add_column("今日累计笔数", justify="right", style="green", width=15)
    
    now_tz = datetime.now(pytz.timezone('Asia/Shanghai'))
    for row in metrics["stocks"]:
        db, code, last_time, total_count = row
        if last_time:
            # 统一转为上海时区计算
            if last_time.tzinfo is None:
                last_time = pytz.timezone('Asia/Shanghai').localize(last_time)
            diff_secs = int((now_tz - last_time).total_seconds())
            if diff_secs < 0:
                diff_secs = 0
            diff_str = f"{diff_secs} 秒"
            if diff_secs > 10:
                diff_str = f"[bold red]{diff_secs} 秒 (滞后)[/bold red]"
            time_str = last_time.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        else:
            diff_str = "N/A"
            time_str = "N/A"
            
        table.add_row(db, code, time_str, diff_str, f"{total_count:,}")
        
    # 整合面板
    layout = Layout()
    layout.split_column(
        Layout(Panel(summary_text, title="📡 Trader Ticks 收集器双库监控", border_style=border_color), size=12),
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
