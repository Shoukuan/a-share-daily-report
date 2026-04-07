"""
Watchlist analysis module
"""

from utils import get_logger

logger = get_logger('watchlist_analyzer')


class WatchlistAnalyzer:
    """Watchlist analysis for morning and evening reports"""

    def __init__(self, config, watchlist, news_mapper):
        """
        Initialize WatchlistAnalyzer

        Args:
            config: Configuration dictionary
            watchlist: List of watchlist stocks
            news_mapper: NewsMapper instance for news mapping
        """
        self.config = config
        self.watchlist = watchlist
        self.news_mapper = news_mapper

    def _find_related_news_for_stock(self, code, name, news_list):
        """
        查找与股票相关的新闻
        返回前3条相关新闻标题
        """
        try:
            related_news = []
            code_search = code.split('.')[0]  # 处理带交易所后缀的代码

            for news in news_list[:50]:  # 只搜索前50条新闻以提高性能
                title = news.get('title', '')
                # 检查新闻标题是否包含股票代码或名称
                if code_search in title or name in title:
                    related_news.append(title)
                    if len(related_news) >= 3:
                        break

            return related_news
        except Exception as e:
            logger.warning(f"查找 {name}({code}) 相关新闻时出错: {e}")
            return []

    def analyze_watchlist_morning(self, data):
        """
        早报自选股预测：基于昨日真实行情 + 技术分析生成预判
        data 中应包含 watchlist_performance（由 generate_report 注入）
        新增：置信度评估、盘口量比分析、北向资金、新闻关联
        """
        results = []
        watchlist_performance = data.get('watchlist_performance', [])

        # 构建 code→data 映射
        perf_map = {p.get('code', '').split('.')[0]: p for p in watchlist_performance}

        # 获取新闻列表
        news_list = data.get('news', {}).get('data', [])

        # 获取北向资金持仓变动（可选）
        northbound_holdings = data.get('northbound_holdings', {})

        for stock in self.watchlist:
            code_raw = stock.get('code', '')
            name = stock.get('name', '')
            ak_code = code_raw.split('.')[0]

            perf = perf_map.get(ak_code)
            if perf and perf.get('change_pct') is not None:
                pct = perf.get('change_pct', 0)
                price = perf.get('price', 0)
                volume_ratio = perf.get('volume_ratio', 1.0)
                ma5 = perf.get('ma5', 0)
                ma20 = perf.get('ma20', 0)

                # 技术判断
                trend = ""
                if ma5 and ma20:
                    if price > ma5 > ma20:
                        trend = "均线多头排列"
                    elif price < ma5 < ma20:
                        trend = "均线空头排列"
                    elif price > ma20:
                        trend = "站上20日均线"
                    else:
                        trend = "位于20日均线下方"

                # 生成预判
                if pct >= 5:
                    view = "看涨"
                    reason = f"昨日强势涨停/大涨{pct:.1f}%，{trend}，今日关注高开承接力度"
                elif pct >= 2:
                    view = "偏多"
                    reason = f"昨日上涨{pct:.1f}%，{trend}，今日关注量价配合"
                elif pct >= 0:
                    view = "震荡偏多"
                    reason = f"昨日微涨{pct:.1f}%，{trend}，短期维持强势震荡"
                elif pct >= -2:
                    view = "震荡"
                    reason = f"昨日小跌{abs(pct):.1f}%，{trend}，关注支撑位企稳"
                elif pct >= -5:
                    view = "偏空"
                    reason = f"昨日下跌{abs(pct):.1f}%，{trend}，注意止损位"
                else:
                    view = "看跌"
                    reason = f"昨日大跌{abs(pct):.1f}%，{trend}，短期回避"

                # 盘口量比分析
                if volume_ratio:
                    if volume_ratio >= 2.5:
                        reason += f"，放量突破（量比{volume_ratio:.1f}）"
                    elif volume_ratio <= 0.5:
                        reason += f"，缩量调整（量比{volume_ratio:.1f}）"
                    elif volume_ratio >= 2.0:
                        reason += f"，量比{volume_ratio:.1f}倍放量"

                # 北向资金持仓变动
                try:
                    nb_change = northbound_holdings.get(ak_code, 0)
                    if nb_change > 0 and nb_change >= 1.0:
                        reason += f"，北向增持{nb_change:.1f}%"
                    elif nb_change < 0 and abs(nb_change) >= 1.0:
                        reason += f"，北向减持{abs(nb_change):.1f}%"
                except Exception:
                    pass  # 北向数据不存在时跳过

                # 新闻标的关联
                try:
                    related_news = self._find_related_news_for_stock(code_raw, name, news_list)
                    if related_news:
                        reason += f"，受「{related_news[0][:30]}...」提振"
                except Exception as e:
                    logger.debug(f"关联新闻失败 {name}: {e}")

                # 置信度计算
                confidence = 0.5  # 基础置信度
                confidence_notes = []

                try:
                    # 均线多头排列 +0.20
                    if ma5 and ma20 and price > ma5 > ma20:
                        confidence += 0.20
                        confidence_notes.append("均线多头")

                    # 昨日涨幅 ≥ 5% +0.15
                    if pct >= 5:
                        confidence += 0.15
                        confidence_notes.append("昨日强势")

                    # 量比 ≥ 2.0 +0.10
                    if volume_ratio and volume_ratio >= 2.0:
                        confidence += 0.10
                        confidence_notes.append("放量")

                    # 有相关新闻 +0.15
                    try:
                        if self._find_related_news_for_stock(code_raw, name, news_list):
                            confidence += 0.15
                            confidence_notes.append("新闻催化")
                    except Exception:
                        pass

                    # 北向增持 ≥ 1% +0.10
                    try:
                        nb_change = northbound_holdings.get(ak_code, 0)
                        if nb_change >= 1.0:
                            confidence += 0.10
                            confidence_notes.append("北向增持")
                    except Exception:
                        pass

                    # 昨日跌幅 ≤ -5% -0.20
                    if pct <= -5:
                        confidence -= 0.20
                        confidence_notes.append("昨日大跌")

                    # 均线空头排列 -0.20
                    if ma5 and ma20 and price < ma5 < ma20:
                        confidence -= 0.20
                        confidence_notes.append("均线空头")

                    # 量比 ≤ 0.5 -0.10
                    if volume_ratio and volume_ratio <= 0.5:
                        confidence -= 0.10
                        confidence_notes.append("缩量")

                    # 无任何信号 -0.10
                    if pct >= -2 and pct <= 2 and (not ma5 or not ma20 or ma5 <= price <= ma20):
                        confidence -= 0.10
                        confidence_notes.append("信号模糊")

                except Exception as e:
                    logger.debug(f"置信度计算失败 {name}: {e}")

                # 限制置信度范围 [0, 1]
                confidence = max(0.0, min(1.0, confidence))

                # 生成置信度说明
                if confidence_notes:
                    confidence_note = "、".join(confidence_notes[:3])
                    if len(confidence_notes) > 3:
                        confidence_note += "等"
                else:
                    confidence_note = "技术面中性"

                results.append({
                    "code": code_raw,
                    "name": name,
                    "view": view,
                    "reason": reason,
                    "change_pct": pct,
                    "price": price,
                    "confidence": round(confidence, 2),
                    "confidence_note": confidence_note
                })
            else:
                # 无实时数据时退回简要描述
                results.append({
                    "code": code_raw,
                    "name": name,
                    "view": "待定",
                    "reason": f"{name}行情数据暂缺，开盘后观察走势",
                    "change_pct": 0.0,
                    "price": 0.0,
                    "confidence": 0.0,
                    "confidence_note": "数据缺失"
                })

        return {"success": True, "data": results}

    def get_watchlist_news_mapping(self, data):
        """
        获取自选股的新闻映射信息。

        Args:
            data: 包含新闻数据的字典

        Returns:
            {
                "success": True,
                "data": {
                    "stock_news_map": {
                        "股票名称": ["新闻标题1", "新闻标题2", ...],
                        ...
                    }
                }
            }
        """
        try:
            news_list = data.get('news', {}).get('data', [])

            if not news_list:
                return {"success": True, "data": {"stock_news_map": {}}}

            # 使用 NewsMapper 映射新闻到自选股
            related_news = self.news_mapper.map_news_to_stocks(news_list, self.watchlist)

            return {"success": True, "data": {"stock_news_map": related_news}}
        except Exception as e:
            logger.error(f"获取自选股新闻映射失败: {e}")
            return {"success": True, "data": {"stock_news_map": {}}}

    def analyze_watchlist_evening(self, data):
        """
        分析自选股表现（基于真实行情数据）
        需要从 data 中获取自选股当日涨跌幅
        """
        try:
            logger.debug(f"[DEBUG] analyze_watchlist_evening 收到 data 类型: {type(data)}")
            # 从 data 中获取自选股行情（应该由 generate_report 注入）
            watchlist_performance = data.get('watchlist_performance', [])

            if not watchlist_performance:
                # 没有真实数据时返回空，不模拟
                return {
                    "success": True,
                    "data": {
                        "overall": {"up_count": 0, "down_count": 0, "avg_return": 0.0},
                        "best": None,
                        "worst": None,
                        "tomorrow_strategy": "等待数据更新"
                    }
                }

            # 统计
            up_count = sum(1 for s in watchlist_performance if s.get('change_pct', 0) > 0)
            down_count = len(watchlist_performance) - up_count
            avg_return = sum(s.get('change_pct', 0) for s in watchlist_performance) / len(watchlist_performance) if watchlist_performance else 0

            # 找出最佳和最差
            best = max(watchlist_performance, key=lambda x: x.get('change_pct', 0)) if watchlist_performance else None
            worst = min(watchlist_performance, key=lambda x: x.get('change_pct', 0)) if watchlist_performance else None

            # 构建 best/worst 数据
            best_data = None
            if best:
                best_data = {
                    "code": best.get('code'),
                    "name": best.get('name'),
                    "change_pct": best.get('change_pct', 0),
                    "reason": self._get_performance_reason(best.get('change_pct', 0))
                }

            worst_data = None
            if worst:
                worst_data = {
                    "code": worst.get('code'),
                    "name": worst.get('name'),
                    "change_pct": worst.get('change_pct', 0),
                    "reason": self._get_performance_reason(worst.get('change_pct', 0))
                }

            # 生成策略
            strategy = self._generate_watchlist_strategy(watchlist_performance)

            return {
                "success": True,
                "data": {
                    "overall": {
                        "up_count": up_count,
                        "down_count": down_count,
                        "avg_return": round(avg_return, 2)
                    },
                    "best": best_data,
                    "worst": worst_data,
                    "tomorrow_strategy": strategy,
                    "stocks": watchlist_performance
                }
            }
        except Exception as e:
            logger.error(f"分析自选股表现失败: {e}")
            logger.debug(f"调试 - watchlist_performance={watchlist_performance}, watchlist={self.watchlist}")
            return {
                "success": True,
                "data": {
                    "overall": {"up_count": 0, "down_count": 0, "avg_return": 0.0},
                    "best": None,
                    "worst": None,
                    "tomorrow_strategy": "数据异常，请检查",
                    "stocks": []
                }
            }

    def _get_performance_reason(self, change_pct):
        """根据涨跌幅给出表现描述"""
        if change_pct >= 5:
            return "强势涨停，表现活跃"
        elif change_pct > 0:
            return "小幅上涨，走势稳健"
        elif change_pct > -3:
            return "小幅回调，暂时盘整"
        else:
            return "调整较大的个股"

    def _generate_watchlist_strategy(self, performance_list):
        """基于自选股整体表现生成明日策略"""
        avg_return = sum(s.get('change_pct', 0) for s in performance_list) / len(performance_list) if performance_list else 0
        up_ratio = sum(1 for s in performance_list if s.get('change_pct', 0) > 0) / len(performance_list) if performance_list else 0

        if avg_return > 2 and up_ratio > 0.6:
            return "自选股整体走强，可继续持有多头头寸"
        elif avg_return < -2 and up_ratio < 0.4:
            return "自选股普遍调整，建议减仓观望"
        else:
            return "自选股表现分化，个股操作为主"
