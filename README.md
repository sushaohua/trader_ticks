# Trader Ticks Collector & Analyzer

> A real-time market data collection and microstructure analysis system that connects to **Futu OpenD**, subscribes to tick-level stock data, stores it in **Parquet** format, and provides a **Real-Time Web Dashboard** for advanced microstructure analysis (VPIN, Iceberg orders, Flow Speed).

---

## Architecture

```
├── main_collector.py          # Entry point — CLI for launching data collection
├── configs.template/          # Default config templates tracked by Git
│   ├── futu_settings.json     # Default Futu OpenD connection configuration
│   ├── watchlist_us.json      # US market watchlist template
│   ├── watchlist_hk.json      # HK market watchlist template
│   └── watchlist_cn.json      # CN market watchlist template
├── configs/                   # Active configurations folder (Symlinked to ~/stock_data/configs, gitignored)
├── core/
│   ├── config.py              # Configuration loader supporting env overrides & symlink fallback
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
│   ├── setup_config.sh        # Setup local/remote configs dir & symlink (no-overwrite policy)
│   ├── setup_cron.sh          # Auto-configure crontab adapting to timezone & path
│   ├── verify_local.sh        # Local automated unittest & OpenD connection test
│   ├── deploy_to_yysrv.sh     # One-click push & remote SSH deployment & health verification
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

### 2. Configure Settings & Automated Workflow

This project enforces a strict configuration-code separation to ensure that your custom watchlists and settings are never overwritten when upgrading the code.

#### Step A: Initialize Configuration & Storage
Run the config setup script locally (and it will also run automatically on the remote server):
```bash
./scripts/setup_config.sh
```
This script will:
1. Create `~/stock_data/` directory (e.g., `/Users/sushaohua/stock_data` on macOS or `/home/sushaohua/stock_data` on Linux) with subfolders `archive/`, `reports/`, and `configs/`.
2. Copy missing configurations from `configs.template/` to `~/stock_data/configs/` (existing custom configurations will **never** be overwritten).
3. Create a project symlink `configs` pointing to `~/stock_data/configs` so the application can transparently read and write active configurations.

#### Step B: Install Auto-Adapting Cron Tasks
Install standard background recording schedules to your system crontab:
```bash
./scripts/setup_cron.sh
```
This script automatically:
* Dynamically replaces script execution paths with the current absolute project path.
* Identifies your system timezone. If the system is in **UTC** (common for cloud servers), it will automatically convert Beijing time slots to UTC slots (e.g., HK market 09:30 -> UTC 01:30) before registering them in `crontab`.

#### Step C: Verify Local Environment (Mandatory before deploy)
Run automated testing and local Futu OpenD connection check:
```bash
./scripts/verify_local.sh
```

#### Step D: Deploy to Remote Server yysrv
Once local verification is complete, execute the deployment script:
```bash
./scripts/deploy_to_yysrv.sh
```
This script ensures your local changes are committed and pushed to GitHub, logs into the remote server `yysrv` to pull updates, configures paths and crontab on the server, gracefully restarts running collectors, and runs remote health checks.

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
