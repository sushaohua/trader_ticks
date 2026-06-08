import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import os
import sys

# Add root directory to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analyzer.config_manager import AnalyzerConfigManager
from analyzer.models.vpin import VPINModel
from analyzer.models.iceberg import IcebergModel
from analyzer.models.flow_speed import FlowSpeedModel

# Set page config
st.set_page_config(page_title="Trader Ticks 交易分析系统", layout="wide", initial_sidebar_state="expanded")

st.title("📈 Trader Ticks 交易分析系统")

# --- Initialize Managers ---
@st.cache_resource
def get_config_manager():
    return AnalyzerConfigManager()

config_manager = get_config_manager()

# --- Sidebar: Data Loading ---
st.sidebar.header("📁 数据加载")

# Function to scan archive directory
def get_available_data(base_dir="archive"):
    if not os.path.exists(base_dir):
        return {}
    
    # Structure: archive/YYYY/MM/MARKET/code_date.parquet
    data_map = {}
    for year in os.listdir(base_dir):
        year_path = os.path.join(base_dir, year)
        if not os.path.isdir(year_path): continue
        for month in os.listdir(year_path):
            month_path = os.path.join(year_path, month)
            if not os.path.isdir(month_path): continue
            for market in os.listdir(month_path):
                market_path = os.path.join(month_path, market)
                if not os.path.isdir(market_path): continue
                for file in os.listdir(market_path):
                    if file.endswith(".parquet"):
                        code_date = file.replace(".parquet", "")
                        # Expected format: code_YYYY-MM-DD
                        parts = code_date.split('_')
                        if len(parts) >= 2:
                            code = parts[0]
                            date = parts[-1]
                            path = os.path.join(market_path, file)
                            
                            key = f"{market} - {date}"
                            if key not in data_map:
                                data_map[key] = []
                            data_map[key].append({"code": code, "path": path})
    return data_map

available_data = get_available_data("archive")

if not available_data:
    st.sidebar.warning("未在 'archive/' 发现数据。使用模拟数据进行演示。")
    selected_market_date = "模拟数据"
    selected_stock = "MOCK_AAPL"
    file_path = None
else:
    selected_market_date = st.sidebar.selectbox("市场 - 日期", list(available_data.keys()))
    stocks = [s["code"] for s in available_data[selected_market_date]]
    selected_stock = st.sidebar.selectbox("股票代码", stocks)
    file_path = next(s["path"] for s in available_data[selected_market_date] if s["code"] == selected_stock)

# --- Sidebar: Model Selection & Params ---
st.sidebar.header("⚙️ 模型配置")
analysis_mode = st.sidebar.radio("分析模型", ["VPIN (订单流毒性)", "冰山订单 (Iceberg)", "订单流速 (Flow Speed)"])

stock_config = config_manager.get_stock_config(selected_stock)

if analysis_mode == "VPIN (订单流毒性)":
    st.sidebar.subheader("VPIN 参数")
    volume_bucket_size = st.sidebar.number_input("卷量桶大小 (Volume Bucket)", min_value=100, value=stock_config['vpin']['volume_bucket_size'], step=100)
    window_size = st.sidebar.slider("滚动窗口 (Bucket数量)", min_value=10, max_value=200, value=stock_config['vpin']['window_size'])
    
    if st.sidebar.button("保存配置"):
        config_manager.update_stock_config(selected_stock, "vpin", "volume_bucket_size", volume_bucket_size)
        config_manager.update_stock_config(selected_stock, "vpin", "window_size", window_size)
        st.sidebar.success("已保存！")

elif analysis_mode == "冰山订单 (Iceberg)":
    st.sidebar.subheader("冰山订单参数")
    cluster_threshold = st.sidebar.slider("单笔股数聚集阈值 (笔数)", min_value=2, max_value=20, value=stock_config['iceberg']['volume_cluster_threshold'])
    
    if st.sidebar.button("保存配置"):
        config_manager.update_stock_config(selected_stock, "iceberg", "volume_cluster_threshold", cluster_threshold)
        st.sidebar.success("已保存！")

elif analysis_mode == "订单流速 (Flow Speed)":
    st.sidebar.subheader("订单流速参数")
    rolling_window = st.sidebar.slider("滚动窗口 (秒)", min_value=1, max_value=300, value=stock_config['flow_speed']['rolling_window_seconds'])
    surge_threshold = st.sidebar.number_input("流速狂飙阈值 (Tick数/窗口)", min_value=10, value=stock_config['flow_speed']['speed_surge_threshold'], step=10)
    
    if st.sidebar.button("保存配置"):
        config_manager.update_stock_config(selected_stock, "flow_speed", "rolling_window_seconds", rolling_window)
        config_manager.update_stock_config(selected_stock, "flow_speed", "speed_surge_threshold", surge_threshold)
        st.sidebar.success("已保存！")

