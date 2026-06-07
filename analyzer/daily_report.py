import os
import json
import glob
import gc
import pandas as pd
import logging
from datetime import datetime, timedelta

# =====================================================================
# 🛠️ 智能相对路径锚定（工业级避坑设计）
# =====================================================================
# 1. 无论在哪里拉起脚本，先获取当前文件(daily_report.py)的绝对物理路径
CURRENT_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# 2. 自动逆向推导出项目的根目录绝对物理地址 (即 analyzer/ 的上一级)
PROJECT_ROOT_DIR = os.path.dirname(CURRENT_SCRIPT_DIR)

# 3. 动态拼接并锁定唯一的全局设置 json 相对路径
SETTINGS_JSON_PATH = os.path.join(PROJECT_ROOT_DIR, "configs", "futu_settings.json")

# =====================================================================
# 配置日志系统 (提高日志完整性)
# =====================================================================
LOG_DIR = os.path.join(PROJECT_ROOT_DIR, 'data', 'logs')
os.makedirs(LOG_DIR, exist_ok=True)
log_file_path = os.path.join(LOG_DIR, 'daily_report.log')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.FileHandler(log_file_path),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def load_project_settings(config_path):
    """安全解析全局配置文件"""
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"🚨 核心配置文件未找到: {config_path}")
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def run_micro_structure_audit(parquet_path, k_ticks=15):
    """
    微观结构算法应用：通过物理 Parquet 数据集计算永久价格冲击
    """
    try:
        # 🔥 核心修复：限制只读取需要的列，极大降低内存载入压力
        use_cols = ['price', 'volume', 'ticker_direction', 'bid_price', 'ask_price', 'turnover']
        
        # 兼容性处理：如果不确定全表有哪些列，可先读schema
        # 这里为了稳妥，使用try-except处理可能不存在的列(例如老的测试文件可能没有bid_price)
        df = pd.read_parquet(parquet_path, columns=use_cols)
    except Exception as e:
        # 退回全量读取尝试(兼容处理)
        try:
            df = pd.read_parquet(parquet_path)
            # 过滤只保留需要的列
            df = df[[col for col in use_cols if col in df.columns]]
        except Exception as e2:
            return {"error": f"读取失败: {e2}"}
        
    if df.empty or len(df) < k_ticks * 2:
        return {"error": "数据量过少"}
    
    try:
        # 计算盘口中点价
        if 'bid_price' in df.columns and 'ask_price' in df.columns:
            df['mid_price'] = (df['bid_price'] + df['ask_price']) / 2
            df['mid_price'] = df['mid_price'].fillna(df['price'])
        else:
            df['mid_price'] = df['price']

        # 算法特征工程：shift 提取未来价格窗口
        df['future_mid'] = df['mid_price'].shift(-k_ticks)
        
        # 兼容处理多市场买卖方向标识 (支持富途 BUY/SELL 字符串及数字映射)
        if df['ticker_direction'].dtype == object:
            df['sign'] = df['ticker_direction'].map({'BUY': 1, 'SELL': -1, 'NEUTRAL': 0})
        else:
            df['sign'] = df['ticker_direction'].map({1: 1, 2: -1, 3: 0})
        df['sign'] = df['sign'].fillna(0)

        # 测算大单
        df['perm_impact'] = df['sign'] * (df['future_mid'] - df['mid_price'])
        large_thresh = df['volume'].quantile(0.90)
        if large_thresh == 0: large_thresh = 1
            
        df_large = df[df['volume'] >= large_thresh].copy()
        
        # 🔥 立即释放原表大部分内容以节约内存
        del df
        gc.collect()

        if 'turnover' not in df_large.columns:
            df_large['turnover'] = df_large['price'] * df_large['volume']
            
        large_buys = df_large[df_large['sign'] == 1]
        large_sells = df_large[df_large['sign'] == -1]
        
        net_large_money = large_buys['turnover'].sum() - large_sells['turnover'].sum()
        buy_impact_score = large_buys['perm_impact'].mean() if not large_buys.empty else 0.0
        
        return {
            "net_money": net_large_money,
            "buy_impact": buy_impact_score,
            "threshold": large_thresh
        }
    finally:
        # 🔥 修复：显式删除所有中间 DataFrame，防止内存泄漏
        try:
            del df
        except (NameError, UnboundLocalError):
            pass
        try:
            del df_large
            del large_buys
            del large_sells
        except (NameError, UnboundLocalError):
            pass  # 如果出错，这些变量可能未创建
        gc.collect()


