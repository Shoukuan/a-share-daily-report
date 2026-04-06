
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

from constants import INDEX_NAMES, YFINANCE_INDEX_MAP, ALL_INDICES, TIMEOUTS, RETRY_POLICY
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

logger = get_logger('data_fetcher')

class MoneyFetcherMixin:
    def get_money_flow(self, dt):
        """
        获取资金流向数据（北向资金汇总）
        北向资金：已暂停实时披露，使用历史数据
        主力资金：使用 akshare 行业主力流入汇总
        """
        date_str = format_date(dt)
        cache_key = f'moneyflow_{date_str}'
        cached = get_cache(cache_key, namespace='akshare', ttl=3600)
        if cached is not None:
            return {"success": True, "data": cached, "source": "cache", "cached": True}

        result = {
            "trade_date": date_str,
            "northbound": None,  # 北向资金暂停实时披露
            "main_capital": None
        }

        if self.ak:
            try:
                # 尝试获取北向资金 — 优先 stock_hsgt_fund_flow_summary_em（稳定）
                try:
                    df_summary = self.ak.stock_hsgt_fund_flow_summary_em()
                    if df_summary is not None and not df_summary.empty:
                        north_rows = df_summary[df_summary['资金方向'] == '北向']
                        if not north_rows.empty:
                            net_total = north_rows['资金净流入'].sum()
                            if pd.notna(net_total) and net_total != 0:
                                result["northbound"] = float(net_total) * 1e8
                                logger.info(f"✅ 北向资金: {net_total:.2f}亿")
                except Exception:
                    pass

                # 降级：stock_hsgt_hist_em 历史数据
                if result["northbound"] is None:
                    try:
                        df_north = self.ak.stock_hsgt_hist_em(symbol="北向资金")
                        if df_north is not None and not df_north.empty:
                            target_date = parse_date(date_str)
                            df_north['日期'] = pd.to_datetime(df_north['日期'])
                            matched = df_north[df_north['日期'] == target_date]
                            if matched.empty:
                                df_north = df_north.sort_values('日期')
                                filtered = df_north[df_north['日期'] <= target_date]
                                if not filtered.empty:
                                    matched = filtered.tail(1)
                            if not matched.empty:
                                row = matched.iloc[-1]
                                net = row.get('当日资金流入', None)
                                if pd.notna(net) and net not in ['-', None, '']:
                                    result["northbound"] = float(net) * 1e8
                    except Exception as e:
                        logger.debug(f"北向资金历史数据获取失败: {e}")

                # 主力资金：从行业资金流中汇总（加超时保护，东财 proxy 不稳定）
                try:
                    import signal as _signal
                    def _timeout_handler(signum, frame):
                        raise TimeoutError("stock_sector_fund_flow_rank 超时")
                    _signal.signal(_signal.SIGALRM, _timeout_handler)
                    _signal.alarm(10)  # 10秒超时
                    try:
                        df_flow = self.ak.stock_sector_fund_flow_rank(indicator="今日", sector_type="行业资金流")
                        _signal.alarm(0)
                        if df_flow is not None and not df_flow.empty:
                            total_net = df_flow.get('今日主力净流入-净额', None)
                            if total_net is not None and len(total_net) > 0:
                                total_main = total_net.sum()
                                result["main_capital"] = float(total_main) * 1e4
                    finally:
                        _signal.alarm(0)
                except (TimeoutError, Exception) as e:
                    logger.debug(f"主力资金获取跳过（超时或失败）: {e}")
            except Exception as e:
                logger.warning(f"资金流向获取失败: {e}")

        # ── tushare 北向资金兜底 ──
        if result["northbound"] is None and self.pro:
            try:
                start_dt = parse_date(date_str) - timedelta(days=30)
                start = start_dt.strftime('%Y%m%d')
                end = parse_date(date_str).strftime('%Y%m%d')

                df = self.pro.moneyflow_hsgt(start_date=start, end_date=end)
                if df is not None and not df.empty:
                    latest = df.iloc[-1]
                    north = float(latest.get('north_money', 0))
                    if pd.notna(north):
                        result["northbound"] = north * 1e4  # 万元转元
                        logger.info(f"✅ tushare 北向资金: {north:.2f}万 ({latest.get('trade_date','')})")
            except Exception as e:
                logger.debug(f"tushare 北向资金获取失败: {e}")

        set_cache(cache_key, result, namespace='akshare', ttl=3600)
        return {"success": True, "data": result, "source": "akshare", "cached": False}

    def get_industry_fund_flow(self, dt=None):
        """
        行业资金流向
        数据源优先级：akshare stock_sector_fund_flow_rank → mx-data 行业资金流
        akshare 不可用时自动降级 mx-data
        """
        cache_key = 'industry_fund_flow'
        cached = get_cache(cache_key, namespace='akshare', ttl=3600)
        if cached is not None:
            return {"success": True, "data": cached, "source": "cache", "cached": True}

        # ── 第一层：akshare ──
        if self.ak and not type(self)._akshare_unavailable:
            try:
                df = self.ak.stock_sector_fund_flow_rank(indicator="今日", sector_type="行业资金流")
                if df is not None and not df.empty:
                    # 按主力净流入排序
                    net_col = '今日主力净流入-净额'
                    df[net_col] = pd.to_numeric(df[net_col], errors='coerce')
                    df_sorted = df.sort_values(net_col, ascending=False)

                    inflow_top5 = []
                    for i, (_, row) in enumerate(df_sorted.head(5).iterrows()):
                        inflow_top5.append({
                            "rank": i + 1,
                            "industry": str(row.get('名称', '')),
                            "net_inflow": float(row[net_col]) * 1e4,  # 万元转元
                            "leading_stock": str(row.get('今日主力净流入最大股', '')),
                            "leading_stock_change": float(row.get('今日涨跌幅', 0)) if pd.notna(row.get('今日涨跌幅', 0)) else 0
                        })

                    outflow_top5 = []
                    for i, (_, row) in enumerate(df_sorted.tail(5).iterrows()):
                        outflow_top5.append({
                            "industry": str(row.get('名称', '')),
                            "net_inflow": float(row[net_col]) * 1e4,
                            "leading_stock": str(row.get('今日主力净流入最大股', ''))
                        })
                    outflow_top5.reverse()

                    data = {
                        "update_time": format_date(datetime.now()),
                        "total_industries": len(df),
                        "top_net_inflow": inflow_top5,
                        "top_net_outflow": outflow_top5
                    }

                    set_cache(cache_key, data, namespace='akshare', ttl=3600)
                    logger.info(f"✅ 行业资金流成功: {len(df)} 个行业")
                    return {"success": True, "data": data, "source": "akshare", "cached": False}
            except Exception as e:
                err_str = str(e)
                if 'RemoteDisconnected' in err_str or 'push2.eastmoney.com' in err_str:
                    type(self)._akshare_unavailable = True
                    logger.warning(f"akshare 东方财富接口不可用，降级 mx-data: {e}")
                else:
                    logger.warning(f"行业资金流 akshare 失败: {e}")

        # ── 第二层：mx-data 行业资金流兜底 ──
        result_mx = self._get_industry_fund_flow_mx_data()
        if result_mx.get('success'):
            set_cache(cache_key, result_mx['data'], namespace='akshare', ttl=3600)
            logger.info(f"✅ 行业资金流成功(mx-data): {result_mx['data']['total_industries']} 个行业")
            return result_mx

        return {"success": False, "data": None, "error": "无法获取行业资金流", "source": "none"}

    def _get_industry_fund_flow_mx_data(self):
        """
        使用 mx-data 获取行业资金流向数据（兜底方案）
        返回与 akshare stock_sector_fund_flow_rank 相同的结构
        """
        self._load_env()
        mx_apikey = self._get_mx_apikey()
        if not mx_apikey:
            return {"success": False, "data": None, "error": "MX_APIKEY 未设置", "source": "none"}

        try:
            query = "A股行业板块资金流向排名 今日主力净流入 净流入 排名 板块名称 领涨股"
            raw = self._mx_query_json(query, TIMEOUTS['mx_industry_flow_sec'])
            data = self.mx_provider.parse_industry_fund_flow(
                raw=raw,
                update_time=format_date(datetime.now()),
            )

            return {"success": True, "data": data, "source": "mx-data", "cached": False}

        except Exception as e:
            logger.warning(f"mx-data 行业资金流降级失败: {e}")
            return {"success": False, "data": None, "error": str(e), "source": "none"}

    def get_global_assets(self):
        """
        获取全球资产价格（美元指数、黄金、原油）
        数据源：yfinance
        """
        cache_key = 'global_assets'
        cached = get_cache(cache_key, namespace='yfinance', ttl=1800)
        if cached is not None:
            return {"success": True, "data": cached, "source": "cache", "cached": True}

        try:
            import yfinance as yf

            assets_config = {
                'usd_index': {'ticker': 'DX-Y.NYB', 'name': '美元指数'},
                'gold': {'ticker': 'GC=F', 'name': '黄金(COMEX)'},
                'oil': {'ticker': 'CL=F', 'name': '原油(WTI)'}
            }

            result = {}
            for key, config in assets_config.items():
                try:
                    ticker = yf.Ticker(config['ticker'])
                    hist = ticker.history(period="2d")
                    if not hist.empty:
                        latest = hist.iloc[-1]
                        prev = hist.iloc[-2] if len(hist) > 1 else latest
                        change_pct = (latest['Close'] - prev['Close']) / prev['Close'] * 100 if prev['Close'] > 0 else 0.0

                        result[key] = {
                            "name": config['name'],
                            "code": config['ticker'],
                            "close": float(latest['Close']),
                            "change": float(latest['Close'] - prev['Close']),
                            "change_pct": round(float(change_pct), 2)
                        }
                except Exception as e:
                    logger.debug(f"获取 {config['name']} 失败: {e}")

            if result:
                set_cache(cache_key, result, namespace='yfinance', ttl=1800)
                logger.info(f"✅ 获取全球资产成功: {len(result)}/3")
                return {"success": True, "data": result, "source": "yfinance", "cached": False}
            else:
                return {"success": False, "data": None, "error": "无法获取全球资产", "source": "none", "cached": False}

        except ImportError:
            logger.error("yfinance 未安装，无法获取全球资产")
            return {"success": False, "data": None, "error": "yfinance not installed", "source": "none", "cached": False}
        except Exception as e:
            logger.error(f"获取全球资产失败: {e}")
            return {"success": False, "data": None, "error": str(e), "source": "none", "cached": False}
