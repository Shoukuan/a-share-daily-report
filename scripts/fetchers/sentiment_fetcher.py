
"""
DataFetcher mixin submodule
"""

import os
import urllib.request
import requests
import pandas as pd
from dataclasses import asdict
from datetime import datetime, date, timedelta
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

from constants import INDEX_NAMES, YFINANCE_INDEX_MAP, ALL_INDICES, TIMEOUTS, RETRY_POLICY, CACHE_TTL_CONFIG
from international_event_rules import (
    classify_event_category,
    judge_impact_level,
    generate_a_share_impact,
    get_affected_sectors as infer_affected_sectors,
    get_a_share_impact_sectors as infer_a_share_impact_sectors,
)
from models import IndexData, NewsItem, FuturesItem
from utils import (
    get_cache,
    set_cache,
    get_logger,
    log_event,
    format_date,
    parse_date,
    safe_int,
    load_project_env,
    post_json_with_retry,
)
from schemas import MarketSentimentSchema, validate_schema

logger = get_logger('data_fetcher')

class SentimentFetcherMixin:
    def get_market_sentiment(self, dt, index_cache=None):
        date_str = format_date(dt)
        cache_key = f'sentiment_{date_str}'
        ttl = CACHE_TTL_CONFIG.get('market_sentiment', 300)
        cached = get_cache(cache_key, namespace='akshare', ttl=ttl)
        if cached is not None:
            return {"success": True, "data": cached, "source": "cache", "cached": True}

        if self.ak:
            try:
                ak_date = parse_date(date_str).strftime('%Y%m%d')
                limit_up_df = self.ak.stock_zt_pool_em(date=ak_date)
                limit_up_count = len(limit_up_df) if (limit_up_df is not None and hasattr(limit_up_df, '__len__')) else 0

                # 计算最高连板数（如果有'连板数'字段）
                max_consec_up = 0
                if limit_up_df is not None and hasattr(limit_up_df, 'empty') and not limit_up_df.empty:
                    # 字段名可能是'连板数'或'连续板数'
                    for col in ['连板数', '连续板数', 'consecutive', 'board']:
                        if col in limit_up_df.columns:
                            max_consec_up = int(limit_up_df[col].max()) if not limit_up_df[col].empty else 0
                            break

                # 获取总成交额（从三大指数）
                total_turnover = 0
                try:
                    # 如果传入了 index_cache（已获取的指数数据），直接复用，避免重复查询
                    if index_cache:
                        idx_sh = index_cache.get('000001.SH')
                        idx_sz = index_cache.get('399001.SZ')
                        idx_cyb = index_cache.get('399006.SZ')
                    else:
                        idx_sh = self.get_index_data("000001.SH", dt)
                        idx_sz = self.get_index_data("399001.SZ", dt)
                        idx_cyb = self.get_index_data("399006.SZ", dt)
                    
                    amount_sum = 0
                    for idx in [idx_sh, idx_sz, idx_cyb]:
                        if idx and idx.get('success') and idx.get('data'):
                            amount_sum += idx['data'].get('amount', 0)
                    
                    total_turnover = amount_sum
                except Exception as e:
                    logger.debug(f"获取成交额异常: {e}")
                    total_turnover = 0

                data = {
                    "trade_date": date_str,
                    "limit_up_count": limit_up_count,
                    "limit_down_count": 0,  # akshare 暂无直接接口
                    "failed_limit_up": 0,
                    "failed_rate": 0.0,
                    "prev_limit_up_avg_return": 0.0,
                    "max_consec_up": max_consec_up,
                    "total_turnover": total_turnover,
                    "turnover_change_pct": 0.0
                }

                ttl = CACHE_TTL_CONFIG.get('market_sentiment', 300)
                # 数据验证（非阻塞，失败仅记录）
                validated_data, errors = validate_schema(data, MarketSentimentSchema)
                if errors:
                    logger.warning(f"市场情绪数据验证失败: {errors}; 使用原始数据")
                else:
                    data = validated_data
                set_cache(cache_key, data, namespace='akshare', ttl=ttl)
                logger.info(f"✅ akshare 获取市场情绪数据成功: {date_str}")
                return {"success": True, "data": data, "source": "akshare", "cached": False}
            except Exception as e:
                import traceback
                logger.error(f"akshare 获取市场情绪数据失败: {e}\n{traceback.format_exc()}")

        # ── 降级源：tushare pro.limit_list_d() ──
        if self.pro:
            return self._get_market_sentiment_tushare(dt, cache_key)

        return {"success": False, "data": None, "error": "无法获取市场情绪数据", "source": "none", "cached": False}

    def _get_market_sentiment_tushare(self, dt, cache_key=None):
        """使用 tushare 获取市场情绪数据（涨停/跌停/炸板统计）"""
        date_str = format_date(dt).replace('-', '')  # tushare 格式 YYYYMMDD
        try:
            limit_up_df = self.pro.limit_list_d(trade_date=date_str, limit_type='U')
            limit_down_df = self.pro.limit_list_d(trade_date=date_str, limit_type='D')

            limit_up_count = len(limit_up_df) if limit_up_df is not None and not getattr(limit_up_df, 'empty', True) else 0
            limit_down_count = len(limit_down_df) if limit_down_df is not None and not getattr(limit_down_df, 'empty', True) else 0

            # 最大连板数
            max_consec_up = 0
            if limit_up_count > 0:
                for col in ['连板数', 'board_num', 'consecutive']:
                    if col in limit_up_df.columns:
                        max_consec_up = int(limit_up_df[col].max())
                        break

            # 炸板率：用涨停池中 is_open=0 表示炸板
            failed_limit_up = 0
            if limit_up_count > 0:
                if 'is_open' in limit_up_df.columns:
                    failed_limit_up = int((limit_up_df['is_open'] == 0).sum())
                elif '炸板' in limit_up_df.columns:
                    failed_limit_up = int((limit_up_df['炸板'].astype(str) == '1').sum())

            failed_rate = round(failed_limit_up / max(limit_up_count, 1) * 100, 2)

            # 昨日涨停今日平均收益
            prev_date_str = (parse_date(format_date(dt)) - timedelta(days=1)).strftime('%Y%m%d')
            prev_avg_return = 0.0
            try:
                prev_perf = self.pro.limit_list_d(trade_date=prev_date_str, limit_type='U')
                if prev_perf is not None and not getattr(prev_perf, 'empty', True):
                    chg_col = None
                    for c in ['pct_change', 'pct_chg', 'change_pct', '涨跌幅']:
                        if c in prev_perf.columns:
                            chg_col = c
                            break
                    if chg_col:
                        avg = prev_perf[chg_col].mean()
                        prev_avg_return = round(float(avg), 2) if pd.notna(avg) else 0.0
            except Exception as e:
                logger.debug(f"昨日涨停表现获取失败: {e}")

            # 成交额从指数数据中获取
            total_turnover = 0
            try:
                for code in ["000001.SH", "399001.SZ", "399006.SZ"]:
                    idx = self.get_index_data(code, dt)
                    if idx.get('success') and idx.get('data'):
                        total_turnover += idx['data'].get('amount', 0)
            except Exception:
                pass

            data = {
                "trade_date": format_date(dt),
                "limit_up_count": limit_up_count,
                "limit_down_count": limit_down_count,
                "failed_limit_up": failed_limit_up,
                "failed_rate": failed_rate,
                "prev_limit_up_avg_return": prev_avg_return,
                "max_consec_up": max_consec_up,
                "total_turnover": total_turnover,
                "turnover_change_pct": 0.0
            }

            # 数据验证（非阻塞，失败仅记录）
            validated_data, errors = validate_schema(data, MarketSentimentSchema)
            if errors:
                logger.warning(f"tushare 情绪数据验证失败: {errors}; 使用原始数据")
            else:
                data = validated_data

            if cache_key:
                set_cache(cache_key, data, namespace='akshare', ttl=3600)
            logger.info(f"✅ tushare 情绪: 涨停{limit_up_count}/连板{max_consec_up}/跌停{limit_down_count}/炸板{failed_limit_up}")
            return {"success": True, "data": data, "source": "tushare", "cached": False}

        except Exception as e:
            logger.warning(f"tushare 获取情绪数据失败: {e}")
            return {"success": False, "data": None, "error": str(e), "source": "none"}

    def get_market_overview(self, dt):
        """
        获取市场全景概览（情绪评分+建议仓位）
        数据源：akshare stock_market_activity_legu（秒级返回全市场统计）
        """
        date_str = format_date(dt)
        cache_key = f'market_overview_{date_str}'
        cached = get_cache(cache_key, namespace='overview', ttl=3600)
        if cached is not None:
            return {"success": True, "data": cached, "source": "cache", "cached": True}

        result = {
            "score": 50, "trend": "震荡期",
            "up_count": 0, "down_count": 0, "flat_count": 0,
            "limit_up": 0, "limit_down": 0,
            "turnover": 0, "northbound": 0, "margin": 0,
            "suggest_position": 0.5, "volatility": 0
        }

        if self.ak:
            try:
                # 1. 上证成交额（快速）
                idx_result = self.get_index_data("000001.SH", dt)
                if idx_result.get('success'):
                    result["turnover"] = idx_result['data'].get('amount', 0)
                    result["volatility"] = abs(idx_result['data'].get('change_pct', 0))

                # 2. 用 legu 获取全市场涨跌统计（秒级）
                try:
                    df_legu = self.ak.stock_market_activity_legu()
                    for _, r in df_legu.iterrows():
                        item = str(r.get('item', ''))
                        val = r.get('value', 0)
                        try:
                            val = float(val)
                        except:
                            val = 0
                        if item == '上涨': result["up_count"] = int(val)
                        elif item == '下跌': result["down_count"] = int(val)
                        elif item == '平盘': result["flat_count"] = int(val)
                        elif item == '涨停': result["limit_up"] = int(val)
                        elif item == '跌停': result["limit_down"] = int(val)
                except Exception as e:
                    logger.warning(f"legu涨跌统计失败: {e}")

                # 3. 情绪评分
                score = min(result["limit_up"] * 8, 30)
                score += min(result["turnover"] / 1e12 * 20, 25)
                if result["up_count"] + result["down_count"] > 0:
                    win_ratio = result["up_count"] / (result["up_count"] + result["down_count"])
                    score += max(0, (win_ratio - 0.3) * 20)
                if result["limit_down"] > 0 and result["down_count"] > 0:
                    panic_ratio = result["limit_down"] / result["down_count"]
                    score -= panic_ratio * 10
                result["score"] = max(0, min(100, round(score, 1)))

                # 4. 趋势判定
                if result["score"] >= 70: result["trend"] = "上涨期"
                elif result["score"] >= 50: result["trend"] = "回暖期"
                elif result["score"] >= 30: result["trend"] = "震荡期"
                else: result["trend"] = "下跌期"

                # 5. 建议仓位
                base = 0.3 + (result["score"] / 100) * 0.4
                vol_factor = 0.9 if result["volatility"] > 3 else 1.0
                result["suggest_position"] = round(max(0.3, min(0.7, base * vol_factor)), 2)

            except Exception as e:
                logger.error(f"市场全景计算失败: {e}")

        # ── 降级源：tushare pro.moneyflow() 获取涨跌统计 ──
        if self.pro and result.get("up_count", 0) == 0 and result.get("down_count", 0) == 0:
            try:
                date_str_ts = parse_date(date_str).strftime('%Y%m%d')
                df = self.pro.daily(trade_date=date_str_ts)
                if df is not None and not getattr(df, 'empty', True):
                    up_c = int((df['pct_chg'] > 0).sum())
                    down_c = int((df['pct_chg'] < 0).sum())
                    flat_c = int((df['pct_chg'] == 0).sum())
                    limit_up_c = int((df['pct_chg'] >= 9.8).sum())
                    limit_down_c = int((df['pct_chg'] <= -9.8).sum())
                    result["up_count"] = up_c
                    result["down_count"] = down_c
                    result["flat_count"] = flat_c
                    result["limit_up"] = limit_up_c
                    result["limit_down"] = limit_down_c
                    # 重新计算情绪评分
                    score = min(limit_up_c * 8, 30)
                    if result.get("turnover", 0) > 0:
                        score += min(result["turnover"] / 1e12 * 20, 25)
                    if up_c + down_c > 0:
                        win_ratio = up_c / (up_c + down_c)
                        score += max(0, (win_ratio - 0.3) * 20)
                    result["score"] = max(0, min(100, round(score, 1)))
                    if result["score"] >= 70: result["trend"] = "上涨期"
                    elif result["score"] >= 50: result["trend"] = "回暖期"
                    elif result["score"] >= 30: result["trend"] = "震荡期"
                    else: result["trend"] = "下跌期"
                    base = 0.3 + (result["score"] / 100) * 0.4
                    vol_factor = 0.9 if abs(result.get("volatility", 0)) > 3 else 1.0
                    result["suggest_position"] = round(max(0.3, min(0.7, base * vol_factor)), 2)
                    logger.info(f"✅ tushare 市场全景: {up_c}涨/{down_c}跌/{flat_c}平 涨停{limit_up_c}/跌停{limit_down_c}")
            except Exception as e:
                logger.debug(f"tushare 市场全景降级失败: {e}")

        set_cache(cache_key, result, namespace='overview', ttl=3600)
        logger.info(f"✅ 市场全景: {result['score']}分 {result['trend']} up={result['up_count']} "
                    f"down={result['down_count']} limit={result['limit_up']}/{result['limit_down']} "
                    f"turnover={result['turnover']/1e8:.0f}亿 仓位{result['suggest_position']:.0%}")
        return {"success": True, "data": result, "source": "akshare_legu", "cached": False}

    def get_market_depth(self, dt):
        """
        获取盘面深度数据（炸板率、涨跌幅>5%个股）
        返回：
        {
            "break_rate": 17.5,      # 炸板率 %
            "up_over_5pct": 50,      # 涨幅>5%个股数
            "down_over_5pct": 10,    # 跌幅>5%个股数
            "prev_limit_up_return": 2.3  # 昨日涨停今日平均收益 %
        }
        """
        date_str = format_date(dt)
        cache_key = f'market_depth_{date_str}'
        cached = get_cache(cache_key, namespace='depth', ttl=3600)
        if cached is not None:
            return {"success": True, "data": cached, "source": "cache", "cached": True}

        if self.ak:
            try:
                # 1. 获取涨停池数据
                ak_date = parse_date(date_str).strftime('%Y%m%d')
                df_zt = self.ak.stock_zt_pool_em(date=ak_date)

                if df_zt is None or df_zt.empty:
                    logger.warning("涨停池数据为空，无法计算炸板率")
                    return {"success": False, "data": None, "error": "无涨停数据", "source": "none"}

                total_limits = len(df_zt)  # 总涨停数

                # 2. 计算炸板数（炸板次数 > 0 的视为炸板）
                # 字段：'炸板次数'，可能有缺失用其他字段
                break_count = 0
                if '炸板次数' in df_zt.columns:
                    break_count = (df_zt['炸板次数'] > 0).sum()
                elif '涨停统计' in df_zt.columns:
                    # 有些版本有"涨停统计"字段如"2/2"表示2板成功，1/2表示炸板
                    def is_break(val):
                        if isinstance(val, str) and '/' in val:
                            parts = val.split('/')
                            return parts[0] != parts[1]
                        return False
                    break_count = df_zt['涨停统计'].apply(is_break).sum()

                break_rate = (break_count / total_limits * 100) if total_limits > 0 else 0

                # 3. 涨跌幅>5%统计（从涨停池可以部分推断，但不够全面）
                # 注意：akshare 没有直接获取全市场涨跌幅分布，暂时用涨停数近似
                up_over_5pct = total_limits + int(total_limits * 0.5)  # 粗略估计
                down_over_5pct = 0

                # 4. 昨日涨停今日表现（需要获取昨日涨停池，再查今日表现）
                # 可以使用 get_watchlist_performance 类似的逻辑
                # 暂时用0或模拟数据
                prev_limit_up_return = 0.0

                result = {
                    "break_rate": round(break_rate, 1),
                    "break_count": int(break_count),
                    "total_limit_up": int(total_limits),
                    "up_over_5pct": int(up_over_5pct),
                    "down_over_5pct": int(down_over_5pct),
                    "prev_limit_up_return": round(prev_limit_up_return, 2)
                }

                set_cache(cache_key, result, namespace='depth', ttl=3600)
                logger.info(f"✅ 获取盘面深度数据：炸板率{break_rate:.1f}%")
                return {"success": True, "data": result, "source": "akshare", "cached": False}

            except Exception as e:
                import traceback
                logger.error(f"计算盘面深度失败: {e}\n{traceback.format_exc()}")

        # ── 降级源：tushare pro.limit_list_d() ──
        if self.pro:
            return self._get_market_depth_tushare(dt, cache_key)

        return {"success": False, "data": None, "error": "无法获取盘面深度数据", "source": "none"}

    def _get_market_depth_tushare(self, dt, cache_key=None):
        """使用 tushare 获取盘面深度（炸板率/涨跌统计）"""
        date_str = format_date(dt).replace('-', '')
        try:
            limit_up_df = self.pro.limit_list_d(trade_date=date_str, limit_type='U')
            limit_down_df = self.pro.limit_list_d(trade_date=date_str, limit_type='D')

            total_limit_up = len(limit_up_df) if limit_up_df is not None and not getattr(limit_up_df, 'empty', True) else 0
            total_limit_down = len(limit_down_df) if limit_down_df is not None and not getattr(limit_down_df, 'empty', True) else 0

            # 炸板数：用跌停池中的首板涨停被砸来判断
            break_count = 0
            if total_limit_up > 0 and 'is_open' in limit_up_df.columns:
                break_count = int((limit_up_df['is_open'] == 0).sum())

            break_rate = round(break_count / max(total_limit_up, 1) * 100, 1)

            # 涨>5% 和 跌>5% 估算
            up_over_5pct = total_limit_up * 2 if total_limit_up > 0 else 0
            down_over_5pct = total_limit_down * 2 if total_limit_down > 0 else 0

            # 昨日涨停今日收益
            prev_date = (parse_date(format_date(dt)) - timedelta(days=1)).strftime('%Y%m%d')
            prev_return = 0.0
            try:
                prev_df = self.pro.limit_list_d(trade_date=prev_date, limit_type='U')
                if prev_df is not None and not getattr(prev_df, 'empty', True):
                    for col in ['pct_change', 'pct_chg', 'change_pct']:
                        if col in prev_df.columns:
                            avg = prev_df[col].mean()
                            prev_return = round(float(avg), 2) if pd.notna(avg) else 0.0
                            break
            except Exception:
                pass

            result = {
                "break_rate": break_rate,
                "break_count": break_count,
                "total_limit_up": total_limit_up,
                "up_over_5pct": up_over_5pct,
                "down_over_5pct": down_over_5pct,
                "prev_limit_up_return": prev_return
            }

            if cache_key:
                set_cache(cache_key, result, namespace='depth', ttl=3600)
            logger.info(f"✅ tushare 盘面深度: 涨停{total_limit_up}/跌停{total_limit_down}/炸板率{break_rate}%")
            return {"success": True, "data": result, "source": "tushare", "cached": False}

        except Exception as e:
            logger.warning(f"tushare 盘面深度获取失败: {e}")
            return {"success": False, "data": None, "error": str(e), "source": "none"}
