# Trader Ticks Collector & Analyzer

> A real-time market data collection and microstructure analysis system that connects to **Futu OpenD**, subscribes to tick-level stock data, stores it in **Parquet** format, and provides a **Real-Time Web Dashboard** for advanced microstructure analysis (VPIN, Iceberg orders, Flow Speed).

---

## Architecture

```
├── main_collector.py          # Entry point — CLI for launching data collection
├── configs/
│   ├── futu_settings.json     # Futu OpenD connection configuration
│   ├── analyzer_params.json   # Dynamic parameters for Analyzer Models
│   ├── watchlist_us.json      # US market watchlist
│   ├── watchlist_hk.json      # HK market watchlist
│   └── watchlist_cn.json      # CN market watchlist
├── core/
│   ├── futu_client.py         # Futu OpenD client — connection, subscription, tick reception
│   └── parquet_engine.py      # Parquet engine — in-memory buffer & Parquet file writing
├── analyzer/
│   ├── app.py                 # Streamlit Real-Time Dashboard (Web UI)
│   ├── config_manager.py      # Manager for dynamic UI and model parameters
│   ├── models/                # Advanced Microstructure Models
│   │   ├── vpin.py            # VPIN (Order Flow Toxicity)
│   │   ├── iceberg.py         # Iceberg Order Detection
│   │   └── flow_speed.py      # Aggressive Order Flow Speed
│   ├── micro_structure.py     # Legacy Microstructure functions
│   └── daily_report.py        # Daily Markdown report generator from Parquet data
├── scripts/
│   ├── run_hk_market.sh       # Shell script to start HK market collection
│   └── run_us_market.sh       # Shell script to start US market collection
└── data/                      # Runtime data directory (gitignored)
    ├── logs/                  # Collector logs
    └── archive/               # Parquet files organized by date
```

---

## Features

- **Multi-market Support** — Collect tick data for US, HK, and CN markets via a single unified interface
- **Futu OpenD Integration** — Connects to [Futu OpenD](https://www.futunn.com/) for real-time stock market data
- **Parquet Storage** — Buffers ticks in memory and flushes them to efficient Parquet files for downstream analysis
- **Advanced Microstructure Analysis Models**:
  - **VPIN (Volume-Synchronized Probability of Informed Trading)**: Measures order flow toxicity and identifies informed trading.
  - **Iceberg Orders (冰山订单)**: Detects hidden large orders through trade duration autocorrelation and volume clustering.
  - **Aggressive Order Flow Speed (主动性交易流密度)**: Analyzes tick flow density and speed surges during critical price levels.
- **Interactive Web UI Dashboard** — Built with Streamlit and Plotly, providing real-time data visualization and on-the-fly parameter tuning.
- **Daily Reports** — Automatically generate Markdown-based daily analysis reports from archived Parquet data.

---

## Requirements

- Python 3.8+
- [Futu OpenD](https://www.futunn.com/) running and accessible (default: `127.0.0.1:11111`)
- Python libraries: `futu-api`, `pandas`, `pyarrow`, `streamlit`, `plotly`

---

## Quick Start

### 1. Clone & Setup Environment

```bash
git clone <repository-url>
cd trader-ticks
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install futu-api pandas pyarrow streamlit plotly
```

### 2. Configure Settings

Edit configuration files in `configs/`:

*   **`futu_settings.json`** — Contains default settings for Futu OpenD connection and relative storage paths.
*   **`futu_settings.local.json`** — (**Recommended for production**) Create this file to override settings locally. It is untracked by Git, so you can specify custom absolute storage directories (e.g., `/home/sushaohua/trader_ticks_data/archive`) and host details without affecting Git updates.
*   **`FUTU_SETTINGS_PATH`** — Alternatively, export this environment variable to load configurations from any arbitrary file path.

### 3. Run Data Collection

Using the virtual environment:

```bash
# US market
python main_collector.py --market US

# HK market
python main_collector.py --market HK

# CN market (A-share)
python main_collector.py --market CN
```

### 4. Run the Analyzer Dashboard (Web UI)

To start the real-time visualization dashboard and analyze your collected parquet data:

```bash
source venv/bin/activate
streamlit run analyzer/app.py --server.address 0.0.0.0
```

*The dashboard will be available at `http://<your-server-ip>:8501`.*

### 5. Generate Offline Reports

Run the offline reporting generator:

```bash
python -m analyzer.daily_report
```

---

## License

[MIT](LICENSE)
