"""
分析模块 - 主入口
整合各个分析子模块，提供统一的分析接口
"""

import os
import yaml

from utils import get_logger
from modules.analysis import (
    SummaryGenerator,
    WatchlistAnalyzer,
    TechnicalIndicators,
    PositionSizer,
    ComprehensiveAnalyzer,
    MarketOverview,
)
from modules.analysis.news_classifier import NewsClassifier, NewsMapper

logger = get_logger('analyzer')


class Analyzer:
    """
    主分析器 - 协调各分析子模块
    """

    def __init__(self, config):
        self.config = config
        self.watchlist = self._load_watchlist()

        # 初始化各分析子模块
        self.news_mapper = NewsMapper()
        self.summary_generator = SummaryGenerator(config)
        self.watchlist_analyzer = WatchlistAnalyzer(
            config=config,
            watchlist=self.watchlist,
            news_mapper=self.news_mapper
        )
        self.technical_indicators = TechnicalIndicators(config)
        self.position_sizer = PositionSizer(config)
        self.comprehensive_analyzer = ComprehensiveAnalyzer(config, self.news_mapper)
        self.market_overview = MarketOverview(config)

        logger.info("Analyzer 初始化完成")

    def _load_watchlist(self):
        """加载自选股配置"""
        watchlist_path = self.config.get('watchlist', {}).get('path', 'config/watchlist.yaml')

        if not os.path.isabs(watchlist_path):
            base_dir = os.path.dirname(os.path.dirname(__file__))
            watchlist_path = os.path.join(base_dir, watchlist_path)

        try:
            with open(watchlist_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
                return data.get('watchlist', [])
        except Exception as e:
            logger.warning(f"加载自选股配置失败: {e}")
            return []

    # ========== 摘要生成 ==========
    def generate_summary(self, data, mode):
        """生成摘要（早报/晚报）"""
        return self.summary_generator.generate_summary(data, mode)

    def _generate_morning_summary(self, data):
        """生成早报摘要"""
        return self.summary_generator.generate_morning_summary(data)

    def _generate_evening_summary(self, data):
        """生成晚报摘要"""
        return self.summary_generator.generate_evening_summary(data)

    # ========== 自选股分析 ==========
    def analyze_watchlist_morning(self, data):
        """分析自选股（早报）"""
        return self.watchlist_analyzer.analyze_watchlist_morning(data)

    def analyze_watchlist_evening(self, data):
        """分析自选股（晚报）"""
        return self.watchlist_analyzer.analyze_watchlist_evening(data)

    def get_watchlist_news_mapping(self, data):
        """获取自选股新闻映射"""
        return self.watchlist_analyzer.get_watchlist_news_mapping(data)

    # ========== 市场概览 ==========
    def analyze_market_overview(self, data):
        """分析市场概览"""
        return self.market_overview.analyze_market_overview(data)

    def analyze_market_depth(self, data):
        """分析盘面深度"""
        return self.market_overview.analyze_market_depth(data)

    def analyze_major_indices(self, data):
        """分析主要指数"""
        return self.market_overview.analyze_major_indices(data)

    def analyze_global_assets(self, data):
        """分析全球资产"""
        return self.market_overview.analyze_global_assets(data)

    def generate_trading_strategy(self, data):
        """生成交易策略"""
        return self.market_overview.generate_trading_strategy(data)

    # ========== 技术指标 ==========
    def analyze_technical_analysis(self, data):
        """技术分析"""
        return self.technical_indicators.analyze_technical_analysis(data)

    # ========== 仓位管理 ==========
    def suggest_position(self, data):
        """动态仓位建议"""
        return self.position_sizer.suggest_position(data)

    def suggest_position_with_risk_plan(self, data, north=None, turnover=None, sh_change=None, volatility=None, us_nasdaq_change=None):
        """带风险预案的动态仓位建议"""
        return self.position_sizer.suggest_position_with_risk_plan(
            data, north, turnover, sh_change, volatility, us_nasdaq_change
        )

    # ========== 综合分析 ==========
    def analyze_comprehensive(self, data):
        """综合分析（大盘走势、量能、风格、展望）"""
        return self.comprehensive_analyzer.analyze_comprehensive(data)

    def analyze_theme_tracking(self, data):
        """主题投资追踪"""
        return self.comprehensive_analyzer.analyze_theme_tracking(data)

    def analyze_strategy_adjustment(self, data, morning_pred=None):
        """策略调整分析"""
        return self.comprehensive_analyzer.analyze_strategy_adjustment(data, morning_pred)

    def analyze_sector_rotation(self, data):
        """板块轮动分析"""
        return self.comprehensive_analyzer.analyze_sector_rotation(data)

    # ========== 聚焦个股分析 ==========
    def analyze_focus_stocks(self, data):
        """分析聚焦个股"""
        try:
            watchlist = self.watchlist
            watchlist_performance = data.get('watchlist_performance', [])

            # 性能数据映射：code -> performance
            perf_map = {p.get('code'): p for p in watchlist_performance}

            focus_list = []
            for stock in watchlist[:3]:  # 最多3只
                code = stock.get('code')
                name = stock.get('name')
                perf = perf_map.get(code, {})
                change_pct = perf.get('change_pct', 0)

                # 生成逻辑和策略
                focus_logic = self._generate_focus_logic(name, change_pct)
                price = perf.get('price', 0)
                ma5 = perf.get('ma5', 0)
                ma20 = perf.get('ma20', 0)
                entry_range = self._generate_entry_range(change_pct, price, ma5, ma20)
                stop_loss = self._generate_stop_loss(change_pct, price, ma20)

                focus_list.append({
                    "code": code,
                    "name": name,
                    "focus_logic": focus_logic,
                    "entry_range": entry_range,
                    "stop_loss": stop_loss
                })

            return {"success": True, "data": focus_list}
        except Exception as e:
            logger.error(f"分析聚焦个股失败: {e}")
            return {"success": True, "data": []}

    # ========== 新闻分类 ==========
    def classify_news(self, news_list):
        """分类新闻"""
        classifier = NewsClassifier(self.config)
        return classifier.classify_news(news_list)

    # ========== 辅助方法 ==========
    def _generate_focus_logic(self, name, change_pct):
        """生成聚焦个股逻辑"""
        if change_pct >= 9.9:
            return f"{name}涨停，强势突破，关注明日溢价"
        elif change_pct >= 7:
            return f"{name}大涨{change_pct:.1f}%，逼近涨停，资金追捧"
        elif change_pct >= 5:
            return f"{name}涨幅超5%，表现活跃，关注量能"
        else:
            return f"{name}表现良好，技术面走强"

    def _generate_entry_range(self, change_pct, price=0, ma5=0, ma20=0):
        """生成买入区间"""
        if price > 0 and ma5 > 0:
            return f"{ma5 * 0.98:.2f}-{ma5:.2f}"
        elif price > 0:
            return f"{price * 0.97:.2f}-{price:.2f}"
        else:
            return "-"

    def _generate_stop_loss(self, change_pct, price=0, ma20=0):
        """生成止损位"""
        if price > 0 and ma20 > 0:
            return f"{ma20:.2f}"
        elif price > 0:
            return f"{price * 0.95:.2f}"
        else:
            return "-"