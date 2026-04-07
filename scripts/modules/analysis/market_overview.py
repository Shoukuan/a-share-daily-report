"""
市场全景与交易策略分析模块
"""

from constants import SCORING_CONFIG
from utils import get_logger

logger = get_logger('market_overview')


class MarketOverview:
    """
    市场全景与交易策略分析器
    负责市场情绪、盘面深度、主要指数、全球资产和交易策略的分析
    """

    def __init__(self, config):
        """
        初始化市场分析器

        Args:
            config: 配置字典
        """
        self.config = config
        logger.info("MarketOverview 初始化完成")

    def analyze_market_overview(self, data):
        """
        分析市场全景（情绪评分、趋势、仓位建议）
        封装 data_fetcher.get_market_overview() 的结果

        Args:
            data: 包含 market_overview 信息的字典

        Returns:
            dict: 包含 success 和 data 的结果字典
        """
        market_overview_wrapper = data.get('market_overview', {})
        logger.info(
            f"[DEBUG] analyze_market_overview: wrapper type={type(market_overview_wrapper)}, "
            f"keys={list(market_overview_wrapper.keys()) if isinstance(market_overview_wrapper, dict) else 'not dict'}, "
            f"success={market_overview_wrapper.get('success') if isinstance(market_overview_wrapper, dict) else 'N/A'}"
        )
        if isinstance(market_overview_wrapper, dict) and market_overview_wrapper.get('success'):
            result = {"success": True, "data": market_overview_wrapper['data']}
            logger.info(f"[DEBUG] analyze_market_overview returning: score={market_overview_wrapper['data'].get('score')}")
            return result
        else:
            logger.warning("市场全景数据获取失败或格式错误")
            return {"success": False, "data": None, "error": "无法获取市场全景"}

    def analyze_market_depth(self, data):
        """
        分析盘面深度（炸板率、涨跌幅>5%统计）
        封装 data_fetcher.get_market_depth() 的结果

        Args:
            data: 包含 market_depth 信息的字典

        Returns:
            dict: 包含 success 和 data 的结果字典
        """
        market_depth_wrapper = data.get('market_depth', {})
        if market_depth_wrapper.get('success'):
            return {"success": True, "data": market_depth_wrapper['data']}
        else:
            logger.warning("盘面深度数据获取失败")
            return {"success": False, "data": None, "error": "无法获取盘面深度"}

    def analyze_major_indices(self, data):
        """
        分析主要指数行情（10个指数）
        封装 data_fetcher.get_major_indices() 的结果

        Args:
            data: 包含 major_indices 信息的字典

        Returns:
            dict: 包含 success 和 data 的结果字典
        """
        indices_wrapper = data.get('major_indices', {})
        if indices_wrapper.get('success'):
            return {"success": True, "data": indices_wrapper['data']}
        else:
            logger.warning("主要指数数据获取失败")
            return {"success": False, "data": None, "error": "无法获取主要指数"}

    def analyze_global_assets(self, data):
        """
        分析全球资产联动（美元、黄金、原油）
        封装 data_fetcher.get_global_assets() 的结果

        Args:
            data: 包含 global_assets 信息的字典

        Returns:
            dict: 包含 success 和 data 的结果字典
        """
        global_assets_wrapper = data.get('global_assets', {})
        if global_assets_wrapper.get('success'):
            return {"success": True, "data": global_assets_wrapper['data']}
        else:
            logger.warning("全球资产数据获取失败")
            return {"success": False, "data": None, "error": "无法获取全球资产"}

    def generate_trading_strategy(self, data):
        """
        生成整体交易策略（基于真实数据）

        Args:
            data: 包含 sentiment, money_flow, position 信息的字典

        Returns:
            dict: 包含交易策略信息的字典，包括 strategy, strategy_name, logic, confidence
        """
        try:
            sentiment_data = data.get('sentiment', {}).get('data', {})
            money_flow_data = data.get('money_flow', {}).get('data', {})
            position_data = data.get('position', {}).get('data', {})

            # 基于情绪分和仓位决定策略
            if position_data:
                emotion_score = position_data.get('emotion_score', 50)
                position_min = position_data.get('position_min', 30)
            else:
                # 兼容调用方未提前注入 position 的情况（当前主流程即如此）
                emotion_score = self._calc_emotion_score(sentiment_data, money_flow_data)
                position_min = 30 + (emotion_score / 100.0) * 40

            if emotion_score >= 70 and position_min >= 50:
                strategy = "offensive"
                strategy_name = "进攻"
                logic = "市场情绪火热，涨停家数众多，建议积极做多"
                confidence = 0.8
            elif emotion_score <= 30 and position_min <= 30:
                strategy = "defensive"
                strategy_name = "防守"
                logic = "市场情绪低迷，建议控制仓位，等待机会"
                confidence = 0.7
            else:
                strategy = "neutral"
                strategy_name = "中性"
                logic = "市场情绪中性，建议平衡配置，快进快出"
                confidence = 0.6

            return {
                "success": True,
                "data": {
                    "strategy": strategy,
                    "strategy_name": strategy_name,
                    "logic": logic,
                    "confidence": confidence
                }
            }
        except Exception as e:
            logger.error(f"生成交易策略失败: {e}")
            return {
                "success": True,
                "data": {
                    "strategy": "neutral",
                    "strategy_name": "中性",
                    "logic": "策略生成失败，默认中性",
                    "confidence": 0.5
                }
            }

    def _calc_emotion_score(self, sentiment_data, money_flow_data):
        """
        计算市场情绪分数（0-100），权重由 constants.SCORING_CONFIG 定义

        Args:
            sentiment_data: 市场情绪数据
            money_flow_data: 资金流向数据

        Returns:
            float: 情绪分数（0-100）
        """
        score = SCORING_CONFIG['base_score']

        # 涨停家数加分
        limit_up = sentiment_data.get('limit_up_count', 0)
        score += min(
            SCORING_CONFIG['limit_up_max_score'],
            limit_up / SCORING_CONFIG['limit_up_per_point']
        )

        # 连板高度加分
        max_consec = sentiment_data.get('max_consec_up', 0)
        score += min(
            SCORING_CONFIG['consecutive_max_score'],
            max_consec * SCORING_CONFIG['consecutive_per_point']
        )

        # 北向资金加分
        north_raw = money_flow_data.get('northbound')
        north = 0
        if isinstance(north_raw, dict):
            north = north_raw.get('total_net_inflow', 0)
        elif isinstance(north_raw, (int, float)):
            north = north_raw
        threshold = SCORING_CONFIG['northbound_threshold']
        north_score = SCORING_CONFIG['northbound_score']
        if north > threshold:
            score += north_score
        elif north < -threshold:
            score -= north_score

        return max(0, min(100, score))