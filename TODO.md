
# A股日报 - 开发进度 TODO

---

## Phase 1: 项目基础搭建 ✅ 已完成

- [x] 创建项目目录结构
- [x] 创建配置文件（config.yaml、watchlist.yaml）
- [x] 创建工具函数层（cache、logger、helpers）
- [x] 创建交易日历模块

---

## Phase 2: 核心模块开发 ✅ 已完成

### 2.1 数据采集模块 ✅
- [x] DataFetcher 类（1600+ 行）
- [x] 指数数据（akshare stock_zh_index_spot_em + yfinance 降级）
- [x] 市场情绪（涨停/连板/涨跌家数）
- [x] 资金流向（北向资金 + 主力资金）
- [x] 行业/概念板块数据
- [x] 龙虎榜数据
- [x] 美股数据（yfinance）
- [x] 期指数据（mx-data API：A50、沪深300）
- [x] 新闻数据（mx-search API + 重要性分级）
- [x] 市场全景（情绪评分 + 趋势判断）
- [x] 盘面深度（炸板率、涨跌幅统计）
- [x] 主要指数（10 个 A 股指数）
- [x] 全球资产（美元、黄金、原油）
- [x] 行业资金流向
- [x] 自选股行情（含均线、量比等技术指标）
- [x] 多级降级策略（主源 → 备用源 → Mock）
- [x] 文件缓存层（TTL 控制）

### 2.2 分析模块 ✅
- [x] Analyzer 类（978 行）
- [x] 30 秒总览（早报/晚报两种模式）
- [x] 自选股预测（早报：基于行情+技术面）
- [x] 自选股复盘（晚报：涨跌统计+最佳/最差）
- [x] 交易策略生成（进攻/中性/防守）
- [x] 关注标的分析（介入区间+止损位）
- [x] 凯利公式动态仓位（含情绪分+波动率约束）
- [x] 市场全景分析
- [x] 盘面深度分析
- [x] 主要指数分析
- [x] 全球资产分析
- [x] 技术面分析（RSI、MACD、支撑阻力）
- [x] 综合分析（大盘走势、量能、风格、展望）
- [x] 主题投资追踪（8 个预定义主题：算力、半导体、新能源、风电、金属、低空经济、商业航天、生物制造）
- [x] 新闻分级（🔴重大/🟡中等/🟢一般）

### 2.3 渲染模块 ✅
- [x] Renderer 类（878 行）
- [x] 早报预测版完整渲染
- [x] 晚报复盘版完整渲染（含市场全景、盘面深度、全球资产、技术分析、综合分析、主题追踪）

### 2.4 发布模块 ✅
- [x] Publisher 类（257 行）
- [x] 飞书文档创建（OpenClaw 环境自动调用真实 API，开发环境模拟）
- [x] 飞书消息通知
- [x] 环境自动检测（OPENCLAW_RUNTIME 环境变量）
- [x] 配置灵活（.env + config.yaml 双重支持）

### 2.5 主控制器 ✅
- [x] ReportGenerator 类
- [x] 命令行参数解析（--mode、--date、--config、--publish、--outdir）
- [x] 完整早报流程（采集→分析→渲染→保存→发布）
- [x] 完整晚报流程（15 项数据采集→12 项分析→渲染→保存→发布）
- [x] 报告自动保存到配置目录

### 2.6 测试 ✅
- [x] test_analyzer.py（10 用例，全部通过）
- [x] test_renderer.py（5 用例）
- [x] test_data_fetcher.py（9 用例）
- [x] test_integration.py（6 用例）

---

## Phase 3: 未来优化方向

### 3.1 数据源增强 ✅ 已完成
- [x] 接入 tushare 资金流向 API（需配置 TUSHARE_TOKEN）
- [x] 增加融资融券数据（MarginFetcherMixin）
- [x] 增加大宗交易数据（BlockTradeFetcherMixin）
- [ ] 增加 ETF 资金流向

