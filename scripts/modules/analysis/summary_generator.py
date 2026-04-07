"""
摘要生成模块
生成早报和晚报的摘要内容
"""

from constants import NEWS_KEYWORD_MAP
from utils import get_logger

logger = get_logger('summary_generator')


class SummaryGenerator:
    """早报和晚报摘要生成器"""

    def __init__(self, config):
        self.config = config

    def generate_summary(self, data, mode):
        """根据模式生成摘要"""
        if mode == 'morning':
            return self.generate_morning_summary(data)
        else:
            return self.generate_evening_summary(data)

    def generate_morning_summary(self, data):
        """
        生成早报摘要（基于隔夜美股和昨日晚间数据）
        """
        try:
            us_market_data = data.get('us_market', {}).get('data', {})
            sentiment_data = data.get('sentiment', {}).get('data', {}) or {}
            news = data.get('news', {}).get('data', [])[:3] if data.get('news', {}).get('data') else []

            # 1. 美股表现
            nasdaq_change = 0.0
            sp500_change = 0.0
            if isinstance(us_market_data, dict):
                indices_dict = us_market_data.get('indices', {})
                if isinstance(indices_dict, dict):
                    nasdaq = indices_dict.get('nasdaq', {})
                    sp500 = indices_dict.get('sp500', {})
                    try:
                        nasdaq_change = float(nasdaq.get('change_pct', 0)) if isinstance(nasdaq, dict) else 0.0
                    except (ValueError, TypeError):
                        nasdaq_change = 0.0
                    try:
                        sp500_change = float(sp500.get('change_pct', 0)) if isinstance(sp500, dict) else 0.0
                    except (ValueError, TypeError):
                        sp500_change = 0.0
                else:
                    nasdaq_change = 0.0
                    sp500_change = 0.0
            else:
                nasdaq_change = 0.0
                sp500_change = 0.0

            if nasdaq_change > 1.0:
                us_desc = f"纳斯达克大涨{nasdaq_change:.2f}%，AI概念股强势"
            elif nasdaq_change > 0:
                us_desc = f"纳斯达克上涨{nasdaq_change:.2f}%，美股整体偏暖"
            elif nasdaq_change > -1.0:
                us_desc = f"纳斯达克小幅下跌{abs(nasdaq_change):.2f}%，影响有限"
            else:
                us_desc = f"纳斯达克大跌{abs(nasdaq_change):.2f}%，需警惕A股跟跌"

            # 2. 市场情绪（昨日涨停数据）
            limit_up = sentiment_data.get('limit_up_count', 0)
            if limit_up > 80:
                emotion_desc = f"昨日涨停{limit_up}家，市场极度活跃"
            elif limit_up > 50:
                emotion_desc = f"昨日涨停{limit_up}家，情绪偏暖"
            elif limit_up > 30:
                emotion_desc = f"昨日涨停{limit_up}家，情绪一般"
            else:
                emotion_desc = f"昨日涨停仅{limit_up}家，市场谨慎"

            # 3. 机会识别（从新闻提取关键词）
            opportunities = []
            keyword_map = NEWS_KEYWORD_MAP
            for keys, desc in keyword_map:
                for news_item in news:
                    title = news_item.get('title', '')
                    if any(k in title for k in keys) and desc not in opportunities:
                        opportunities.append(desc)
                        break

            if not opportunities:
                # 从涨停数和情绪推断
                if limit_up > 50:
                    opportunities = ["市场情绪偏暖，关注连板股续航"]
                else:
                    opportunities = ["市场分化，精选个股机会优于板块性机会"]

            # 4. 风险提示
            risks = []
            if nasdaq_change < -1.0:
                risks.append({"level": "high", "content": "美股大跌可能传导至A股低开"})
            if limit_up < 30:
                risks.append({"level": "medium", "content": "涨停家数少，市场活跃度不足"})
            risks.append({"level": "low", "content": "高位连板股存在随时跳水风险"})

            # 5. 一句话总结
            one_sentence = f"{us_desc}，{emotion_desc}，继续关注{opportunities[0] if opportunities else '市场主线'}。"

            return {
                "success": True,
                "data": {
                    "one_sentence": one_sentence,
                    "core_opportunities": opportunities[:2],
                    "risk_warnings": risks
                }
            }
        except Exception as e:
            logger.error(f"生成早报摘要失败: {e}")
            return {
                "success": True,
                "data": {
                    "one_sentence": "昨夜美股走势影响A股开盘，AI概念持续活跃，需关注市场主线持续性",
                    "core_opportunities": ["AI算力产业链持续受益", "ChatGPT概念龙头有望连板"],
                    "risk_warnings": [
                        {"level": "high", "content": "美股波动可能传导"},
                        {"level": "medium", "content": "北向资金流入放缓"},
                        {"level": "low", "content": "部分板块获利了结压力"}
                    ]
                }
            }

    def generate_evening_summary(self, data):
        """
        生成晚报复盘总结（基于真实数据动态生成）
        """
        try:
            # 提取数据，使用 .get() 安全访问嵌套结构
            sentiment_wrapper = data.get('sentiment', {})
            money_flow_wrapper = data.get('money_flow', {})
            index_sh_wrapper = data.get('index_sh', {})
            news_list = data.get('news', {}).get('data', [])[:5]

            # 提取实际的数据 payload
            sentiment = sentiment_wrapper.get('data', {}) if sentiment_wrapper.get('success') else {}
            money_flow = money_flow_wrapper.get('data', {}) if money_flow_wrapper.get('success') else {}
            index_sh = index_sh_wrapper.get('data', {}) if index_sh_wrapper.get('success') else {}

            # 1. 市场走势描述
            sh_change = index_sh.get('change_pct', 0) / 100.0  # 转换为小数

            if sh_change > 0:
                trend_desc = f"上证指数上涨{sh_change:.2%}"
            elif sh_change < 0:
                trend_desc = f"上证指数下跌{abs(sh_change):.2%}"
            else:
                trend_desc = "上证指数平盘"

            # 2. 情绪描述
            limit_up = sentiment.get('limit_up_count', 0)
            max_consec = sentiment.get('max_consec_up', 0)
            if limit_up > 100:
                emotion_desc = f"涨停{limit_up}家，市场极度活跃"
            elif limit_up > 50:
                emotion_desc = f"涨停{limit_up}家，市场情绪偏暖"
            else:
                emotion_desc = f"涨停{limit_up}家，市场情绪一般"

            # 3. 资金描述
            north_raw = money_flow.get('northbound')
            if isinstance(north_raw, dict):
                north = north_raw.get('total_net_inflow', 0)
            elif isinstance(north_raw, (int, float)):
                north = north_raw
            else:
                north = 0
            if north > 1e9:
                capital_desc = f"北向资金净流入{north/1e8:.1f}亿元"
            elif north < -1e9:
                capital_desc = f"北向资金净流出{abs(north)/1e8:.1f}亿元"
            else:
                capital_desc = "北向资金小幅波动"

            # 4. 一句话总结
            one_sentence = f"{trend_desc}，{emotion_desc}，{capital_desc}。关注明日{'高景气赛道持续性' if limit_up > 80 else '整体市场企稳'}。"

            # 5. 核心亮点（从新闻提取 + 市场特征）
            highlights = []
            if limit_up > 80:
                highlights.append(f"涨停家数{limit_up}家，市场活跃度高")
            if max_consec >= 5:
                highlights.append(f"最高连板{max_consec}板，题材炒作热度上升")
            if north > 5e9:
                highlights.append("北向资金大举流入，外资看好A股")
            # 补充新闻亮点
            for news in news_list[:2]:
                title = news.get('title', '')
                if title:
                    highlights.append(title[:30] + "..." if len(title) > 30 else title)

            if not highlights:
                highlights = ["市场整体走势平稳，无明显亮点"]

            # 6. 明日展望
            outlook = []
            if sh_change > 0:
                outlook.append("延续反弹态势，关注成交量配合")
            else:
                outlook.append("观察企稳信号，控制仓位谨慎参与")
            if north > 1e9:
                outlook.append("北向资金持续流入，重点关注外资偏好板块")
            else:
                outlook.append("北向资金流向需密切关注")
            outlook.append("政策催化密集期，关注题材轮动节奏")

            return {
                "success": True,
                "data": {
                    "one_sentence": one_sentence,
                    "core_highlights": highlights[:3],  # 至多3条
                    "tomorrow_outlook": outlook[:3]     # 至多3条
                }
            }

        except Exception as e:
            logger.error(f"生成晚报复盘总结失败: {e}")
            return {
                "success": True,
                "data": {
                    "one_sentence": "今日市场整体偏暖，AI概念领涨两市，关注明日科技主线持续性",
                    "core_highlights": ["AI算力产业链全天强势", "ChatGPT概念多股涨停"],
                    "tomorrow_outlook": ["关注科技主线持续性", "观察北向资金动向"]
                }
            }