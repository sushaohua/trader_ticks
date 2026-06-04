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
- Additional Python dependencies (if any) listed in a future `requirements.txt`

---

## Quick Start

### 1. Clone & configure

```bash
git clone <repository-url>
cd trader-ticks-collector
```

Edit the configuration files in `configs/` as needed:

- **`futu_settings.json`** — Set the Futu OpenD host, port, and password
- **`watchlist_us.json` / `watchlist_hk.json` / `watchlist_cn.json`** — Add stock codes to your watchlist

### 2. Run data collection

```bash
# US market
python main_collector.py --market US

# HK market
python main_collector.py --market HK

# CN market
python main_collector.py --market CN
```

Or use the provided shell scripts:

```bash
bash scripts/run_us_market.sh
bash scripts/run_hk_market.sh
```

### 3. Generate reports (coming soon)

```python
from analyzer.daily_report import DailyReportGenerator

generator = DailyReportGenerator("data/archive")
report = generator.generate_report()
print(report)
```

---

## Project Status

This project is in early development. Core module interfaces are defined, but inner implementations are marked as `TODO`. Contributions and suggestions are welcome.

---

## License

[MIT](LICENSE)
