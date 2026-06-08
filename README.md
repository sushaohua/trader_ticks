# Trader Ticks Collector

> A real-time market data collection and microstructure analysis system that connects to **Futu OpenD**, subscribes to tick-level stock data, stores it in **Parquet** format, and generates daily microstructure analysis reports (VPIN, price impact, etc.).

---

## Architecture

```
├── main_collector.py          # Entry point — CLI for launching data collection
├── configs/
│   ├── futu_settings.json     # Futu OpenD connection configuration
│   ├── watchlist_us.json      # US market watchlist
│   ├── watchlist_hk.json      # HK market watchlist
│   └── watchlist_cn.json      # CN market watchlist
├── core/
│   ├── futu_client.py         # Futu OpenD client — connection, subscription, tick reception
│   └── parquet_engine.py      # Parquet engine — in-memory buffer & Parquet file writing
├── analyzer/
│   ├── micro_structure.py     # Microstructure analysis (VPIN, price impact, etc.)
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
- **Microstructure Analysis** — Includes algorithm placeholders for:
  - **VPIN** (Volume-Synchronized Probability of Informed Trading)
  - **Permanent Price Impact**
  - **Temporary Price Impact**
- **Daily Reports** — Automatically generate Markdown-based daily analysis reports from archived Parquet data

---

## Requirements

- Python 3.8+
- [Futu OpenD](https://www.futunn.com/) running and accessible (default: `127.0.0.1:11111`)
- Python libraries: `futu-api`, `pandas`, `pyarrow`

---

## Quick Start

### 1. Clone & Setup Environment

```bash
git clone <repository-url>
cd trader-ticks
python3 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install futu-api pandas pyarrow
```

### 2. Configure Settings

Edit configuration files in `configs/`:

*   **`futu_settings.json`** — Contains default settings for Futu OpenD connection and relative storage paths.
*   **`futu_settings.local.json`** — (**Recommended for production**) Create this file to override settings locally. It is untracked by Git, so you can specify custom absolute storage directories (e.g., `/home/sushaohua/trader_ticks_data/archive`) and host details without affecting Git updates.
*   **`FUTU_SETTINGS_PATH`** — Alternatively, export this environment variable to load configurations from any arbitrary file path.

Example `futu_settings.local.json`:
```json
{
    "futu_opend": {
        "host": "127.0.0.1",
        "port": 11111
    },
    "storage": {
        "base_archive_dir": "/var/data/trader_ticks/archive",
        "base_report_dir": "/var/data/trader_ticks/reports",
        "flush_threshold": 200,
        "flush_interval_seconds": 10,
        "compression": "snappy"
    }
}
```

### 3. Run data collection

Using the virtual environment:

```bash
# US market
venv/bin/python main_collector.py --market US

# HK market
venv/bin/python main_collector.py --market HK

# CN market (A-share)
venv/bin/python main_collector.py --market CN
```

Or run the provided background shell scripts:

```bash
bash scripts/run_us_market.sh
bash scripts/run_hk_market.sh
```

To stop collectors running in the background gracefully (waiting up to 20 seconds for data to flush and close parquet files safely):

```bash
bash scripts/stop_us_market.sh
bash scripts/stop_hk_market.sh
```

### 4. Generate reports

Run the offline reporting generator:

```bash
venv/bin/python -m analyzer.daily_report
```

---

## Project Status

This project is in active development. Core modules and architecture are set up, and basic tests can be run via:
```bash
venv/bin/python -m unittest tests/test_smoke.py
```

---

## License

[MIT](LICENSE)