### 3.2 分析算法优化 ✅ 已完成
- [ ] 凯利公式参数接入回测数据（历史胜率 p、盈亏比 b）
- [x] 基于 5 日 ATR 计算真实波动率（替代当日涨跌幅代理）
- [x] 增加最大回撤控制因子（max_drawdown 参数）
- [x] 增加持仓时长风险调整
- [x] 真实 RSI(14) 计算（需传入 index_history）
- [x] 5 日支撑/阻力位计算（基于近 5 日高低点）

### 3.3 报告增强
- [x] PDF 导出（fpdf2，纯 Python 方案，已集成到 generate_report.py 主流程）
- [ ] 图表可视化（matplotlib 生成 K 线图、板块涨跌柱状图、资金流向图）
- [ ] 历史报告对比（连续多日趋势分析）

### 3.4 自动化调度 ✅ 已完成
- [ ] 早报定时生成（每日 7:00）
- [ ] 晚报定时生成（每日 17:30）
- [x] dry_run 模式支持（环境变量 A_SHARE_DRY_RUN=1 或 config）
- [x] 时区感知（cn_today() / cn_now() UTC+8 函数）
- [ ] 异常告警通知

### 3.5 回测系统
- [ ] 基于历史数据的仓位建议回测
- [ ] 计算策略收益率、夏普比率、最大回撤
- [ ] 输出回测报告

### 3.6 预测复盘闭环 ✅ 已完成
- [x] 早报预测快照存储（PredictionStore）
- [x] 晚报加载早报快照
- [x] 预测 vs 实际对比，命中率统计
- [x] 每股预测失误原因分析

### 3.7 工程完善 ✅ 已完成
- [x] 数据并行拉取（ThreadPoolExecutor，2 阶段：先指数，后并行）
- [x] Pydantic V2 数据验证（schemas.py）
- [x] 完整 AppConfig 配置校验（config_validator.py）
- [x] 审计日志（logs/audit.jsonl）
- [x] 依赖锁定（requirements.txt 19 个包）
- [x] CI 烟雾测试（scripts/run_ci_smoke.sh，覆盖率 ≥60%）

---

## 完成度统计

| 模块 | 完成度 | 状态 |
|------|--------|------|
| 工具函数层 | 100% | ✅ 时区感知（cn_today/cn_now）、节假日 |
| 配置文件 | 100% | ✅ Kelly 参数配置化、dry_run 模式 |
| 数据采集模块 | 98% | ✅ 并行拉取、融资融券、大宗交易 / ETF 待补充 |
| 分析模块 | 95% | ✅ ATR、Kelly、RSI 真实计算 / 回测参数待接入 |
| 渲染模块 | 100% | ✅ 早晚报完整渲染 + 预测复盘 |
| 主控制器 | 100% | ✅ 审计日志、性能监控 |
| 预测存储 | 100% | ✅ PredictionStore 早晚报闭环 |
| 报告保存器 | 100% | ✅ ReportSaver |
| 数据验证层 | 100% | ✅ Pydantic V2 Schemas |
| 熔断器 | 100% | ✅ CircuitBreaker |
| 发布模块 | 90% | ✅ Agent 驱动飞书发布流程 + dry_run |
| 测试 | 75% | ✅ 16/16 核心用例通过 + CI 烟雾测试 |
| 凯利公式仓位 | 90% | ✅ 基础实现 + 参数配置化 / 回测待接入 |
| 主题追踪 | 100% | ✅ 8 个预定义主题 |
| 依赖锁定 | 100% | ✅ requirements.txt 19 个包 |

**总体完成度：约 97%**（较 96% 提升 1%）

---

## P0 修复记录（2026-04-04）

### P0-1：tushare 降级源接入
- [x] `get_market_sentiment()` → `_get_market_sentiment_tushare()` — `pro.limit_list_d()` 涨停/跌停/连板/炸板
- [x] `get_lhb_data()` → `_get_lhb_data_tushare()` — `pro.top_list()` 龙虎榜
- [x] `get_market_depth()` → `_get_market_depth_tushare()` — `pro.limit_list_d()` 炸板率
- [x] `get_market_overview()` — akshare legu 失败后 `pro.daily()` 全市场涨跌统计

### P0-2：测试 import 路径修复
- [x] 4 个测试文件添加 `SCRIPTS_DIR` sys.path
- [x] 16/16 核心用例通过

