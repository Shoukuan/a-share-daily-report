# 📈 A股日报生成器 (A-Share Daily Report)

> **基于 AI Agent 的 A 股自动化日报系统** — 多源数据采集 + 智能分析 + 飞书一键发布

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![中文](https://img.shields.io/badge/%E4%B8%AD%E6%96%87-文档-red.svg)](README.md)

---

## ✨ 你能得到什么

每天早上自动收到一份结构化的 A 股市场早报（或盘后晚报），包含：

- 📊 **30 秒总览** — 一句话总结当日市场机会与风险
- 💹 **自选股预测** — 基于技术面的看涨/看跌判断 + 止损建议
- 🎯 **交易策略** — 进攻/中性/防守信号 + 凯利公式仓位推荐
- 🔥 **主题追踪** — 算力、半导体、新能源等热门板块实时表现
- 📰 **新闻分级** — 红/黄/绿三级重要性自动分类
- 🌍 **全球联动** — 美股、期指、美元、黄金、原油一站式
- 🔮 **预测复盘** — 早报预测 vs 晚报实际，命中率统计（预测闭环）
- ⚡ **并行拉取** — 多源数据并行采集，报告生成速度提升 50%
- 📉 **高级分析** — ATR 波动率、真实 RSI(14)、5 日支撑/阻力位
- 💰 **深度资金** — 融资融券、大宗交易 TOP10 数据
- 📝 **审计日志** — 完整操作记录与阶段耗时追踪

---

## 🏗 架构一览

```
数据采集 ──→ 智能分析 ──→ 报告渲染 ──→ 保存/发布
  │             │             │              │
akshare     交易策略     Markdown模板    本地文件
yfinance   凯利公式     结构化排版     飞书文档
tushare    技术面RSI    早报/晚报     飞书消息
APIs...    新闻分级     分级展示
```

---

## 🚀 快速开始（5 分钟）

### 1. 安装依赖

```bash
pip install akshare yfinance pyyaml pandas python-dotenv jinja2
```

### 2. 配置自选股

创建 `config/watchlist.yaml`：

```yaml
watchlist:
  - code: "002594.SZ"
    name: "比亚迪"
    note: "新能源车龙头"
  - code: "300308.SZ"
    name: "中际旭创"
    note: "光模块龙头"
  - code: "600519.SH"
    name: "贵州茅台"
    note: "白酒龙头"
```

### 3. 生成你的第一份报告

```bash
# 生成早报
python scripts/generate_report.py --mode morning

# 生成晚报（盘后复盘）
python scripts/generate_report.py --mode evening

# 指定日期
python scripts/generate_report.py --mode morning --date 2026-04-05
```

报告将保存到本地 `reports/morning/` 或 `reports/evening/` 目录。

---

## 📋 报告内容对比

| 章节 | 早报（盘前） | 晚报（盘后） |
|------|:-----------:|:-----------:|
| 30 秒总览 | ✅ 核心机会+风险 | ✅ 走势+情绪总结 |
| 自选股分析 | ✅ 看涨/看跌预测 | ✅ 涨跌复盘 + 明日策略 |
| 交易策略 | ✅ 进攻/防守 + 仓位建议 | ✅ 明日关注标的 |
| 市场情绪 | — | ✅ 情绪评分 0-100 |
| 盘面深度 | — | ✅ 涨停/跌停/炸板统计 |
| 全球资产 | — | ✅ 美元/黄金/原油 |
| 技术面分析 | — | ✅ RSI/MACD/支撑阻力 |
| 主题投资追踪 | — | ✅ 热门板块排行 |
| 龙虎榜 | — | ✅ 机构/游资买卖 |
| 行业资金流向 | ✅ 北向/主力 | ✅ 详细排行 |
| 国内要闻 | ✅ 分级新闻 | ✅ 分级新闻 |

---

## 📡 数据源

系统采用**多源降级策略**，主源失败自动切换备用源，极端情况下用 Mock 数据保证报告完整输出：

| 数据类型 | 主源 | 备用源 |
|---------|------|--------|
| A 股指数/板块/情绪 | akshare | yfinance / Mock |
| 资金流向 | akshare / tushare | Mock |
| 龙虎榜 | akshare | Mock |
| 美股行情 | yfinance | Mock |
| 期指 (A50/沪深300) | mx-data API | Mock |
| 财经新闻 | mx-search API | Mock |
| 融资融券 | akshare | Mock |
| 大宗交易 | akshare | Mock |

> 无需付费 API 也能运行 — 仅使用 akshare + yfinance 免费源即可生成基础报告。

---

## 📦 项目结构

```
a-share-daily-report/
├── config/
│   ├── config.yaml              # 主配置文件（含 Kelly 公式参数、dry_run 等）
│   └── watchlist.yaml           # 自选股列表
├── scripts/
│   ├── generate_report.py       # 主入口（支持审计日志、性能监控）
│   ├── data_fetcher.py          # 数据采集统一入口（组合各 fetcher）
│   ├── data_collectors.py       # 早/晚报采集器（并行拉取，ThreadPoolExecutor）
│   ├── fetchers/                # 分源采集模块
│   │   ├── index_fetcher.py
│   │   ├── sentiment_fetcher.py
│   │   ├── money_fetcher.py
│   │   ├── international_fetcher.py
│   │   ├── news_fetcher.py
│   │   ├── sector_fetcher.py
│   │   ├── margin_fetcher.py    # 融资融券数据
│   │   └── block_trade_fetcher.py  # 大宗交易 TOP10
│   ├── providers/               # 外部 provider 解析（如 mx provider）
│   ├── analyzer.py              # 分析引擎（策略/仓位/主题/技术面）
│   ├── renderer.py              # 渲染统一入口
│   ├── morning_renderer.py      # 早报渲染
│   ├── evening_renderer.py      # 晚报渲染（含预测复盘）
│   ├── template_engine.py       # Jinja2 模板引擎
│   ├── templates/               # Jinja2 模板目录
│   ├── publisher.py             # 飞书文档发布 + 消息通知（支持 dry_run）
│   ├── pdf_converter.py         # PDF 策略模式（fpdf2/weasyprint/wkhtmltopdf）
│   ├── prediction_store.py      # 早报预测快照存储（早晚报闭环）
│   ├── models.py                # dataclass 数据模型
│   ├── schemas.py               # Pydantic V2 数据验证
│   ├── config_validator.py      # AppConfig 配置校验
│   ├── trade_calendar.py        # 交易日历判（含节假日）
│   └── utils/                   # 缓存/日志/观测/trace/工具
│       ├── cache.py
│       ├── logger.py
│       ├── observability.py
│       ├── trace.py
│       ├── network.py
│       └── helpers.py           # cn_today() / cn_now() UTC+8 时区函数
├── tests/                       # 单元测试 + 集成测试
├── reports/                     # 生成的报告（自动创建）
│   ├── morning/
│   ├── evening/
│   ├── predictions/             # 早报预测快照（YYYYMMDD.json）
│   └── pdf/
├── logs/                        # 日志目录（gitignore）
│   └── audit.jsonl              # 审计日志（按行 JSON）
├── requirements.txt             # 依赖锁定（19 个包）
└── README.md
```

---

## 🔧 进阶用法

### 发布到飞书

```bash
python scripts/generate_report.py --mode morning --publish
```

需在 `config/config.yaml` 中配置飞书参数，或设置环境变量：
```bash
export FEISHU_NOTIFY_OPEN_ID=ou_xxxxxxxx
```
在 OpenClaw 环境中，`publisher.py` 会优先通过 `openclaw.tools` 直接调用：
- `feishu_create_doc`
- `feishu_im_user_message`

### 定时任务（Cron）

配合系统 cron 或 OpenClaw Cron 实现每日自动推送：

```bash
# 每个交易日早上 7:30 生成早报
30 7 * * 1-5 cd /path/to/a-share-daily-report && python scripts/generate_report.py --mode morning
```

### 自定义配置

详细配置说明见 `config/config.yaml` 注释，支持：
- 启用/停用数据源
- 自定义报告输出路径
- 飞书文档文件夹 Token
- 缓存 TTL 控制
- **Kelly 公式参数配置**（`analysis.kelly` 节：win_rate、risk_reward_ratio、half_kelly）
- **Dry-run 模式**（`publish.dry_run: true` 或环境变量 `A_SHARE_DRY_RUN=1`）

#### Kelly 公式配置示例
```yaml
analysis:
  kelly:
    win_rate: 0.5              # 策略胜率（建议通过回测校准）
    risk_reward_ratio: 2.0      # 盈亏比（1:2 止损止盈）
    half_kelly: false           # 是否使用半凯利（更保守）
```

#### Dry-run 模式示例
```bash
# 环境变量方式
export A_SHARE_DRY_RUN=1
python scripts/generate_report.py --mode morning

# 或修改 config.yaml
publish:
  dry_run: true    # 跳过真实的飞书发布，仅记录日志
```

### 可观测性（新增）

支持结构化 JSON 日志、trace_id 透传、阶段耗时采集：

```bash
# 结构化日志（ELK 推荐）
export A_SHARE_LOG_JSON=1

# 日志级别
export A_SHARE_LOG_LEVEL=INFO

# StatsD（可选）
export STATSD_HOST=127.0.0.1
export STATSD_PORT=8125
export STATSD_PREFIX=a_share_report
```

说明：
- 日志自动脱敏 `api_key/token/authorization/password` 等字段。
- `trace_id` 自动注入日志，并在超时线程执行中保持上下文。
- 各阶段（fetch/analyze/render/save/publish）会记录耗时到日志，并可上报 Prometheus/StatsD。

---

## 🧪 测试

```bash
# 运行全部测试
pytest tests/ -v

# 按模块测试
pytest tests/test_analyzer.py -v      # 分析模块 (10 用例)
pytest tests/test_renderer.py -v      # 渲染模块 (5 用例)
pytest tests/test_data_fetcher.py -v  # 数据采集 (9 用例)
pytest tests/test_integration.py -v   # 集成测试 (6 用例)
```

---

## 📝 TODO

详见 [TODO.md](TODO.md)。欢迎提 Issue / PR 贡献功能！

---

## 🤝 贡献

欢迎提 Issue 报告问题，或发 Pull Request 贡献代码。

---

## 📄 许可证

MIT License — 详见 [LICENSE](LICENSE) 文件。

---

## 👤 作者

由 [阿宽](https://github.com/Shoukuan) 创建，基于 OpenClaw AI Agent 平台构建。

> 💡 **企业定制** — 需要私有化部署、自定义数据源对接或团队协作方案？联系我们获取支持。
