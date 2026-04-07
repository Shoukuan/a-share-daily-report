"""
Technical Indicators Module
技术指标分析模块
"""

import sys
import os

# Add parent directories to path for utils import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from utils import get_logger

logger = get_logger('technical_indicators')


class TechnicalIndicators:
    """Technical Indicators Analysis Class
    技术指标分析类
    """

    def __init__(self, config):
        """Initialize with configuration"""
        self.config = config
        logger.info("TechnicalIndicators 初始化完成")

    def analyze_technical_analysis(self, data):
        """
        技术面分析（RSI、MACD、支撑阻力）
        基于指数日线数据计算。
        当 data 中包含 index_history 时，计算真实的 RSI(14)、
        5 日支撑位（最低点）和 5 日阻力位（最高点）；
        否则退化为基于当日涨跌幅的简单估算（向后兼容）。
        """
        try:
            index_sh_wrapper = data.get('index_sh', {})
            index_sh = index_sh_wrapper.get('data', {}) if index_sh_wrapper.get('success') else {}

            if not index_sh:
                return {"success": False, "data": None, "error": "无法获取上证指数数据"}

            change_pct = index_sh.get('change_pct', 0)

            # --- 尝试使用历史数据计算精确技术指标 ---
            index_history = data.get('index_history', [])
            rsi_value = None
            support = None
            resistance = None

            if index_history and len(index_history) >= 2:
                # 1. 计算真实 RSI（14 日）
                # 需要至少 15 条数据（14 个变化值）；数据不足时跳过
                RSI_PERIOD = 14
                closes = [float(bar.get('close', 0)) for bar in index_history if bar.get('close')]
                if len(closes) >= RSI_PERIOD + 1:
                    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
                    # 取最近 RSI_PERIOD 个变化
                    recent_changes = changes[-RSI_PERIOD:]
                    gains = [c for c in recent_changes if c > 0]
                    losses = [abs(c) for c in recent_changes if c < 0]
                    avg_gain = sum(gains) / RSI_PERIOD
                    avg_loss = sum(losses) / RSI_PERIOD
                    if avg_loss == 0:
                        rsi_value = 100.0
                    else:
                        rs = avg_gain / avg_loss
                        rsi_value = round(100 - 100 / (1 + rs), 2)

                # 2. 计算 5 日支撑位（最近 5 日最低点）和阻力位（最近 5 日最高点）
                WINDOW = 5
                recent_bars = index_history[-WINDOW:]
                lows = [float(bar.get('low', 0)) for bar in recent_bars if bar.get('low')]
                highs = [float(bar.get('high', 0)) for bar in recent_bars if bar.get('high')]
                if lows:
                    support = round(min(lows), 2)
                if highs:
                    resistance = round(max(highs), 2)

            # --- 退化路径：当日涨跌幅简单判断 ---
            if rsi_value is None:
                # 无历史数据时保留原粗略估算逻辑
                rsi_value = round(50 + change_pct * 5, 2)

            if support is None:
                support = round(index_sh.get('low', 0), 2)   # 日内最低作为支撑

            if resistance is None:
                resistance = round(index_sh.get('high', 0), 2)  # 日内最高作为阻力

            # RSI 状态判断
            if rsi_value >= 70:
                rsi_status = "超买"
            elif rsi_value <= 30:
                rsi_status = "超卖"
            else:
                rsi_status = "中性"

            # MACD 信号和趋势强度（仍基于当日涨跌幅，未来可扩展为真实 MACD）
            if change_pct > 2:
                macd_signal = "多头"
                trend_strength = "强"
            elif change_pct > 0:
                macd_signal = "中性"
                trend_strength = "中等"
            elif change_pct > -2:
                macd_signal = "中性"
                trend_strength = "弱"
            else:
                macd_signal = "空头"
                trend_strength = "弱"

            return {
                "success": True,
                "data": {
                    "index_name": "上证指数",
                    "change_pct": change_pct,
                    "rsi": rsi_value,
                    "rsi_status": rsi_status,
                    "macd_signal": macd_signal,
                    "trend_strength": trend_strength,
                    "support": support,
                    "resistance": resistance
                }
            }

        except Exception as e:
            logger.error(f"技术面分析失败: {e}")
            return {"success": False, "data": None, "error": str(e)}

    def _calculate_kelly_position(self, p, b, emotion_score=None, volatility=None, max_drawdown=None):
        """
        计算凯利公式最优仓位

        Args:
            p: 胜率（0-1小数）
            b: 盈亏比（赢时收益/输时损失）
            emotion_score: 情绪分（0-100），可选，用于约束上限
            volatility: 波动率（小数），可选，用于约束上限
            max_drawdown: 最大回撤（小数，如 0.15 表示 15%），可选，
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