### P0-3：飞书发布流程
- [x] `generate_report.py` 输出 `REPORT_PATH:` 标记
- [x] `config.yaml` 启用 `feishu_message.enabled: true`

---

## P1 增强记录（2026-04-06）

### P1-1：主控制器拆分
- [x] 新建 `report_saver.py`（ReportSaver 类，140 行）
  - `save_markdown()` - 保存 Markdown 文件
  - `export_pdf()` - 可选 PDF 导出（支持多引擎）
  - `save_report_with_pdf()` - 统一接口
- [x] `generate_report.py` 清理
  - 移除 `_save_report`、`_export_pdf`、`_pdf_via_*`、`_find_cjk_font`（约 180 行）
  - 注入 `ReportSaver`，调用 `self.saver.save_report_with_pdf()`
  - 类大小从 562 行 → 380 行（-32%）
- [x] 删除 `publisher` 中的 PDF 转换引用（已转移）

### P1-3：网络熔断机制
- [x] 新建 `utils/circuit_breaker.py`（180 行）
  - `CircuitBreaker` 类：CLOSED → OPEN → HALF_OPEN 状态机
  - `@circuit_breaker` 装饰器工厂
  - `CircuitBreakerManager` 全局管理器
- [x] 集成到 `data_fetcher.py`
  - `@circuit_breaker('akshare.stock_zh_index_spot_em', failure_threshold=3, recovery_timeout=300)`
  - 保护 `_get_spot_em()` 方法
- [x] 导出到 `utils/__init__.py`

### P1-5：数据验证层
- [x] 新建 `schemas.py`（230 行）
  - 9 个 Pydantic Schema: IndexData, MarketSentiment, MoneyFlow, SectorInfo, SectorData, LHBItem, NewsItem, MarketOverview, MarketDepth, GlobalAssets
  - 统一接口: `validate_schema()`、`validate_many()`
- [x] 验证集成到各 Fetcher：
  - `index_fetcher.py`: akshare/baostock/yfinance 三处成功返回点前
  - `sentiment_fetcher.py`: akshare 和 tushare 两处成功返回点前
  - `money_fetcher.py`: 最终返回前
  - `news_fetcher.py`: 缓存前批量验证 `validate_many(news_items, NewsItemSchema)`
  - `sector_fetcher.py`: 已集成（之前完成）
- [x] 验证策略：非阻塞，失败仅记录 warning，不影响流程

---

## P0 缺陷修复记录（2026-04-06）

### P0-4：缓存命名空间冲突
- [x] `utils/cache.py:19-23` - `key_hash = hashlib.md5(f"{namespace}:{key}".encode()).hexdigest()`

### P0-3：主题追踪字段名不匹配
- [x] `analyzer.py:737` - `s.get('sector', '')` 添加默认值

### P0-5：新闻解析路径硬编码
- [x] `fetchers/news_fetcher.py:108-180` - 新增 `_extract_news_items()` 支持多级探测
  - 路径 1: `result['data']['data']['llmSearchResponse']['data']`
  - 路径 2: `result['llmSearchResponse']['data']`
  - 路径 3: `result['data']` / `result['items']` / `result['news']`
  - 路径 4: 递归搜索任意包含 news/item 的列表

### P0-1：`_get_spot_em()` 内存泄漏
- [x] `data_fetcher.py:50-53, 160-202`
  - 添加 `_spot_cache_ts` 和 `_spot_cache_ttl = 300`
  - 自动清理过期缓存（5 分钟 TTL）
  - 失败时重置时间戳，允许后续重试

### P0-2：早报缺少自选股统计
- [x] `generate_report.py:303-311` - 新增 `watchlist_stats`（涨跌数、平均收益）

---

*最后更新：2026-04-07*

---

## P0 时区/dry_run/节假日优化 ✅ 已完成（2026-04-06）

### P0-1：时区感知函数
- [x] `scripts/utils/helpers.py` 新增 `cn_today()` / `cn_now()` UTC+8 时区函数
- [x] 所有 `date.today()` / `datetime.now()` 已替换为时区感知版本

