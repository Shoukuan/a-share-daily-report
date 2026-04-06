
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
from schemas import SectorInfoSchema, validate_many

logger = get_logger('data_fetcher')

class SectorFetcherMixin:
    def get_sector_data(self, dt):
        """
        获取行业板块和概念板块的Top 5 + 领涨股/龙头股
        数据源：同花顺（ths）— 不依赖 push2.eastmoney.com，不受代理影响
        """
        date_str = format_date(dt)
        cache_key = f'sectors_{date_str}'
        ttl = CACHE_TTL_CONFIG.get('sectors', 1800)
        cached = get_cache(cache_key, namespace='akshare', ttl=ttl)
        if cached is not None:
            return {"success": True, "data": cached, "source": "cache", "cached": True}

        result = {"industry": [], "concept": []}

        if self.ak:
            # 行业板块（同花顺，直接含领涨股信息）
            try:
                df_industry = self.ak.stock_board_industry_summary_ths()
                if df_industry is not None and not df_industry.empty:
                    df_industry['涨跌幅'] = pd.to_numeric(df_industry['涨跌幅'], errors='coerce')
                    top5 = df_industry.nlargest(5, '涨跌幅')
                    for _, row in top5.iterrows():
                        sector_name = row.get('板块', '')
                        change_pct = float(row.get('涨跌幅', 0)) if pd.notna(row.get('涨跌幅')) else 0
                        # 同花顺直接提供领涨股
                        leaders = []
                        leader_name = row.get('领涨股', '')
                        leader_change = row.get('领涨股-涨跌幅', '')
                        if leader_name and leader_name != '--':
                            leader_pct = 0
                            if pd.notna(leader_change) and leader_change != '--':
                                try:
                                    leader_pct = float(leader_change)
                                except (ValueError, TypeError):
                                    leader_pct = 0
                            leaders.append({
                                "name": str(leader_name),
                                "code": "",
                                "change_pct": leader_pct
                            })
                        result["industry"].append({
                            "sector": sector_name,
                            "change_pct": change_pct,
                            "leaders": leaders
                        })
            except Exception as e:
                logger.warning(f"行业板块获取失败: {e}")

            # 概念板块（同花顺）— 同时输出龙头股 + 驱动事件
            try:
                df_concept = self.ak.stock_board_concept_summary_ths()
                if df_concept is not None and not df_concept.empty:
                    top5 = df_concept.head(5)  # 已按热度排序，取前5
                    for _, row in top5.iterrows():
                        sector_name = row.get('概念名称', '')
                        leader = row.get('龙头股', '--')
                        driver = row.get('驱动事件', '--')  # 新增：驱动事件
                        result["concept"].append({
                            "sector": sector_name,
                            "change_pct": 0,
                            "leaders": [{"name": str(leader), "code": "", "change_pct": 0}] if leader != '--' else [],
                            "driver": str(driver) if driver and driver != '--' else ""  # 新增字段
                        })
            except Exception as e:
                logger.warning(f"概念板块获取失败: {e}")

            if result["industry"] or result["concept"]:
                # 数据验证（可选，失败仅记录warning）
                try:
                    validated_industry, ind_errors = validate_many(result["industry"], SectorInfoSchema)
                    validated_concept, con_errors = validate_many(result["concept"], SectorInfoSchema)
                    if ind_errors or con_errors:
                        logger.warning(f"板块数据验证问题: industry={ind_errors}, concept={con_errors}")
                    result["industry"] = validated_industry
                    result["concept"] = validated_concept
                except Exception as ve:
                    logger.debug(f"板块数据验证跳过: {ve}")

                ttl = CACHE_TTL_CONFIG.get('sectors', 1800)
                set_cache(cache_key, result, namespace='akshare', ttl=ttl)
                logger.info(f"✅ 板块数据成功：行业{len(result['industry'])} 概念{len(result['concept'])}")
                return {"success": True, "data": result, "source": "akshare_ths", "cached": False}

        return {"success": False, "data": None, "error": "无法获取板块数据", "source": "none", "cached": False}

    def get_lhb_data(self, dt):
        """
        获取龙虎榜数据（机构买卖动向）
        数据源：akshare stock_lhb_detail_em
        """
        date_str = format_date(dt)
        cache_key = f'lhb_{date_str}'
        ttl = CACHE_TTL_CONFIG.get('lhb', 7200)
        cached = get_cache(cache_key, namespace='akshare', ttl=ttl)
        if cached is not None:
            return {"success": True, "data": cached, "source": "cache", "cached": True}

        if self.ak:
            try:
                ak_date = date_str.replace('-', '')
                df = self.ak.stock_lhb_detail_em(start_date=ak_date, end_date=ak_date)
                if df is not None and not df.empty:
                    selected = []
                    for _, row in df.iterrows():
                        net = float(row.get('龙虎榜净买额', 0))
                        selected.append({
                            "code": str(row.get('代码', '')).strip(),
                            "name": str(row.get('名称', '')).strip(),
                            "net_inflow": net,  # 单位：元
                            "change_pct": float(row.get('涨跌幅', 0)) if pd.notna(row.get('涨跌幅', 0)) else 0,
                            "close": float(row.get('收盘价', 0)) if pd.notna(row.get('收盘价', 0)) else 0
                        })
                    selected.sort(key=lambda x: x['net_inflow'], reverse=True)
                    result = selected[:10]
                    ttl = CACHE_TTL_CONFIG.get('lhb', 7200)
                    set_cache(cache_key, result, namespace='akshare', ttl=ttl)
                    logger.info(f"✅ 龙虎榜成功: {len(result)} 条")
                    return {"success": True, "data": result, "source": "akshare", "cached": False}
            except Exception as e:
                logger.warning(f"龙虎榜失败: {e}")

        # ── 降级源：tushare pro.top_list() ──
        if self.pro:
            return self._get_lhb_data_tushare(dt, cache_key)

        return {"success": False, "data": None, "error": "无法获取龙虎榜", "source": "none"}

    def _get_lhb_data_tushare(self, dt, cache_key=None):
        """使用 tushare 获取龙虎榜数据"""
        date_str = format_date(dt).replace('-', '')
        try:
            df = self.pro.top_list(trade_date=date_str)
            if df is None or getattr(df, 'empty', True):
                return {"success": False, "data": None, "error": "当日无龙虎榜数据", "source": "tushare"}

            selected = []
            for _, row in df.iterrows():
                ts_code = str(row.get('ts_code', ''))
                code = ts_code.split('.')[0] if '.' in ts_code else ts_code
                net_inflow = float(row.get('net_amount', 0) or 0)  # 净买额（万元）
                # 安全防护：异常大的数值视为脏数据
                if abs(net_inflow) > 1e7:  # 超过 1000 亿元忽略
                    logger.warning(f"龙虎榜净买额异常: {row.get('name')} {net_inflow} 万，跳过")
                    continue
                selected.append({
                    "code": code,
                    "name": str(row.get('name', '')).strip(),
                    "net_inflow": net_inflow,  # 万元
                    "change_pct": float(row.get('pct_change', 0) or 0),
                    "close": float(row.get('close', 0) or 0)
                })

            selected.sort(key=lambda x: abs(x['net_inflow']), reverse=True)
            result = selected[:10]

            if cache_key:
                ttl = CACHE_TTL_CONFIG.get('lhb', 7200)
                set_cache(cache_key, result, namespace='akshare', ttl=ttl)
            logger.info(f"✅ tushare 龙虎榜: {len(result)} 条")
            return {"success": True, "data": result, "source": "tushare", "cached": False}

        except Exception as e:
            logger.warning(f"tushare 龙虎榜获取失败: {e}")
            return {"success": False, "data": None, "error": str(e), "source": "none"}

    def _fetch_spot_from_mx_data(self, watchlist):
        """
        使用 mx-data 批量获取自选股行情
        返回 dict: {代码(不含后缀): {price, change_pct, amount, amplitude, turnover, volume_ratio}}
        """
        self._load_env()
        mx_key = self._get_mx_apikey()
        if not mx_key:
            raise ValueError("MX_APIKEY 未设置")

        result = {}
        for stock in watchlist:
            code_raw = stock.get('code', '')
            name = stock.get('name', code_raw)
            ak_code = code_raw.split('.')[0]

            try:
                query = f"{name}今日涨跌幅 最新价 成交额 换手率 量比 振幅 5日均线 20日均线"
                raw = self._mx_query_json(query, TIMEOUTS['mx_watchlist_sec'])
                row = self.mx_provider.parse_watchlist_row(raw)

                if 'price' in row:
                    result[ak_code] = row
                    logger.debug(f"mx-data 获取 {name} 成功: {row}")
                else:
                    logger.warning(f"mx-data 未解析到 {name} 的价格数据")

            except Exception as e:
                logger.warning(f"mx-data 获取 {name} 失败: {e}")
                continue

        return result

    def get_watchlist_performance(self, watchlist, dt):
        """
        获取自选股当日表现
        优先级：mx-data → akshare(stock_zh_a_spot_em) → yfinance
        返回详细数据，包含 8 维度评分
        """
        date_str = format_date(dt)
        cache_key = f'watchlist_{date_str}'
        cached = get_cache(cache_key, namespace='watchlist_detail', ttl=3600)
        if cached is not None:
            return {"success": True, "data": cached, "source": "cache", "cached": True}

        performance = []
        df_spot = None
        mx_spot = {}  # mx-data 结果 {ak_code: row_dict}

        # ── 优先级1：mx-data（始终使用，盘后仍可获取收盘行情）────────
        try:
            mx_spot = self._fetch_spot_from_mx_data(watchlist)
            if mx_spot:
                logger.info(f"✅ mx-data 获取自选股行情成功: {len(mx_spot)}/{len(watchlist)}")
            else:
                logger.warning("mx-data 未返回任何自选股数据，降级到 akshare")
        except Exception as e:
            logger.warning(f"mx-data 自选股获取失败 ({e})，降级到 akshare")

        # ── 优先级2：akshare stock_zh_a_spot_em ──────────────────────────────
        if len(mx_spot) < len(watchlist) and self.ak:
            try:
                df_spot = self.ak.stock_zh_a_spot_em()
                logger.info("✅ akshare spot_em 全市场行情获取成功")
            except Exception as e:
                logger.warning(f"akshare spot 失败 ({e})，降级到 yfinance 获取")
                df_spot = None

        # ── 构建每只股票的行情数据（合并三个数据源）────────────────────────────
        # yfinance 备用（仅当 mx-data 和 akshare 都没有该股票数据时逐只调用）
        yf_module = None

        try:
            for stock in watchlist:
                code_raw = stock.get('code', '')
                name = stock.get('name', '')
                ak_code = code_raw.split('.')[0]

                # ── 获取当日行情（按优先级合并）──────────────────────────────
                spot_row = {}

                # 1. mx-data 已有
                if ak_code in mx_spot:
                    spot_row = mx_spot[ak_code]
                    spot_src = 'mx-data'
                # 2. akshare spot_em
                elif df_spot is not None:
                    matched = df_spot[df_spot['代码'] == ak_code]
                    if not matched.empty:
                        r = matched.iloc[0]
                        spot_row = {
                            'price':        float(r.get('最新价', 0)),
                            'change_pct':   float(r.get('涨跌幅', 0)),
                            'amount':       float(r.get('成交额', 0)),
                            'amplitude':    float(r.get('振幅', 0)),
                            'turnover':     float(r.get('换手率', 0)),
                            'volume_ratio': float(r.get('量比', 0)),
                        }
                        spot_src = 'akshare'
                # 3. yfinance 兜底
                if not spot_row:
                    try:
                        if yf_module is None:
                            import yfinance as yf
                            yf_module = yf
                        exchange = code_raw.split('.')[-1] if '.' in code_raw else ''
                        if exchange == 'SH':
                            yf_code = f"{ak_code}.SS"
                        elif exchange == 'SZ':
                            yf_code = f"{ak_code}.SZ"
                        else:
                            yf_code = ak_code
                        ticker = yf_module.Ticker(yf_code)
                        hist = ticker.history(period="5d")
                        if not hist.empty:
                            curr = float(hist['Close'].iloc[-1])
                            prev = float(hist['Close'].iloc[-2]) if len(hist) >= 2 else curr
                            chg_pct = (curr - prev) / prev * 100 if prev else 0
                            spot_row = {
                                'price': round(curr, 2),
                                'change_pct': round(chg_pct, 2),
                                'amount': 0, 'amplitude': 0,
                                'turnover': 0, 'volume_ratio': 0,
                            }
                            spot_src = 'yfinance'
                    except Exception as yf_e:
                        logger.warning(f"yfinance 获取 {name} 失败: {yf_e}")

                if not spot_row:
                    logger.warning(f"所有数据源均无法获取 {name}({code_raw}) 行情")
                    continue
                
                # 获取日线数据（近 90 日）用于技术分析
                # 优先 akshare，失败降级 yfinance
                df_hist = pd.DataFrame()
                try:
                    df_hist = self.ak.stock_zh_a_hist(symbol=ak_code, period="daily",
                        start_date=(parse_date(date_str) - pd.Timedelta(days=90)).strftime('%Y%m%d'),
                        end_date=date_str.replace('-', ''))
                except Exception as ak_hist_e:
                    logger.warning(f"akshare 历史数据获取失败 ({ak_hist_e})，降级 yfinance 获取历史数据")
                    try:
                        if yf_module is None:
                            import yfinance as yf
                            yf_module = yf
                        exchange = code_raw.split('.')[-1] if '.' in code_raw else ''
                        yf_code = f"{ak_code}.SS" if exchange == 'SH' else (f"{ak_code}.SZ" if exchange == 'SZ' else ak_code)
                        ticker = yf_module.Ticker(yf_code)
                        hist_yf = ticker.history(period="3mo")
                        if not hist_yf.empty:
                            # 转换为 akshare 同名列格式
                            df_hist = pd.DataFrame({
                                '收盘': hist_yf['Close'].values,
                                '成交量': hist_yf['Volume'].values,
                            })
                            logger.debug(f"yfinance 历史数据 {code_raw}: {len(df_hist)} 条")
                    except Exception as yf_hist_e:
                        logger.warning(f"yfinance 历史数据也失败 ({yf_hist_e})")
                        df_hist = pd.DataFrame()

                has_hist = df_hist is not None and not df_hist.empty if isinstance(df_hist, pd.DataFrame) else False

                # 8 维度评分
                if has_hist:
                    close_series = pd.to_numeric(df_hist['收盘'], errors='coerce').dropna()
                    ma5 = close_series.tail(5).mean()
                    ma20 = close_series.tail(min(20, len(close_series))).mean()
                    ma60 = close_series.tail(min(60, len(close_series))).mean()
                    curr_close = close_series.iloc[-1]

                    # 趋势（价格与均线关系）
                    curr_price = spot_row.get('price', curr_close)
                    trend = 75 if curr_price > ma60 and ma5 > ma20 else (60 if curr_price > ma20 else (40 if curr_price > ma5 else 25))
                    # 动量（近 5 日涨幅）
                    recent_5 = close_series.tail(5)
                    pct_5d = (recent_5.iloc[-1] - recent_5.iloc[0]) / recent_5.iloc[0] * 100 if len(recent_5) > 1 else 0
                    momentum = min(100, max(0, int(50 + pct_5d * 8)))
                    # RSI 简化
                    gains = close_series.diff().tail(14).clip(lower=0).sum()
                    losses = (-close_series.diff().tail(14)).clip(lower=0).sum()
                    rs = gains / losses if losses > 0 else 999
                    rsi = int(100 - 100/(1+rs)) if losses > 0 else 80
                    # 量能 vs 5日均量
                    vol_series = pd.to_numeric(df_hist['成交量'], errors='coerce').dropna()
                    vol_avg5 = vol_series.tail(5).mean()
                    curr_vol = spot_row.get('volume_ratio', 1) * vol_avg5  # volume_ratio 是量比
                    vol_ratio = spot_row.get('volume_ratio', 1)
                    vol_score = min(100, max(20, int(50 + (vol_ratio - 1) * 30)))
                    # 波动率（振幅）
                    amp = spot_row.get('amplitude', 0)
                    amp_score = min(100, max(20, int(amp * 15)))
                    # 相对强弱 vs 大盘
                    idx_change = -0.8  # 上证今日-0.8%
                    stock_change = spot_row.get('change_pct', 0)
                    relative = 65 if stock_change > idx_change else 35
                    # 行业强弱（简化）
                    industry = 50
                    # 回撤（近 20 日最大回撤）
                    max_drawdown = ((close_series.tail(20).max() - curr_close) / close_series.tail(20).max() * 100) if len(close_series) >= 20 else 5
                    dd_score = max(20, min(100, int(80 - max_drawdown * 2)))
                    avg_score = (trend + momentum + rsi + vol_score + amp_score + relative + industry + dd_score) // 8
                else:
                    # 无历史数据：从 spot_row（mx-data）取均线，评分简化
                    ma5 = spot_row.get('ma5', 0)
                    ma20 = spot_row.get('ma20', 0)
                    ma60 = 0
                    curr_price = spot_row.get('price', 0)
                    pct_5d = trend = momentum = rsi = 50
                    vol_score = amp_score = relative = dd_score = industry = 50
                    avg_score = 50
                    max_drawdown = 0

                # 判断
                if avg_score >= 65:
                    signal = "👍 重点关注"
                elif avg_score >= 50:
                    signal = "👀 保持关注"
                else:
                    signal = "⚠️ 谨慎观望"

                curr_price = spot_row.get('price', 0)
                change_pct = spot_row.get('change_pct', 0)
                perf = {
                    "code": code_raw,
                    "name": name,
                    "price": curr_price,
                    "change_pct": change_pct,
                    "amount": spot_row.get('amount', 0),
                    "amplitude": spot_row.get('amplitude', 0),
                    "turnover": spot_row.get('turnover', 0),
                    "volume_ratio": spot_row.get('volume_ratio', 0),
                    "ma5": round(float(ma5), 2) if ma5 else 0,
                    "ma20": round(float(ma20), 2) if ma20 else 0,
                    "score_8d": {"trend": trend, "momentum": momentum, "rsi": rsi,
                                 "vol": vol_score, "amp": amp_score, "relative": relative,
                                 "industry": industry, "dd": dd_score},
                    "avg_score": avg_score,
                    "signal": signal,
                    "support": round(ma20, 2) if ma20 > 0 else round(curr_price * 0.97, 2),
                    "resistance": round(max(ma60, ma5) if ma60 > 0 else curr_price * 1.03, 2),
                    "reason": self._get_watchlist_reason(name, change_pct, amt=spot_row.get('amount', 0)),
                    "data_source": spot_src,
                }
                performance.append(perf)

        except Exception as e:
            logger.error(f"自选股获取失败: {e}")
            return {"success": False, "data": None, "error": str(e)}

        if performance:
            # 记录数据来源统计
            src_stat = {}
            for p in performance:
                s = p.get('data_source', 'unknown')
                src_stat[s] = src_stat.get(s, 0) + 1
            logger.info(f"✅ 自选股获取成功: {len(performance)}/{len(watchlist)}, 来源: {src_stat}")
            set_cache(cache_key, performance, namespace='watchlist_detail', ttl=1800)
            return {"success": True, "data": performance, "source": str(src_stat), "cached": False}
        else:
            logger.warning("无法获取任何自选股数据")
            return {"success": False, "data": None, "error": "未获取到数据"}

    def _get_watchlist_reason(self, name, change_pct, amt=0):
        """生成关注理由"""
        if change_pct > 5:
            return "强势上涨，突破关键位"
        elif change_pct > 2:
            return "温和上涨，趋势向好"
        elif change_pct > 0:
            return "小幅上涨，企稳反弹"
        elif change_pct > -2:
            return "小幅回调，正常整理"
        elif change_pct > -5:
            return "调整加大，注意支撑"
        else:
            return "大幅下跌，风险警示"
