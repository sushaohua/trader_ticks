# Trader Ticks 开发与运维技能手册 (skill.md)

本文档旨在记录本高频 Tick 数据收集系统的核心架构、部署运行指南、日常运维命令、ClickHouse 数据库管理方法，以及故障灾备排查机制，方便开发与运维人员快速上手。

---

## 🏗️ 系统核心架构与技术栈

本系统基于富途高频 Ticker 推送，采用 **Producer-Consumer (生产者-消费者)** 架构实现数据的实时获取与工业级的高效落盘：
1. **数据获取层 (FutuOpenD)**：通过 Futu SDK 连接本地/远程的 FutuOpenD 网关，利用事件驱动回调订阅 Tick 级别的逐笔交易流。
2. **缓冲队列层 (Python Queue)**：使用线程安全的内置 `queue.Queue`（最大容量限制为 100k 条）作为 Get-Write 缓冲，实现极高频推送与网络写入速度差的完全解耦，防止阻塞富途 SDK 线程。
3. **数据存储层 (ClickHouse)**：基于列式数据库 ClickHouse，通过官方 `clickhouse-connect` HTTP 驱动，采用**全局缓冲批量写入 (Bulk Insert)** 机制，最小化 ClickHouse 磁盘 Merge 的碎片整理压力，同时对各市场数据进行物理时区对齐。
4. **数据防丢失层 (Spill failover)**：具备断线检测、指数退避重连、内存安全控制（最大缓冲 50k 条），在网络中断时自动将内存数据固化至本地临时 Parquet 文件，并在连接恢复后由守护线程异步补录（Replay）。

---

## ⚙️ 环境配置与部署技能

本系统采用**敏感信息隔离**原则，敏感的数据库凭证与网关端口不得硬编码在代码中。

### 1. 配置文件结构
所有的配置统一存放在 `configs/` 目录下（该目录已被 Git 忽略，防止凭证泄露）。
本地开发或部署时，需要从 [configs.template/futu_settings.json](file:///Users/sushaohua/code/trader_ticks/configs.template/futu_settings.json) 模板复制一份为 `configs/futu_settings.json`：

```json
{
    "futu_opend": {
        "host": "127.0.0.1",
        "port": 11111
    },
    "clickhouse": {
        "host": "103.118.254.69",
        "port": 8123,
        "username": "sushaohua",
        "password": "YOUR_PASSWORD",
        "database": "stock_preview"
    },
    "storage": {
        "engine": "clickhouse",
        "base_archive_dir": "./data/archive",
        "base_report_dir": "./data/reports",
        "flush_threshold": 1000,
        "flush_interval_seconds": 3,
        "compression": "snappy"
    }
}
```

> [!IMPORTANT]
> **多环境数据库隔离原则**：
> - **测试/开发环境**：在配置中将 `database` 设为 `"stock_preview"`。
> - **生产/部署环境**：在配置中将 `database` 设为 `"stock"`。
> - 数据库不存在时，系统启动后会自动执行 `CREATE DATABASE IF NOT EXISTS <database>` 自动建库。

---

## 🚀 日常运行与测试指令

### 1. 启动高频收集器
根据收集的目标市场（美股 `US`、港股 `HK`、A股 `CN`），传入 `--market` 参数启动：
```bash
# 收集港股 Tick 数据并实时批量写入 ClickHouse
python3 main_collector.py --market HK

# 收集美股 Tick 数据
python3 main_collector.py --market US
```

### 2. 运行实时流状态监控（远程/本地）
监控看板通过读取公网 ClickHouse 时序数据及本地心跳状态进行实时渲染，可在任意可访问数据库的终端上远程运行：
```bash
# 启动实时监控仪表盘
python3 scripts/monitor_collector.py

# 非交互式单次打印健康状态 (常用于脚本定时检测或 CI)
ONCE=1 python3 scripts/monitor_collector.py
```

### 3. 运行系统单元测试
在提交代码修改前，必须运行测试套件，验证时区解析、异常灾备及 ClickHouse 插入的正确性：
```bash
# 运行 ClickHouse 存储及灾备逻辑单元测试
python3 tests/test_clickhouse.py
```

---

## 📊 ClickHouse 数据库操作指南

### 1. 表结构 DDL
```sql
CREATE TABLE IF NOT EXISTS {database}.ticks (
    code LowCardinality(String),
    name LowCardinality(String),
    time DateTime64(3, 'Asia/Shanghai'),
    price Float64,
    volume Int64,
    turnover Float64,
    ticker_direction LowCardinality(String),
    sequence Int64,
    type LowCardinality(String),
    push_data_type LowCardinality(String)
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(time)
ORDER BY (code, time, sequence)
SETTINGS index_granularity = 8192;
```

### 2. 常用监控查询 SQL

- **查询表已存总行数**：
  ```sql
  SELECT count() FROM stock_preview.ticks;
  ```

- **查询最近 10 分钟平均每秒写入速度 (TPS)**：
  ```sql
  SELECT count() / 600 AS tps 
  FROM stock_preview.ticks 
  WHERE time >= now() - INTERVAL 10 MINUTE;
  ```

- **查看今日各个标的最新 Tick 时间与累计条数（检验延迟）**：
  ```sql
  SELECT 
      code,
      max(time) as last_tick_time,
      count() as cnt
  FROM stock_preview.ticks
  WHERE time >= today()
  GROUP BY code
  ORDER BY last_tick_time DESC;
  ```

- **物理清除某只股票的测试数据**：
  ```sql
  ALTER TABLE stock_preview.ticks DELETE WHERE code = 'HK.TEST_UNIT';
  ```

---

## 🚨 异常排查与故障恢复技能

### 1. 本地心跳状态文件检查
收集进程在运行时，主循环每 10 秒会把当前进程的状态和心跳更新到 [data/collector_status.json](file:///Users/sushaohua/code/trader_ticks/data/collector_status.json) 中。
运维可以通过命令查看健康状况：
```bash
cat data/collector_status.json
```
**指标排查意义：**
- `"last_heartbeat"`: 上次更新时间。如果与当前时间相差 30 秒以上，说明收集器进程已假死或崩溃。
- `"queue_size"`: 线程安全共享队列大小。如果在交易时间内该值持续累积并接近 `100,000` 上限，说明消费者写入数据库线程卡死或网络极慢，存在数据丢弃风险。
- `"db_connected"`: `true` 表示网络与数据库连接正常；`false` 说明当前处于网络断开状态。
- `"failover_files_count"`: 灾备文件堆积数。如果该值大于 `0`，说明有本地 parquet 文件待补录，此时网络可能有问题。

### 2. 本地灾备数据补录 (Replay) 机制
当 ClickHouse 数据库断网时，数据会自动写入以下本地临时目录中：
`data/clickhouse_failover/failover_{timestamp}.parquet`

**恢复操作**：
1. **全自动恢复**：收集器进程内置了 `CHRecoveryThread` 守护线程，它每 5 秒扫描一次网络。当网络重新接通后，后台会自动异步将这些 `.parquet` 文件读入并重新 localized 解析补录写入 ClickHouse，写入成功后会自动执行 `os.remove` 进行物理删除。无需人工干预。
2. **人工手动恢复**：若进程异常退出，您可以通过运行测试或手动起停收集器来触发补录。只要收集器成功连通 ClickHouse，就会自动优先处理 `data/clickhouse_failover/` 下的所有历史积压块。
