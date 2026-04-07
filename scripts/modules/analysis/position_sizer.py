"""
仓位管理模块

基于凯利公式的动态仓位管理，结合市场情绪、波动率、最大回撤等因素
"""

from constants import SCORING_CONFIG
from utils import get_logger

logger = get_logger('position_sizer')


class PositionSizer:
    """
    动态仓位管理器

    基于凯利公式进行仓位建议，结合市场情绪、波动率、最大回撤等因素进行约束

    Attributes:
        _kelly_win_rate (float): 凯利公式胜率参数（默认0.5）
        _kelly_risk_reward (float): 凯利公式盈亏比参数（默认2.0）
        _kelly_half (bool): 是否启用半凯利模式（更保守）
    """

    def __init__(self, config):
        """
        初始化仓位管理器

        Args:
            config (dict): 配置字典，包含凯利公式参数
        """
        kelly_cfg = config.get('analysis', {}).get('kelly', {})
        self._kelly_win_rate = float(kelly_cfg.get('win_rate', 0.5))
        self._kelly_risk_reward = float(kelly_cfg.get('risk_reward_ratio', 2.0))
        self._kelly_half = bool(kelly_cfg.get('half_kelly', False))
        logger.info(
            f"PositionSizer 初始化完成 "
            f"(Kelly: p={self._kelly_win_rate}, b={self._kelly_risk_reward}, "
            f"half={self._kelly_half})"
        )

    def suggest_position(self, data):
        """
        动态仓位管理（凯利公式增强版）
        公式: f* = (p × b - (1-p)) / b
        结合情绪分和波动率进行约束

        Args:
            data (dict): 完整数据字典，包含以下字段：
                - sentiment: 市场情绪数据
                - money_flow: 资金流向数据
                - index_sh: 上证指数数据
                - index_history: 指数历史数据（可选）
                - max_drawdown: 最大回撤（可选）

        Returns:
            dict: {
                "success": True,
                "data": {
                    "position_min": float,      # 最小仓位（%）
                    "position_max": float,      # 最大仓位（%）
                    "position_suggestion": str, # 仓位建议字符串
                    "logic": str,               # 计算逻辑说明
                    "emotion_score": float,     # 情绪分
                    "volatility": float,        # 波动率
                    "kelly_fraction": float,    # 凯利公式结果
                    "win_rate": float,          # 胜率
                    "risk_reward_ratio": float  # 盈亏比
                }
            }
        """
        try:
            # 1. 提取数据
            sentiment_wrapper = data.get('sentiment', {})
            money_flow_wrapper = data.get('money_flow', {})
            index_wrapper = data.get('index_sh', {})

            sentiment = sentiment_wrapper.get('data', {}) if sentiment_wrapper.get('success') else {}
            index_data = index_wrapper.get('data', {}) if index_wrapper.get('success') else {}
            money_flow = money_flow_wrapper.get('data', {}) if money_flow_wrapper.get('success') else {}

            # 2. 计算情绪分
            emotion_score = self._calc_emotion_score(sentiment, money_flow)

            # 3. 计算波动率（优先使用历史数据计算 ATR，无历史数据退化为当日涨跌幅）
            index_history = data.get('index_history', [])
            volatility = self._get_volatility(index_data, history=index_history if index_history else None)

            # 3b. 获取最大回撤（若有，用于仓位折减）
            max_drawdown = data.get('max_drawdown')  # 期望为小数，如 0.15 表示 15%

            # 4. 获取凯利参数（优先使用配置值）
            p = self._kelly_win_rate
            b = self._kelly_risk_reward

            # 5. 计算凯利仓位（传入最大回撤用于折减控制）
            kelly_result = self._calculate_kelly_position(
                p=p,
                b=b,
                emotion_score=emotion_score,
                volatility=volatility,
                max_drawdown=max_drawdown
            )

            # 6. 半凯利模式：仓位上限减半（更保守）
            if self._kelly_half:
                kelly_result['adjusted_max'] = round(kelly_result['adjusted_max'] * 0.5)
                kelly_result['adjusted_min'] = round(min(kelly_result['adjusted_min'], kelly_result['adjusted_max']))
                kelly_result['logic'] += "（半凯利模式）"

            return {
                "success": True,
                "data": {
                    "position_min": kelly_result['adjusted_min'],
                    "position_max": kelly_result['adjusted_max'],
                    "position_suggestion": f"{kelly_result['adjusted_min']}%-{kelly_result['adjusted_max']}%",
                    "logic": kelly_result['logic'],
                    "emotion_score": round(emotion_score),
                    "volatility": round(volatility, 4),
                    "kelly_fraction": kelly_result['kelly_fraction'],
                    "win_rate": p,
                    "risk_reward_ratio": b
                }
            }

        except Exception as e:
            logger.error(f"动态仓位计算失败: {e}")
            return {
                "success": True,
                "data": {
                    "position_min": 30,
                    "position_max": 50,
                    "position_suggestion": "30%-50%",
                    "logic": "计算失败，使用保守预设",
                    "error": str(e)
                }
            }

    def suggest_position_with_risk_plan(self, data, north=None, turnover=None, sh_change=None, volatility=None, us_nasdaq_change=None):
        """
        带风险预案的动态仓位建议（增强版 suggest_position）
        返回基础仓位信息 + 风险场景和对冲建议

        Args:
            data (dict): 完整数据字典（用于基础仓位计算）
            north (float): 北向资金净流入（可选，从 data 自动提取）
            turnover (float): 市场成交额（可选，从 data 自动提取）
            sh_change (float): 上证涨跌幅（可选，从 data 自动提取）
            volatility (float): 波动率（可选，从 data 自动提取）
            us_nasdaq_change (float): 纳斯达克涨跌幅（可选，从 data 自动提取）

        Returns:
            dict: {
                "success": True,
                "data": {
                    "position_min": float,
                    "position_max": float,
                    "position_suggestion": str,
                    "logic": str,
                    "emotion_score": float,
                    "volatility": float,
                    "kelly_fraction": float,
                    "win_rate": float,
                    "risk_reward_ratio": float,
                    "risk_scenarios": [  # 新增风险场景
                        {
                            "scenario": str,
                            "probability": str,  # "高"/"中"/"低"
                            "hedge": str,
                            "hedge_timing": str
                        },
                        ...
                    ],
                    "risk_summary": str,  # 新增风险总结
                }
            }
        """
        try:
            # 1. 复用 suggest_position 计算基础仓位
            base_position = self.suggest_position(data)
            if not base_position.get('success'):
                raise Exception('基础仓位计算失败')

            pos_data = base_position['data']

            # 2. 提取/补全风险分析所需指标
            sentiment_wrapper = data.get('sentiment', {})
            money_flow_wrapper = data.get('money_flow', {})
            index_wrapper = data.get('index_sh', {})
            us_market = data.get('us_market', {})

            sentiment = sentiment_wrapper.get('data', {}) if sentiment_wrapper.get('success') else {}
            index_data = index_wrapper.get('data', {}) if index_wrapper.get('success') else {}
            money_flow_data = money_flow_wrapper.get('data', {}) if money_flow_wrapper.get('success') else {}

            # 北向资金
            if north is None:
                north_raw = money_flow_data.get('northbound')
                if isinstance(north_raw, dict):
                    north = north_raw.get('total_net_inflow', 0)
                elif isinstance(north_raw, (int, float)):
                    north = north_raw
                else:
                    north = 0

            # 成交额
            if turnover is None:
                overview_wrapper = data.get('market_overview', {})
                overview_data = overview_wrapper.get('data', overview_wrapper) if isinstance(overview_wrapper, dict) else {}
                turnover = overview_data.get('turnover', 0)

            # 上证涨跌幅（转为小数）
            if sh_change is None:
                sh_change_pct = index_data.get('change_pct', 0)  # 百分比数值，如 1.23
                sh_change = sh_change_pct / 100.0 if sh_change_pct else 0

            # 波动率
            if volatility is None:
                index_history = data.get('index_history', [])
                volatility = self._get_volatility(index_data, history=index_history if index_history else None)

            # 美股纳指涨跌幅（转为小数）
            if us_nasdaq_change is None:
                us_nasdaq_change = us_market.get('nasdaq_change_pct', 0) / 100.0

            # 情绪分
            emotion_score = pos_data.get('emotion_score', self._calc_emotion_score(sentiment, money_flow_data))

            # 3. 构建风险场景（硬编码规则）
            risk_scenarios = []

            # 场景1: 北向大幅流出
            if north < -5e9:
                risk_scenarios.append({
                    "scenario": "北向资金大幅流出",
                    "probability": "高",
                    "hedge": "减仓至20%，观察量能变化",
                    "hedge_timing": "今日盘中"
                })

            # 场景2: 缩量上涨虚高
            if sh_change > 0 and turnover < 8e11:
                risk_scenarios.append({
                    "scenario": "缩量上涨，上涨放量不足",
                    "probability": "中",
                    "hedge": "高开不追高，午后考虑减仓",
                    "hedge_timing": "开盘后1小时"
                })

            # 场景3: 情绪转冷
            if emotion_score < 35:
                risk_scenarios.append({
                    "scenario": "市场情绪低迷",
                    "probability": "中",
                    "hedge": "轻仓观望或空仓",
                    "hedge_timing": "当日"
                })

            # 场景4: 波动率过高
            if volatility > 0.03:
                risk_scenarios.append({
                    "scenario": "市场波动率过高",
                    "probability": "高",
                    "hedge": "降低仓位至30%，设置止损",
                    "hedge_timing": "立即"
                })

            # 场景5: 美股暴跌传导
            if us_nasdaq_change < -0.02:
                risk_scenarios.append({
                    "scenario": "美股暴跌传导风险",
                    "probability": "低",
                    "hedge": "低开观望，不追跌",
                    "hedge_timing": "明日"
                })

            # 4. 生成风险总结
            if risk_scenarios:
                # 按概率排序（高 > 中 > 低）
                prob_order = {"高": 0, "中": 1, "低": 2}
                risk_scenarios.sort(key=lambda x: prob_order.get(x["probability"], 99))

                top_risks = [s["scenario"] for s in risk_scenarios[:2]]
                if len(top_risks) == 1:
                    risk_desc = top_risks[0]
                elif len(top_risks) == 2:
                    risk_desc = f"{top_risks[0]}、{top_risks[1]}"
                else:
                    risk_desc = "、".join(top_risks)

                risk_summary = f"当前主要风险：{risk_desc}，建议严格执行对冲策略"
            else:
                risk_summary = "当前市场风险可控，正常操作"

            # 5. 合并结果
            pos_data["risk_scenarios"] = risk_scenarios
            pos_data["risk_summary"] = risk_summary

            return {
                "success": True,
                "data": pos_data
            }

        except Exception as e:
            logger.error(f"带风险预案的仓位计算失败: {e}")
            # 降级：返回基础仓位结果（不带风险预案）
            base_position = self.suggest_position(data)
            if base_position.get('success'):
                pos_data = base_position['data']
                pos_data["risk_scenarios"] = []
                pos_data["risk_summary"] = "风险预案生成失败，请谨慎操作"
                return {
                    "success": True,
                    "data": pos_data
                }
            # 完全失败场景
            return {
                "success": True,
                "data": {
                    "position_min": 30,
                    "position_max": 50,
                    "position_suggestion": "30%-50%",
                    "logic": "计算失败，使用保守预设",
                    "emotion_score": 50,
                    "volatility": 0.01,
                    "kelly_fraction": 0.125,
                    "win_rate": 0.5,
                    "risk_reward_ratio": 2.0,
                    "risk_scenarios": [],
                    "risk_summary": "计算失败，建议谨慎操作",
                    "error": str(e)
                }
            }

    def _calculate_kelly_position(self, p, b, emotion_score=None, volatility=None, max_drawdown=None):
        """
        计算凯利公式最优仓位

        Args:
            p (float): 胜率（0-1小数）
            b (float): 盈亏比（赢时收益/输时损失）
            emotion_score (float): 情绪分（0-100），可选，用于约束上限
            volatility (float): 波动率（小数），可选，用于约束上限
            max_drawdown (float): 最大回撤（小数，如 0.15 表示 15%），可选，
                                 超过阈值时对仓位上限进行折减

        Returns:
            dict: {
                'kelly_fraction': float,  # 凯利公式结果（0-1）
                'adjusted_min': float,     # 调整后最小仓位（%）
                'adjusted_max': float,     # 调整后最大仓位（%）
                'logic': str              # 计算逻辑说明
            }
        """
        # 凯利公式
        f_star = (p * b - (1 - p)) / b if b > 0 else 0
        f_star = max(0, min(1, f_star))  # 限制在 [0,1]

        # 基础仓位区间（凯利±20%）
        base_min = max(10, f_star * 100 * 0.8)
        base_max = min(70, f_star * 100 * 1.2)

        # 情绪分约束（情绪越激动仓位越高）
        if emotion_score is not None:
            emotion_cap = 30 + (emotion_score / 100) * 40  # 30%-70%
            base_min = max(base_min, emotion_cap * 0.8)
            base_max = min(base_max, emotion_cap * 1.2)

        # 波动率约束（波动越大仓位越低）
        if volatility is not None:
            vol_penalty = volatility * 500  # 经验系数
            base_min = max(10, base_min - vol_penalty)
            base_max = min(70, base_max + vol_penalty * 0.2)

        # 最大回撤控制因子（回撤越深，仓位上限折减越多）
        drawdown_note = ""
        if max_drawdown is not None:
            drawdown_pct = abs(max_drawdown)  # 统一为正值
            if drawdown_pct > 0.30:
                # 回撤超过 30%：仓位上限折减 60%
                base_max = base_max * 0.4
                drawdown_note = f"，最大回撤{drawdown_pct*100:.1f}%（>30%）上限折减60%"
            elif drawdown_pct > 0.20:
                # 回撤超过 20%：仓位上限折减 40%
                base_max = base_max * 0.6
                drawdown_note = f"，最大回撤{drawdown_pct*100:.1f}%（>20%）上限折减40%"
            elif drawdown_pct > 0.10:
                # 回撤超过 10%：仓位上限折减 20%
                base_max = base_max * 0.8
                drawdown_note = f"，最大回撤{drawdown_pct*100:.1f}%（>10%）上限折减20%"

        # 确保 min <= max
        if base_min > base_max:
            base_min, base_max = base_max, base_min

        logic = f"凯利公式: f*=(p×b-q)/b={p:.2f}×{b:.2f}-{1-p:.2f})/{b:.2f}={f_star:.2f}"
        if emotion_score is not None:
            logic += f"，情绪{emotion_score:.0f}分约束30%-70%"
        if volatility is not None:
            logic += f"，波动{volatility*100:.2f}%惩罚"
        logic += drawdown_note

        return {
            'kelly_fraction': round(f_star, 4),
            'adjusted_min': round(base_min),
            'adjusted_max': round(base_max),
            'logic': logic
        }

    def _get_volatility(self, index_data, history=None):
        """
        计算波动率代理。
        当提供历史数据（history）时，使用 ATR（平均真实波幅）计算更精确的波动率；
        否则退回到当日涨跌幅绝对值作为代理（向后兼容）。

        Args:
            index_data (dict): 当日指数数据字典，包含 change_pct / high / low / close 等字段
            history (list): 可选，历史 K 线列表，每项为含 high / low / close 键的字典，
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

    def _calc_emotion_score(self, sentiment_data, money_flow_data):
        """
        计算市场情绪分数（0-100），权重由 constants.SCORING_CONFIG 定义

        Args:
            sentiment_data (dict): 市场情绪数据，包含：
                - limit_up_count: 涨停板数量
                - max_consec_up: 最大连续涨停天数
            money_flow_data (dict): 资金流向数据，包含：
                - northbound: 北向资金数据（字典或数值）

        Returns:
            float: 情绪分数（0-100）
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