# --- Data Loading Logic ---
@st.cache_data(ttl=60) # Cache for 60 seconds, allows "refresh" by clearing or waiting
def load_data(path, is_mock=False):
    if is_mock or path is None:
        # Generate mock data
        import numpy as np
        np.random.seed(42)
        n = 10000
        df = pd.DataFrame({
            'price': 150 + np.random.randn(n).cumsum() * 0.1,
            'volume': np.random.choice([100, 200, 300, 400, 500], n),
            'ticker_direction': np.random.choice(['buy', 'sell', 'neutral'], n)
        })
        # Inject an iceberg
        df.loc[5000:5010, 'volume'] = 400
        df.loc[5000:5010, 'price'] = 155.5
        return df
    else:
        try:
            df = pd.read_parquet(path)
            return df
        except Exception as e:
            st.error(f"加载 Parquet 文件失败: {e}")
            return pd.DataFrame()

with st.spinner('正在加载 Tick 数据...'):
    df = load_data(file_path, is_mock=(file_path is None))

if st.sidebar.button("刷新数据 (拉取最新录制)"):
    st.cache_data.clear()
    st.rerun()

# --- Main Dashboard ---
if df.empty:
    st.warning("暂无数据。")
    st.stop()

st.subheader(f"数据源: {selected_stock} ({selected_market_date})")
st.write(f"加载的总 Tick 数: {len(df):,}")

# --- Analysis & Visualization ---
fig = go.Figure()

if analysis_mode == "VPIN (订单流毒性)":
    model = VPINModel(volume_bucket_size=volume_bucket_size, window_size=window_size)
    vpin_df = model.calculate(df)
    
    # Plotting
    if not vpin_df.empty:
        # Subplot 1: Price
        fig = go.Figure()
        fig.add_trace(go.Scatter(y=vpin_df['price'], mode='lines', name='价格 (Price)'))
        
        # Subplot 2: VPIN
        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(y=vpin_df['vpin'], mode='lines', name='VPIN', line=dict(color='red')))
        fig2.update_layout(title="VPIN 指标", yaxis_title="VPIN 值")
        
        st.plotly_chart(fig, use_container_width=True)
        st.plotly_chart(fig2, use_container_width=True)
    else:
        st.warning("数据量不足以计算 VPIN。")

elif analysis_mode == "冰山订单 (Iceberg)":
    model = IcebergModel(volume_cluster_threshold=cluster_threshold)
    iceberg_df = model.detect(df)
    
    fig.add_trace(go.Scatter(y=df['price'], mode='lines', name='价格 (Price)', opacity=0.6))
    
    if not iceberg_df.empty:
        st.write(f"检测到 {len(iceberg_df)} 笔可能的冰山订单。")
        fig.add_trace(go.Scatter(
            x=iceberg_df.index, 
            y=iceberg_df['price'], 
            mode='markers', 
            name='冰山订单 (Iceberg Detected)',
            marker=dict(color='red', size=8, symbol='x')
        ))
    else:
        st.write("在当前参数下未检测到冰山订单。")
        
    fig.update_layout(title="冰山订单检测价格图")
    st.plotly_chart(fig, use_container_width=True)

elif analysis_mode == "订单流速 (Flow Speed)":
    model = FlowSpeedModel(rolling_window_seconds=rolling_window, speed_surge_threshold=surge_threshold)
    speed_df = model.calculate(df)
    
    if not speed_df.empty:
        fig.add_trace(go.Scatter(x=speed_df['timestamp'], y=speed_df['tick_speed'], mode='lines', name='流速 (Tick数/窗口)'))
        
        # Highlight surges
        surges = speed_df[speed_df['is_surge']]
        if not surges.empty:
            fig.add_trace(go.Scatter(
                x=surges['timestamp'], 
                y=surges['tick_speed'], 
                mode='markers', 
                name='流速狂飙 (Speed Surge)',
                marker=dict(color='orange', size=8)
            ))
            
        fig.update_layout(title=f"主动性交易流密度 ({rolling_window}秒 窗口)", yaxis_title="窗口内 Tick 数")
        st.plotly_chart(fig, use_container_width=True)
        
        if 'buy_ratio' in speed_df.columns:
            st.write("买卖主动性比例 (主动买单 / 总单)")
            st.line_chart(speed_df.set_index('timestamp')['buy_ratio'])
    else:
        st.warning("数据量不足以计算订单流速。")

