"""
综合分析模块
负责大盘走势归因、主题追踪、策略调整和板块轮动分析
"""

from constants import SCORING_CONFIG, THEME_KEYWORDS
from utils import get_logger
from modules.analysis.news_classifier import NewsMapper

logger = get_logger('comprehensive_analyzer')


class ComprehensiveAnalyzer:
    """综合分析器：市场趋势、主题、策略、轮动"""

    def __init__(self, config, news_mapper):
        """
        初始化综合分析器

        Args:
            config: 配置字典
            news_mapper: NewsMapper 实例，用于新闻分类
        """
        self.config = config
        self.news_mapper = news_mapper
        logger.info("ComprehensiveAnalyzer 初始化完成")

    def analyze_comprehensive(self, data):
        """
        综合分析（大盘走势归因、量能、风格、展望）
        关联新闻事件 / 板块强弱 / 资金流向做真正的因果陈述，而非简单分档描述。
        """
        try:
            # --- 收集各项原始数据 ---
            overview = data.get('market_overview', {})
            overview_data = overview.get('data', {}) if overview.get('success') else {}

            sentiment_wrapper = data.get('sentiment', {})
            sentiment = sentiment_wrapper.get('data', {}) if sentiment_wrapper.get('success') else {}

            money_flow_wrapper = data.get('money_flow', {})
            money_flow = money_flow_wrapper.get('data', {}) if money_flow_wrapper.get('success') else {}

            sectors_wrapper = data.get('sectors', {})
            sectors_data = sectors_wrapper.get('data', {}) if sectors_wrapper.get('success') else {}
            top_sectors = sorted(
                sectors_data.get('industry', []),
                key=lambda x: x.get('change_pct', 0),
                reverse=True,
            )[:3]  # 今日涨幅前三行业

            news_list = data.get('news', {}).get('data', [])[:5]

            # 使用 NewsMapper 对新闻进行影响范围分类
            impact_classified = self.news_mapper.classify_news_by_impact(news_list)
            market_wide_news = impact_classified.get("market_wide", [])
            sector_specific_news = impact_classified.get("sector_specific", [])

            # --- 指数核心数据 ---
            index_sh_wrapper = data.get('index_sh', {})
            index_sh = index_sh_wrapper.get('data', {}) if index_sh_wrapper.get('success') else {}
            sh_change = index_sh.get('change_pct', 0)   # 百分比数值，如 1.23 表示 +1.23%

            # 北向资金
            north_raw = money_flow.get('northbound')
            if isinstance(north_raw, dict):
                north = north_raw.get('total_net_inflow', 0)
            elif isinstance(north_raw, (int, float)):
                north = north_raw
            else:
                north = 0

            # 成交额
            turnover = overview_data.get('turnover', 0)
            limit_up = sentiment.get('limit_up_count', 0)

            # -------------------------------------------------------
            # 1. 大盘走势归因（涨跌 + 关联最强板块 + 资金方向）
            # -------------------------------------------------------
            if sh_change > 1.0:
                trend_base = f"上证大涨{sh_change:.2f}%"
            elif sh_change > 0:
                trend_base = f"上证小幅上涨{sh_change:.2f}%"
            elif sh_change > -1.0:
                trend_base = f"上证小幅下跌{abs(sh_change):.2f}%"
            else:
                trend_base = f"上证大跌{abs(sh_change):.2f}%"

            # 关联驱动因素
            drivers = []
            if top_sectors:
                leaders = "、".join(s.get('sector', '') for s in top_sectors[:2] if s.get('sector'))
                if leaders:
                    drivers.append(f"{leaders}领涨")
            if north > 2e9:
                drivers.append(f"北向净流入{north/1e8:.1f}亿推动")
            elif north < -2e9:
                drivers.append(f"北向净流出{abs(north)/1e8:.1f}亿拖累")
            if limit_up > 100:
                drivers.append(f"涨停{limit_up}家市场情绪火热")
            elif limit_up < 30:
                drivers.append(f"涨停仅{limit_up}家情绪偏冷")

            # 关联新闻催化
            for news in news_list[:2]:
                title = news.get('title', '')
                importance = news.get('importance', 'medium')
                if importance == 'high' and title:
                    short = title[:25] + '…' if len(title) > 25 else title
                    drivers.append(f"受「{short}」消息提振" if sh_change > 0 else f"受「{short}」压制")
                    break

            if drivers:
                trend_judge = trend_base + "，" + "，".join(drivers[:3])
            else:
                trend_judge = trend_base

            # -------------------------------------------------------
            # 2. 量能归因（成交额 + 与涨跌关系）
            # -------------------------------------------------------
            if turnover > 1.2e12:
                vol_base = f"全市场成交{turnover/1e12:.2f}万亿，增量资金明显入场"
            elif turnover > 1e12:
                vol_base = f"全市场成交{turnover/1e12:.2f}万亿，市场交投活跃"
            elif turnover > 8e11:
                vol_base = f"全市场成交{turnover/1e12:.2f}万亿，量能温和"
            else:
                vol_base = f"全市场成交{turnover/1e12:.2f}万亿，缩量明显"

            # 量价关系判断
            if sh_change > 0 and turnover > 1e12:
                vol_note = "放量上涨，多头信号明确"
            elif sh_change > 0 and turnover <= 8e11:
                vol_note = "缩量上涨，上攻动能不足，需警惕假突破"
            elif sh_change < 0 and turnover > 1e12:
                vol_note = "放量下跌，空头压力较大"
            elif sh_change < 0 and turnover <= 8e11:
                vol_note = "缩量下跌，跌势可控，关注企稳信号"
            else:
                vol_note = "量价配合一般"

            volume_analysis = f"{vol_base}；{vol_note}"

            # -------------------------------------------------------
            # 3. 风格归因（基于涨幅前三行业 + 北向偏好）
            # -------------------------------------------------------
            if top_sectors:
                top_names = [s.get('sector', '') for s in top_sectors if s.get('sector')]
                avg_top_pct = sum(s.get('change_pct', 0) for s in top_sectors) / len(top_sectors)
                style_base = f"今日{'/'.join(top_names[:2])}领涨（均涨{avg_top_pct:.2f}%）"
                if avg_top_pct > 3:
                    style_note = "题材主线明确，板块效应显著"
                elif avg_top_pct > 1:
                    style_note = "市场风格分散，个股机会为主"
                else:
                    style_note = "板块普跌，防御板块相对抗跌"
                style_analysis = f"{style_base}，{style_note}"
            else:
                style_analysis = "板块数据暂缺，无法判断风格"

            # -------------------------------------------------------
            # 4. 后市展望（多维度综合）
            # -------------------------------------------------------
            score = overview_data.get('score', 50)
            outlook_parts = []

            if score >= 65:
                outlook_parts.append("情绪评分偏高，短线可积极参与主线")
            elif score >= 40:
                outlook_parts.append("情绪中性，精选个股，控制整体仓位")
            else:
                outlook_parts.append("情绪偏低，建议观望或防守配置")

            if north > 5e9:
                outlook_parts.append("外资持续流入，关注北向重仓板块")
            elif north < -5e9:
                outlook_parts.append("外资流出压力未消，谨慎追高")

            if top_sectors:
                top1 = top_sectors[0].get('sector', '')
                if top1:
                    outlook_parts.append(f"明日继续关注{top1}板块持续性")

            outlook = "；".join(outlook_parts) if outlook_parts else "市场整体中性，谨慎操作"

            return {
                "success": True,
                "data": {
                    "trend_judge": trend_judge,
                    "volume_analysis": volume_analysis,
                    "style_analysis": style_analysis,
                    "outlook": outlook,
                    "score": score,
                    "news_impact": {
                        "market_wide": market_wide_news,
                        "sector_specific": sector_specific_news
                    }
                }
            }

        except Exception as e:
            logger.error(f"综合分析失败: {e}")
            return {"success": False, "data": None, "error": str(e)}

    def analyze_theme_tracking(self, data):
        """
        主题投资追踪（算力、半导体、新能源、风电等）
        基于板块数据，识别预定义主题的表现
        """
        try:
            sectors_wrapper = data.get('sectors', {})
            sectors_data = sectors_wrapper.get('data', {}) if sectors_wrapper.get('success') else {}

            industry_sectors = sectors_data.get('industry', [])
            concept_sectors = sectors_data.get('concept', [])

            # 预定义主题关键词映射（来自 constants）
            theme_keywords = THEME_KEYWORDS

            # 收集相关板块
            theme_sectors = []
            all_sectors = industry_sectors + concept_sectors

            for theme_name, keywords in theme_keywords.items():
                matched_sectors = []
                for sector in all_sectors:
                    sector_name = sector.get('sector', '')
                    if any(keyword in sector_name for keyword in keywords):
                        matched_sectors.append(sector)

                if matched_sectors:
                    # 计算主题平均涨幅
                    avg_change = sum(s.get('change_pct', 0) for s in matched_sectors) / len(matched_sectors)
                    # 取涨幅最大的3个板块作为代表
                    top3 = sorted(matched_sectors, key=lambda x: x.get('change_pct', 0), reverse=True)[:3]

                    theme_sectors.append({
                        "theme": theme_name,
                        "avg_change_pct": round(avg_change, 2),
                        "sector_count": len(matched_sectors),
                        "top_sectors": [s.get('sector', '') for s in top3],
                        "top_leaders": [s.get('leaders', [{}])[0].get('name', '') if s.get('leaders') else '' for s in top3]
                    })

            # 按平均涨幅排序
            theme_sectors.sort(key=lambda x: x['avg_change_pct'], reverse=True)

            return {
                "success": True,
                "data": theme_sectors
            }

        except Exception as e:
            logger.error(f"主题投资追踪失败: {e}")
            return {"success": False, "data": None, "error": str(e)}

    def analyze_strategy_adjustment(self, data, morning_pred=None):
        """
        晚报分析：对比早报策略与今日实际，给出明日策略调整建议

        Args:
            data: 晚报数据
            morning_pred: 早报预测快照（从 prediction_store 读取），包含
                         {
                             "watchlist_data": [...],
                             "position_data": {...}
                         }

        Returns:
            {
                "success": True,
                "data": {
                    "original_strategy": str,    # 早报策略（如"进攻"）
                    "actual_performance": str,    # 今日实际市场表现（如"震荡走弱"）
                    "adjustment_needed": bool,   # 是否需要调整
                    "new_strategy": str,          # 建议明日策略（如"观望"）
                    "adjustment_reason": str,     # 调整原因
                    "position_adjustment": str,   # 仓位调整（如"50%→30%"）
                }
            }
        """
        try:
            # 1. 获取早报策略
            original_strategy = "中性"
            if morning_pred and 'position_data' in morning_pred:
                # 从早报仓位推导策略（向后兼容）
                position_data = morning_pred['position_data']
                position_min = position_data.get('position_min', 30)
                emotion_score = position_data.get('emotion_score', 50)

                if emotion_score >= 70 and position_min >= 50:
                    original_strategy = "进攻"
                elif emotion_score <= 30 and position_min <= 30:
                    original_strategy = "防守"
                else:
                    original_strategy = "中性"

            # 2. 获取今日实际表现
            sentiment_wrapper = data.get('sentiment', {})
            index_wrapper = data.get('index_sh', {})

            sentiment_data = sentiment_wrapper.get('data', {}) if sentiment_wrapper.get('success') else {}
            index_data = index_wrapper.get('data', {}) if index_wrapper.get('success') else {}

            # 上证涨跌幅
            sh_change = index_data.get('change_pct', 0) / 100.0  # 转为小数

            # 情绪分（晚报数据）
            money_flow_wrapper = data.get('money_flow', {})
            money_flow_data = money_flow_wrapper.get('data', {}) if money_flow_wrapper.get('success') else {}
            score = self._calc_emotion_score(sentiment_data, money_flow_data)

            # 3. 判断今日市场表现
            if sh_change > 1.0:
                performance = "强势上涨"
            elif sh_change > 0:
                performance = "震荡走强"
            elif sh_change > -1.0:
                performance = "震荡走弱"
            else:
                performance = "弱势下跌"

            # 4. 判断策略调整（基于规则表）
            adjustment_needed = False
            new_strategy = original_strategy
            reason = "市场符合预期，维持原策略"
            position_adjustment = "保持原仓位"

            # 规则表
            if original_strategy == "进攻":
                if sh_change < -0.01:  # sh_change < -1.0%
                    adjustment_needed = True
                    new_strategy = "观望"
                    reason = "早报误判，市场转弱"
                    position_adjustment = "大幅减仓或空仓"
                elif score < 40:
                    adjustment_needed = True
                    new_strategy = "中性"
                    reason = "情绪转冷，降低预期"
                    position_adjustment = "适度降低仓位"

            elif original_strategy == "防守":
                if sh_change > 0.01:  # sh_change > 1.0%
                    adjustment_needed = True
                    new_strategy = "中性"
                    reason = "市场转暖，可适度参与"
                    position_adjustment = "小幅加仓"
                elif score > 70:
                    adjustment_needed = True
                    new_strategy = "进攻"
                    reason = "情绪火热，积极做多"
                    position_adjustment = "积极加仓"

            elif original_strategy == "中性":
                if sh_change > 0.015:  # sh_change > 1.5%
                    adjustment_needed = True
                    new_strategy = "进攻"
                    reason = "突发利好，顺势而为"
                    position_adjustment = "加仓进攻"
                elif sh_change < -0.015:  # sh_change < -1.5%
                    adjustment_needed = True
                    new_strategy = "防守"
                    reason = "突发利空，果断减仓"
                    position_adjustment = "减仓防守"

            return {
                "success": True,
                "data": {
                    "original_strategy": original_strategy,
                    "actual_performance": performance,
                    "adjustment_needed": adjustment_needed,
                    "new_strategy": new_strategy,
                    "adjustment_reason": reason,
                    "position_adjustment": position_adjustment
                }
            }

        except Exception as e:
            logger.error(f"策略调整分析失败: {e}")
            return {
                "success": True,
                "data": {
                    "original_strategy": "中性",
                    "actual_performance": "未知",
                    "adjustment_needed": False,
                    "new_strategy": "中性",
                    "adjustment_reason": "分析失败，维持原策略",
                    "position_adjustment": "保持原仓位",
                    "error": str(e)
                }
            }

    def analyze_sector_rotation(self, data):
        """
        分析板块轮动趋势。
        需要历史板块数据（近5日）来计算切换频率。

        Args:
            data: 晚报数据，需包含 sectors_data（当日行业板块）和 sector_history（近5日历史）

        Returns:
            {
                "rotation_type": str,      # 轮动类型：'无轮动' / '快速切换' / '主线切换' / '结构分化'
                "rotation_strength": str,  # 轮动强度：'弱' / '中' / '强'
                "mainline_sector": str,    # 当前主线板块（涨幅TOP1）
                "mainline_change": str,    # 主线是否切换：'延续' / '新主线'
                "prev_mainline": str,      # 前一日主线
                "rotation_signal": str,    # 轮动信号描述
            }
        """
        try:
            # 获取当日板块数据
            sectors_wrapper = data.get('sectors', {})
            sectors_data = sectors_wrapper.get('data', {}) if isinstance(sectors_wrapper, dict) else {}

            industry_sectors = sectors_data.get('industry', [])
            if not industry_sectors:
                logger.warning("板块数据暂缺，无法分析轮动")
                return {
                    "success": True,
                    "data": {
                        "rotation_type": "无轮动",
                        "rotation_strength": "弱",
                        "mainline_sector": "-",
                        "mainline_change": "-",
                        "prev_mainline": "-",
                        "rotation_signal": "数据不足"
                    }
                }

            # 获取当日TOP1板块
            top1_today = industry_sectors[0] if industry_sectors else {}
            mainline_sector = top1_today.get('sector', '')
            mainline_change_today = top1_today.get('change_pct', 0)

            # 获取历史数据
            sector_history = data.get('sector_history', [])
            if not sector_history or len(sector_history) < 3:
                logger.info("历史数据不足，无法进行轮动分析")
                return {
                    "success": True,
                    "data": {
                        "rotation_type": "无轮动",
                        "rotation_strength": "弱",
                        "mainline_sector": mainline_sector or "-",
                        "mainline_change": "-",
                        "prev_mainline": "-",
                        "rotation_signal": "数据不足"
                    }
                }

            # 统计近5日TOP1板块出现频率
            top1_history = [h.get('top_sector', '') for h in sector_history]
            top1_counts = {}
            for sector in top1_history:
                top1_counts[sector] = top1_counts.get(sector, 0) + 1

            max_count = max(top1_counts.values()) if top1_counts else 0
            unique_top1 = len(top1_counts)

            # 判断轮动类型
            rotation_type = "无轮动"
            rotation_signal = ""

            # 近5日TOP1板块重复出现 >=3次
            if max_count >= 3:
                rotation_type = "无轮动"
                rotation_signal = f"{list(top1_counts.keys())[0]}为持续主线，资金聚焦"

            # 近5日TOP1板块每日不同
            elif unique_top1 >= 4:
                rotation_type = "快速切换"
                rotation_signal = "每日热点轮动，资金游击战明显"

            # 判断是否为主线切换
            prev_mainline = sector_history[0].get('top_sector', '') if sector_history else ''
            if prev_mainline and prev_mainline != mainline_sector:
                # 检查昨日主线是否跌出TOP3
                prev_top3_sectors = [s.get('sector', '') for s in industry_sectors[:3]]
                if prev_mainline not in prev_top3_sectors:
                    rotation_type = "主线切换"
                    rotation_signal = f"主线从{prev_mainline}切换至{mainline_sector}"
                else:
                    rotation_type = "结构分化"
                    rotation_signal = f"{prev_mainline}仍保持强势，资金分散"

            # TOP3板块涨幅差 < 1%
            elif len(industry_sectors) >= 3:
                top3_changes = [s.get('change_pct', 0) for s in industry_sectors[:3]]
                max_change = max(top3_changes) if top3_changes else 0
                min_change = min(top3_changes) if top3_changes else 0
                if max_change - min_change < 1:
                    rotation_type = "结构分化"
                    rotation_signal = "TOP3板块涨幅接近，齐涨齐跌"

            # 判断轮动强度（基于近5日TOP1平均涨幅）
            top1_changes = [h.get('top_change', 0) for h in sector_history if h.get('top_change') is not None]
            if top1_changes:
                avg_top1_change = sum(top1_changes) / len(top1_changes)
                if avg_top1_change > 3:
                    rotation_strength = "强"
                elif avg_top1_change > 1:
                    rotation_strength = "中"
                else:
                    rotation_strength = "弱"
            else:
                rotation_strength = "弱"

            # 判断主线是否切换
            if prev_mainline and prev_mainline == mainline_sector:
                mainline_change = "延续"
            elif prev_mainline:
                mainline_change = "新主线"
            else:
                mainline_change = "-"

            return {
                "success": True,
                "data": {
                    "rotation_type": rotation_type,
                    "rotation_strength": rotation_strength,
                    "mainline_sector": mainline_sector,
                    "mainline_change": mainline_change,
                    "prev_mainline": prev_mainline,
                    "rotation_signal": rotation_signal,
                }
            }

        except Exception as e:
            logger.error(f"板块轮动分析失败: {e}")
            return {
                "success": False,
                "data": None,
                "error": str(e)
            }

    def _calc_emotion_score(self, sentiment_data, money_flow_data):
        """
        计算市场情绪分数（0-100），权重由 constants.SCORING_CONFIG 定义
        """
        score = SCORING_CONFIG['base_score']

        limit_up = sentiment_data.get('limit_up_count', 0)
        score += min(
            SCORING_CONFIG['limit_up_max_score'],
            limit_up / SCORING_CONFIG['limit_up_per_point']
        )

        max_consec = sentiment_data.get('max_consec_up', 0)
        score += min(
            SCORING_CONFIG['consecutive_max_score'],
            max_consec * SCORING_CONFIG['consecutive_per_point']
        )

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

    def _get_volatility(self, index_data, history=None):
        """
        计算波动率代理。
        当提供历史数据（history）时，使用 ATR（平均真实波幅）计算更精确的波动率；
        否则退回到当日涨跌幅绝对值作为代理（向后兼容）。

        Args:
            index_data: 当日指数数据字典，包含 change_pct / high / low / close 等字段
            history: 可选，历史 K 线列表，每项为含 high / low / close 键的字典，
                     按时间升序排列（最新在末尾）

        Returns:
            float: 波动率，0-1 之间的小数（如 0.02 表示 2%）
        """
        # --- ATR 计算路径（需要至少 2 条历史记录）---
        if history and len(history) >= 2:
            N = 5  # 使用最近 5 日计算 ATR
            # 取最近 N+1 条（N 个 TR 需要 N+1 个收盘价）
            recent = history[-(N + 1):]
            true_ranges = []
            for i in range(1, len(recent)):
                high = float(recent[i].get('high', 0))
                low = float(recent[i].get('low', 0))
                prev_close = float(recent[i - 1].get('close', 0))
                if high == 0 or low == 0 or prev_close == 0:
                    continue
                tr = max(
                    high - low,
                    abs(high - prev_close),
                    abs(low - prev_close)
                )
                true_ranges.append(tr)
            if true_ranges:
                atr = sum(true_ranges) / len(true_ranges)
                # 当前价格取最后一条历史收盘价，避免除零
                current_price = float(recent[-1].get('close', 0))
                if current_price > 0:
                    return atr / current_price

        # --- 退化路径：使用当日涨跌幅绝对值（原逻辑，向后兼容）---
        change_pct = index_data.get('change_pct', 0)
        # 统一按"百分比数值"转换为小数（例如 0.63 -> 0.0063）
        change_pct = change_pct / 100.0
        return abs(change_pct)