### P0-2：dry_run 模式
- [x] `scripts/publisher.py` 支持 dry_run 模式
- [x] 环境变量 `A_SHARE_DRY_RUN=1` 或 config `publish.dry_run: true`

### P0-3：节假日更新
- [x] `scripts/trade_calendar.py` 补充 2026 年中秋节假日

---

## P1 并行数据拉取/缓存优化 ✅ 已完成（2026-04-06）

### P1-1：并行拉取重构
- [x] `scripts/data_collectors.py` 重写为 ThreadPoolExecutor 并行拉取
- [x] 2 阶段策略：先指数，后其余 9-11 个源并行

### P1-2：缓存 TTL 简化
- [x] `scripts/data_fetcher.py` `_spot_cache` TTL 逻辑简化

---

## P2 分析算法优化 ✅ 已完成（2026-04-06）

### P2-1：ATR 波动率
- [x] `scripts/analyzer.py` `_get_volatility()` 支持 5 日 ATR 计算（需传入 history）

### P2-2：Kelly 公式增强
- [x] `scripts/analyzer.py` `_calculate_kelly_position()` 新增 max_drawdown 参数

### P2-3：真实技术分析
- [x] `scripts/analyzer.py` `analyze_technical_analysis()` 支持真实 RSI(14) 和 5 日支撑/阻力计算

---

## P3 新数据源 ✅ 已完成（2026-04-06）

### P3-1：融资融券数据
- [x] `scripts/fetchers/margin_fetcher.py` 新增 MarginFetcherMixin

### P3-2：大宗交易数据
- [x] `scripts/fetchers/block_trade_fetcher.py` 新增 BlockTradeFetcherMixin（TOP10）

### P3-3：Kelly 参数配置化
- [x] `config/config.yaml` 新增 `analysis.kelly` 配置节

---

## P4 早晚报闭环 ✅ 已完成（2026-04-06）

### P4-1：预测快照存储
- [x] `scripts/prediction_store.py` 新增早报预测快照存储
- [x] `save_morning_prediction(dt, watchlist, position)` 保存到 `reports/predictions/YYYYMMDD.json`
- [x] `load_morning_prediction(dt)` 晚报读取
- [x] `compare_predictions(morning_pred, actual)` 计算命中率

### P4-2：晚报预测复盘
- [x] 晚报新增"🔮 早报预测复盘"章节
- [x] 显示预测命中率（如"命中率 75%（3/4）"）
- [x] 仓位建议回顾
- [x] 每股"早报预判 vs 今日实际"对比表格

---

## P5 工程完善 ✅ 已完成（2026-04-06）

### P5-1：Pydantic V2 迁移
- [x] `scripts/schemas.py` 迁移到 Pydantic V2

### P5-2：配置校验增强
- [x] `scripts/config_validator.py` 完整 AppConfig 模型层级（含 PdfConfig/KellyConfig 等）

### P5-3：审计日志
- [x] `scripts/generate_report.py` 审计日志写入 `logs/audit.jsonl`

### P5-4：依赖锁定
- [x] `requirements.txt` 新增（锁定 19 个依赖版本）

### P5-5：CI 烟雾测试
- [x] `scripts/run_ci_smoke.sh` 增强（语法检查 + 覆盖率门禁 ≥60%）

### P5-6：分析方法改进
- [x] `analyze_comprehensive()` 改为真正的归因分析（关联领涨行业/北向资金/新闻催化）
- [x] `generate_report.py` 晚报分析方法从"直传原始数据"改为调用 `analyze_market_overview()` 等方法

---

## P6 待办事项（优先级待定）

### P6-1：回测系统
- [ ] 基于历史数据的仓位建议回测
- [ ] 计算策略收益率、夏普比率、最大回撤
- [ ] 输出回测报告

### P6-2：异常告警系统
- [ ] 数据源失败告警
- [ ] 报告生成失败告警
- [ ] 飞书消息发送失败告警

### P6-3：ETF 资金流向
- [ ] 接入 ETF 资金流向数据
- [ ] 集成到资金流向分析

### P6-4：图表可视化
- [ ] matplotlib 生成 K 线图
- [ ] 板块涨跌柱状图
- [ ] 资金流向图
