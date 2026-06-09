# Trader Ticks 收集与分析引擎

> 一个用于连接 **富途 OpenD (Futu OpenD)** 的实时市场数据收集与微观结构分析系统。该系统能够订阅 Tick 级别的股票数据，将其以高效的 **Parquet** 格式存储在本地，并提供一个基于 **Streamlit** 的实时分析看板 Web UI（支持 VPIN、冰山订单检测、主动性交易流密度等核心模型）。

---

## 🏗 架构设计

```
├── main_collector.py          # 程序入口 — 数据收集主控 CLI
├── configs.template/          # 默认配置模板目录（由 Git 跟踪）
│   ├── futu_settings.json     # 富途 OpenD 连接及默认存储配置模板
│   ├── watchlist_us.json      # 美股监控自选股池模板
│   ├── watchlist_hk.json      # 港股监控自选股池模板
│   └── watchlist_cn.json      # A股监控自选股池模板
├── configs/                   # 活动配置目录（软链接至 ~/stock_data/configs，已加入 gitignore）
├── core/
│   ├── config.py              # 配置加载器（支持环境变量覆盖及软链接回退）
│   ├── futu_client.py         # 富途 OpenD 客户端 — 连接、订阅及 Tick 消息分发
│   └── parquet_engine.py      # Parquet 存储引擎 — 内存双缓冲及 Parquet 文件批量落盘
├── analyzer/
│   ├── app.py                 # Streamlit 实时分析看板（Web UI 服务）
│   ├── config_manager.py      # 动态 UI 及微观模型参数管理器
│   ├── models/                # 高级市场微观结构模型
│   │   ├── vpin.py            # VPIN 模型 (度量知情交易概率与订单流毒性)
│   │   ├── iceberg.py         # 冰山订单检测模型 (基于成交量聚类)
│   │   └── flow_speed.py      # 主动性交易流流速/流密度模型
│   ├── micro_structure.py     # 基础微观结构指标计算函数
│   └── daily_report.py        # 每日历史 Parquet 数据 Markdown 分析报告生成器
├── scripts/
│   ├── setup_config.sh        # 配置与业务解耦初始化脚本 (不覆盖已有的自定义配置)
│   ├── setup_cron.sh          # 定时任务安装脚本 (自适应路径并自动换算 UTC 时区时间)
│   ├── verify_local.sh        # 本地自动测试脚本 (自动运行单元测试及本地 OpenD 连通检查)
│   ├── deploy_to_yysrv.sh     # 一键部署脚本 (本地 GitHub 推送、远程 SSH Pull、自动覆盖软链接与优雅重启)
│   ├── run_hk_market.sh       # 港股收集启动脚本
│   └── run_us_market.sh       # 美股收集启动脚本
└── data/                      # 运行时数据目录（已加入 gitignore）
    ├── logs/                  # 收集器日志输出
    └── archive/               # 按日期归档的 Parquet 数据存储
```

---

## 🌟 系统特性

*   **多市场跨时区支持** — 统一接口，支持港股 (HK)、美股 (US) 和 A股 (CN) 市场高频 Tick 数据的实时订阅与收集。
*   **富途 OpenD 深度集成** — 直连 [富途 OpenD](https://www.futunn.com/) 接收极低延迟的逐笔成交数据。
*   **高效 Parquet 异步落盘** — 内存队列双缓冲机制平衡“读-写”速度差，批量落盘为列式存储 Parquet 文件，保障高频行情的可靠归档。
*   **高级市场微观结构分析**：
    *   **VPIN (知情交易概率)**：采用交易量等分桶算法，动态度量订单流毒性，预警暴跌与流动性崩塌。
    *   **冰山订单检测**：通过成交量聚类、订单拆分关联分析及成交时间间隔自相关性，挖掘隐藏的大单活动。
    *   **主动性交易流速**：分析高频行情中主动买/卖单的瞬时流量涌现，捕获关键价格水平处的资金突破。
*   **交互式 Streamlit 仪表盘** — 实时可视化界面，并支持在页面上动态调节 VPIN/冰山等模型参数并当场重新分析。
*   **自动化每日分析报告** — 每日收盘后，自动从归档的 Parquet 数据中抽提关键微观结构特征并导出为富文本报告。

---

## 📋 依赖要求

*   Python 3.8+
*   已启动并登录的 [富途 OpenD](https://www.futunn.com/) 客户端（默认配置：`127.0.0.1:11111`）
*   依赖库：`futu-api`, `pandas`, `pyarrow`, `streamlit`, `plotly`

---

## 🚀 快速开始

### 1. 克隆项目与环境搭建

```bash
git clone <repository-url>
cd trader-ticks
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install futu-api pandas pyarrow streamlit plotly
```

### 2. 配置与自动化部署工作流

本项目实行**配置与代码的彻底解耦**。您的自选股列表（`watchlist_*.json`）及参数设定在升级业务代码时**绝不会**被覆盖。

#### 步骤 A：本地/远程配置对齐初始化
在开发机或服务器的终端中运行：
```bash
./scripts/setup_config.sh
```
该脚本将自动完成：
1. 在您当前用户的家目录下创建 `~/stock_data`（如 Mac 下的 `/Users/sushaohua/stock_data` 或 Linux 下的 `/home/sushaohua/stock_data`），并建立 `archive/`、`reports/` 和 `configs/` 子目录。
2. 非覆盖式地从 `configs.template/` 复制配置文件模板到该目录中（如果配置已存在，则**不会覆盖**，从而完整保留您的自定义股票池）。
3. 在项目根目录中创建软链接 `configs -> ~/stock_data/configs`。使得程序读写 `./configs/...` 时直接透明指向安全存放的数据目录。

#### 步骤 B：安装定时任务
将标准录制定时计划写入系统 crontab：
```bash
./scripts/setup_cron.sh
```
脚本将自动：
* 动态检测并替换脚本调用的绝对路径为当前项目路径。
* 识别系统时区。如果系统处于 **UTC** 零时区（云服务器常用），脚本会自动将北京时间（港股 09:30, 美股 21:30）换算为 UTC 时间（01:30, 13:30）后安全载入 crontab 中。

#### 步骤 C：一键本地自动测试（部署前必跑）
跑完单元测试及本地 Futu OpenD 通道就绪度校验：
```bash
./scripts/verify_local.sh
```

#### 步骤 D：一键部署到远程服务器 `yysrv`
本地自动验证通过后，在本地终端执行一键同步与更新：
```bash
./scripts/deploy_to_yysrv.sh
```
该脚本会自动确保本地所有新修改都已提交并推送到 GitHub，接着 SSH 连接 `yysrv` 服务器拉取最新代码，更新远程配置软链接与 crontab 定时任务，优雅终止正在运行的收集器以确保数据完全安全落盘，重启收集服务并打印出健康检查报告。

---

### 3. 手动运行数据收集

您也可以直接通过虚拟环境手动调起特定市场的实时收集：

```bash
# 美股行情收集
python main_collector.py --market US

# 港股行情收集
python main_collector.py --market HK

# A股行情收集
python main_collector.py --market CN
```

---

### 4. 运行分析看板（Web UI 仪表盘）

启动实时可视化分析终端：

```bash
source venv/bin/activate
streamlit run analyzer/app.py --server.address 0.0.0.0
```

*默认访问地址：`http://<您的服务器IP>:8501`。*

---

### 5. 离线生成每日报告

在收盘后提取 Parquet 归档行情特征生成 Markdown 分析报告：

```bash
python -m analyzer.daily_report
```

---

## 📄 开源许可证

本项目基于 [MIT](LICENSE) 开源许可证。