def find_latest_trading_data(archive_base_dir):
    """自动基于日期由近及远检索最近一个有 parquet 文件的交易日文件夹"""
    search_date = datetime.today()
    
    for _ in range(10): # 最多向前溯源 10 天 (防长假期导致的报告断流)
        date_str = search_date.strftime('%Y-%m-%d')
        year_month = search_date.strftime('%Y/%m')
        
        # 匹配大数据库下任意市场的多层目录结构
        search_pattern = os.path.join(archive_base_dir, year_month, "*", f"*_{date_str}.parquet")
        target_files = glob.glob(search_pattern)
        
        if target_files:
            return date_str, target_files
            
        search_date -= timedelta(days=1)
    return None, []


def execute_analysis_workflow():
    logger.info("🔮 跨市场微观结构分析模块拉起...")
    
    # 1. 动态载入全系统唯一的相对路径配置
    settings = load_project_settings(SETTINGS_JSON_PATH)
    
    # 2. 将配置中的相对路径，通过动态根目录投影为真实的物理绝对地址
    archive_dir = os.path.join(PROJECT_ROOT_DIR, settings["storage"]["base_archive_dir"])
    report_dir = os.path.join(PROJECT_ROOT_DIR, settings["storage"]["base_report_dir"])
    
    # 3. 自动嗅探最新有数据的交易日
    target_date, target_files = find_latest_trading_data(archive_dir)
    
    if not target_date:
        logger.warning("😴 数据中心未扫描到任何近期的 Parquet 数据，分析终止。")
        return
        
    logger.info(f"📅 锁定测算分析的目标交易日: 【{target_date}】")
    logger.info(f"📂 正在审计来自数据湖中的 {len(target_files)} 只跨市场标的...")

    # 4. 构建 Markdown 战报文档
    report_lines = [
        f"# 🎯 跨市场微观结构筹码审计日报 ({target_date})",
        f"> 算法重构运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "> *监控核心：不看图形虚实，不看红绿假相。只抓主力在微观盘口的真钱沉淀留痕。*\n",
        "| 资产/个股 | 大单净流入 (真钱) | 买单冲击度(锁仓力) | 动态主力门槛 | 💡 智能诊断预警 |",
        "| :--- | :--- | :--- | :--- | :--- |"
    ]

    success_count = 0
    gc_interval = 0  # 🔥 添加垃圾回收计数器
    
    for file_path in target_files:
        # 从文件名解析代码，并逆向获取其所属的子市场分类 (US / HK / CN)
        filename = os.path.basename(file_path)
        code = filename.split('_')[0]
        
        # 执行微观算法特征提取
        res = run_micro_structure_audit(file_path, k_ticks=15)
        if "error" in res:
            logger.debug(f"跳过 {code}: {res['error']}")
            continue
            
        net_m = res["net_money"]
        b_imp = res["buy_impact"]
        thresh = res["threshold"]
        
        # 智能阿尔法审计诊断分级
        if net_m > 0 and b_imp > 0:
            diag = "🟢 **机构硬核吸筹突破** (买入成色极好)"
        elif net_m > 0 and b_imp <= 0:
            diag = "🟡 **虚胖对倒诱多** (筹码松散，警惕假突破)"
        elif net_m < 0 and b_imp > 0:
            diag = "🔵 **被动主力截流** (破位阴跌时有大资金冰山单硬抗)"
        else:
            diag = "🔴 **知情机构坚决撤离** (极度危险，禁止接飞刀)"

        # 智能金额人类可读格式规范化 (M=百万, K=千)
        if abs(net_m) >= 1_000_000:
            money_str = f"${net_m/1_000_000:.2f}M"
        elif abs(net_m) >= 1_000:
            money_str = f"${net_m/1_000:.1f}K"
        else:
            money_str = f"${net_m:.2f}"

        line = f"| **{code}** | {money_str} | {b_imp:+.4f} | >{int(thresh)} 股 | {diag} |"
        report_lines.append(line)
        success_count += 1
        
        # 🔥 修复：每处理100个文件触发一次垃圾回收，防止内存积累
        gc_interval += 1
        if gc_interval % 100 == 0:
            gc.collect()

    # 5. 自动创建报告存储目录，并直接落盘
    os.makedirs(report_dir, exist_ok=True)
    report_file_path = os.path.join(report_dir, f"Audit_Report_{target_date}.md")
    
    with open(report_file_path, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))

    logger.info("="*50)
    logger.info(f"🎉 跨市场分析全部圆满完成！成功固化 {success_count} 家资产成色。")
    logger.info(f"📄 审计日报已存入网盘同步区: {report_file_path}")
    logger.info("="*50)


if __name__ == "__main__":
    execute_analysis_workflow()