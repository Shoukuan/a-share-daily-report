
"""
数据采集模块
从各数据源采集原始数据，处理降级逻辑
"""

import os
import threading
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
    urlopen_json_with_retry,
)

logger = get_logger('data_fetcher')

class DataFetcher:
    _spot_cache = None
    _spot_tried = False
    _akshare_unavailable = False
    _spot_lock = threading.Lock()

    def __init__(self, config):
        self.config = config
        # 确保 .env 文件被加载（支持子进程环境）
        self._load_env()
        self._init_akshare()
        self._init_tushare()
        mx_ready = bool(os.getenv('MX_APIKEY'))
        ts_ready = bool(os.getenv('TUSHARE_TOKEN'))
        log_event(
            logger,
            "info",
            "data_fetcher_init",
            mx_apikey_set=mx_ready,
            tushare_token_set=ts_ready,
        )
        if not mx_ready:
            logger.warning("⚠️ MX_APIKEY 未设置，期指数据可能无法获取")
        if not ts_ready:
            logger.warning("⚠️ TUSHARE_TOKEN 未设置，资金流向数据可能无法获取")

    def _load_env(self):
        """加载 .env 文件到环境变量"""
        env_path = load_project_env(override=False)
        if env_path:
            logger.debug(f"✅ 已加载 .env 文件: {env_path}")

    def _build_index_data(
        self,
        index_code,
        date_str,
        close,
        open_price,
        high,
        low,
        pre_close,
        change,
        change_pct,
        vol=0,
        amount=0,
        source="",
    ):
        """统一构建指数数据结构（dataclass -> dict）。"""
        item = IndexData(
            ts_code=index_code,
            name=self._get_index_name(index_code),
            trade_date=date_str,
            close=float(close),
            open=float(open_price),
            high=float(high),
            low=float(low),
            pre_close=float(pre_close),
            change=float(change),
            change_pct=float(change_pct),
            vol=int(vol or 0),
            amount=int(amount or 0),
            source=source,
        )
        return asdict(item)

    def _init_akshare(self):
        try:
            # 清空代理环境变量，让 akshare 走系统直连（Clash tun 模式）
            # 环境变量中的 HTTP_PROXY 会强制 Python requests 走代理，绕过 Clash 域名规则
            for var in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy',
                        'ALL_PROXY', 'all_proxy'):
                if var in os.environ:
                    del os.environ[var]
            import akshare as ak
            self.ak = ak
            logger.info(f"✅ akshare 已加载 (版本: {ak.__version__})")
        except ImportError as e:
            logger.warning(f"⚠️ akshare 未安装，将使用模拟数据: {e}")
            self.ak = None

    def _init_tushare(self):
        """初始化 tushare（用于资金流向等数据）"""
        try:
            import tushare as ts
            token = os.getenv('TUSHARE_TOKEN')
            if token:
                ts.set_token(token)
                self.ts = ts
                self.pro = ts.pro_api(token)  # 保存 pro 实例，方便直接调用接口
                logger.info(f"✅ tushare 已初始化 (版本: {ts.__version__})")
            else:
                self.ts = None
                self.pro = None
                logger.warning("⚠️ TUSHARE_TOKEN 未设置，资金流向数据可能无法获取")
        except ImportError:
            self.ts = None
            self.pro = None
            logger.warning("⚠️ tushare 未安装，资金流向数据不可用")
        except Exception as e:
            self.ts = None
            self.pro = None
            logger.warning(f"⚠️ tushare 初始化失败，已降级跳过: {e}")


    def _get_spot_em(self):
        """Get cached spot_em DataFrame，返回 (df, error)"""
        with DataFetcher._spot_lock:
            if DataFetcher._spot_cache is not None:
                return DataFetcher._spot_cache, None
            if DataFetcher._spot_tried:
                return None, "已尝试过 stock_zh_index_spot_em，本次跳过"
            try:
                DataFetcher._spot_cache = self.ak.stock_zh_index_spot_em()
                DataFetcher._spot_tried = True
                return DataFetcher._spot_cache, None
            except Exception as e:
                DataFetcher._spot_tried = True
                err_str = str(e)
                if 'RemoteDisconnected' in err_str or 'push2.eastmoney.com' in err_str:
                    DataFetcher._akshare_unavailable = True
                    logger.warning(f"akshare 东方财富接口不可用: {e}")
                return None, str(e)

    def get_index_data(self, index_code, dt):
        """
        获取指数数据（优先 akshare 实时行情含成交额 → baostock 兜底 → yfinance）
        三层数据源，确保指数数据不断层
        """
        date_str = format_date(dt)
        cache_key = f'index_{index_code}_{date_str}'

        cached = get_cache(cache_key, namespace='akshare', ttl=3600)
        if cached is not None:
            return {"success": True, "data": cached, "source": "cache", "cached": True}

        # ── 第一层：akshare stock_zh_index_spot_em（实时行情，含成交额）──
        if self.ak and not DataFetcher._akshare_unavailable:
            df_spot, spot_err = self._get_spot_em()
            if df_spot is not None:
                try:
                    ak_code = index_code.replace('.SH', '').replace('.SZ', '').replace('.BJ', '')
                    matched = df_spot[df_spot['代码'].astype(str) == str(ak_code)]
                    if not matched.empty:
                        row = matched.iloc[0]
                        pre_close = float(row['昨收']) if '昨收' in df_spot.columns and row['昨收'] not in ['-', '', None] and pd.notna(row['昨收']) else float(row['最新价']) / (1 + float(row['涨跌幅'])/100)
                        change_pct = float(row['涨跌幅'])
                        amount_raw = row.get('成交额', 0)
                        try:
                            amount_val = float(amount_raw)
                        except:
                            amount_val = 0
                        data = self._build_index_data(
                            index_code=index_code,
                            date_str=date_str,
                            close=float(row['最新价']),
                            open_price=float(row['今开']) if pd.notna(row.get('今开', None)) and row.get('今开', None) not in ['-', None] else float(row['最新价']),
                            high=float(row['最高']) if pd.notna(row.get('最高', None)) and row.get('最高', None) not in ['-', None] else float(row['最新价']),
                            low=float(row['最低']) if pd.notna(row.get('最低', None)) and row.get('最低', None) not in ['-', None] else float(row['最新价']),
                            pre_close=round(pre_close, 2),
                            change=round(float(row.get('涨跌额', 0)) if pd.notna(row.get('涨跌额', 0)) else 0, 4),
                            change_pct=change_pct,
                            vol=int(float(row.get('成交量', 0)) if pd.notna(row.get('成交量', 0)) else 0),
                            amount=int(amount_val),
                            source="akshare_spot",
                        )
                        set_cache(cache_key, data, namespace='akshare', ttl=3600)
                        logger.info(f"✅ akshare(spot) 获取指数成功: {index_code} close={data['close']} change={change_pct}% amount={amount_val/1e8:.0f}亿")
                        return {"success": True, "data": data, "source": "akshare_spot", "cached": False}
                    else:
                        logger.warning(f"⚠️ akshare spot 未找到指数: {index_code}")
                except Exception as e:
                    logger.warning(f"akshare spot 获取指数失败: {e}")
            else:
                # _get_spot_em 返回 None（已失败或被跳过）
                if not spot_err.startswith("已尝试过"):
                    logger.warning(f"akshare spot 获取指数跳过: {spot_err}")

        # ── 第二层：baostock 兜底（免费无限制，国内稳定）──
        result_baostock = self._get_index_data_baostock(index_code, dt)
        if result_baostock.get('success'):
            return result_baostock

        # ── 第三层：yfinance（海外源，无成交额）──
        return self._get_index_data_yfinance(index_code, dt)

    def _get_index_data_baostock(self, index_code, dt, cache_key=None):
        """
        使用 baostock 获取指数日线数据（第二层兜底）
        代码格式转换：000001.SH → sh.000001，399001.SZ → sz.399001
        """
        date_str = format_date(dt)
        if cache_key is None:
            cache_key = f'index_{index_code}_{date_str}'

        # 线程池执行带超时的查询
        def _baostock_worker():
            import baostock as bs
            # 代码格式转换
            if '.SH' in index_code:
                bs_code = 'sh.' + index_code.replace('.SH', '')
            elif '.SZ' in index_code:
                bs_code = 'sz.' + index_code.replace('.SZ', '')
            elif '.BJ' in index_code:
                bs_code = 'bj.' + index_code.replace('.BJ', '')
            else:
                return {"success": False, "data": None, "error": "不支持的代码格式", "source": "baostock"}

            # 登录 baostock
            lg = bs.login()
            if lg.error_code != '0':
                return {"success": False, "data": None, "error": f"baostock 登录失败: {lg.error_msg}", "source": "baostock"}

            try:
                # 查询近 5 天数据（确保能拿到最新交易日）
                end_date = parse_date(date_str) + timedelta(days=3)
                start_date = parse_date(date_str) - timedelta(days=7)
                rs = bs.query_history_k_data_plus(
                    bs_code,
                    'date,open,high,low,close,volume,amount,turn,pctChg',
                    start_date=start_date.strftime('%Y-%m-%d'),
                    end_date=end_date.strftime('%Y-%m-%d'),
                    frequency='d',
                    adjustflag='3'
                )
                if rs.error_code != '0':
                    return {"success": False, "data": None, "error": f"baostock 查询失败: {rs.error_msg}", "source": "baostock"}

                data_list = []
                while (rs.error_code == '0') & rs.next():
                    data_list.append(rs.get_row_data())

                if not data_list:
                    return {"success": False, "data": None, "error": "baostock 无数据", "source": "baostock"}

                # 取最新一条（最后一个交易日）
                latest = data_list[-1]
                row = dict(zip(rs.fields, latest))
                close = float(row['close'])
                pct_chg = float(row['pctChg']) if row['pctChg'] else 0.0

                data = self._build_index_data(
                    index_code=index_code,
                    date_str=row['date'],
                    close=close,
                    open_price=float(row['open']),
                    high=float(row['high']),
                    low=float(row['low']),
                    pre_close=round(close / (1 + pct_chg / 100), 2) if pct_chg != -100 else close,
                    change=round(close * pct_chg / 100, 4),
                    change_pct=pct_chg,
                    vol=int(float(row['volume'])) if row['volume'] else 0,
                    amount=int(float(row['amount'])) if row['amount'] else 0,
                    source="baostock",
                )

                set_cache(cache_key, data, namespace='baostock', ttl=3600)
                logger.info(f"✅ baostock 获取指数成功: {index_code} close={data['close']} change={pct_chg}% amount={float(row['amount'])/1e8:.0f}亿")
                return {"success": True, "data": data, "source": "baostock", "cached": False}

            finally:
                try:
                    bs.logout()
                except Exception:
                    pass

        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_baostock_worker)
                try:
                    result = future.result(timeout=TIMEOUTS['baostock_query_sec'])
                    return result
                except FuturesTimeoutError:
                    timeout_sec = TIMEOUTS['baostock_query_sec']
                    logger.warning(f"baostock 查询 {index_code} 超时（{timeout_sec}s），跳过该指数")
                    return {"success": False, "data": None, "error": f"baostock query timeout ({timeout_sec}s)", "source": "baostock"}
        except ImportError:
            logger.debug("baostock 未安装，跳过")
            return {"success": False, "data": None, "error": "baostock not installed", "source": "baostock"}
        except Exception as e:
            logger.warning(f"baostock 获取指数失败: {e}")
            return {"success": False, "data": None, "error": str(e), "source": "baostock"}

    def _get_index_data_yfinance(self, index_code, dt):
        """yfinance fallback"""
        date_str = format_date(dt)
        cache_key = f'index_{index_code}_{date_str}'
        try:
            import yfinance as yf
            yf_code = YFINANCE_INDEX_MAP.get(index_code, index_code)
            ticker = yf.Ticker(yf_code)
            hist = ticker.history(period="5d")
            if not hist.empty:
                # 取最近两个收盘价，避免节假日返回 nan
                closes = hist['Close'].dropna()
                if len(closes) >= 2:
                    latest_close = float(closes.iloc[-1])
                    prev_close = float(closes.iloc[-2])
                    # 若两值完全相同（节假日重复），往前再取一行
                    if latest_close == prev_close and len(closes) >= 3:
                        prev_close = float(closes.iloc[-3])
                    change = latest_close - prev_close
                    change_pct = round(change / prev_close * 100, 2) if prev_close != 0 else 0.0
                    latest = hist.iloc[-1]
                    data = self._build_index_data(
                        index_code=index_code,
                        date_str=format_date(latest.name),
                        close=latest_close,
                        open_price=float(latest['Open']),
                        high=float(latest['High']),
                        low=float(latest['Low']),
                        pre_close=prev_close,
                        change=round(change, 2),
                        change_pct=change_pct,
                        vol=int(latest['Volume']) if 'Volume' in latest else 0,
                        amount=0,
                        source="yfinance",
                    )
                    set_cache(cache_key, data, namespace='yfinance', ttl=3600)
                    logger.info(f"✅ yfinance 获取指数: {index_code} change={change_pct}%")
                    return {"success": True, "data": data, "source": "yfinance", "cached": False}
        except Exception as e:
            logger.warning(f"yfinance 获取指数失败: {e}")

        return {"success": False, "data": None, "error": "无法获取指数数据", "source": "none", "cached": False}

    def _convert_index_code(self, index_code):
        if '.SH' in index_code:
            return 'sh' + index_code.replace('.SH', '')
        elif '.SZ' in index_code:
            return 'sz' + index_code.replace('.SZ', '')
        return index_code

    def _get_index_name(self, index_code):
        return INDEX_NAMES.get(index_code, index_code)

    def get_market_sentiment(self, dt, index_cache=None):
        date_str = format_date(dt)
        cache_key = f'sentiment_{date_str}'
        cached = get_cache(cache_key, namespace='akshare', ttl=3600)
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

                set_cache(cache_key, data, namespace='akshare', ttl=3600)
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

            if cache_key:
                set_cache(cache_key, data, namespace='akshare', ttl=3600)
            logger.info(f"✅ tushare 情绪: 涨停{limit_up_count}/连板{max_consec_up}/跌停{limit_down_count}/炸板{failed_limit_up}")
            return {"success": True, "data": data, "source": "tushare", "cached": False}

        except Exception as e:
            logger.warning(f"tushare 获取情绪数据失败: {e}")
            return {"success": False, "data": None, "error": str(e), "source": "none"}

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

    def get_us_market(self):
        """
        获取美股指数和中概股数据
        优先级：yfinance
        失败返回错误，无降级数据
        """
        cache_key = 'us_market'
        cached = get_cache(cache_key, namespace='yfinance', ttl=1800)
        if cached is not None:
            return {"success": True, "data": cached, "source": "cache", "cached": True}

        # 尝试 yfinance
        try:
            import yfinance as yf

            # 定义指数和对应代码
            indices_config = {
                'nasdaq': '^IXIC',
                'sp500': '^GSPC',
                'dow': '^DJI'
            }

            # 中概股（主要港股）
            chinadotcom_config = {
                'tencent': '0700.HK',
                'alibaba': 'BABA',
                'pdd': 'PDD'
            }

            indices_data = {}
            for name, ticker in indices_config.items():
                try:
                    stock = yf.Ticker(ticker)
                    info = stock.info
                    # 获取快速信息（避免大量历史数据下载）
                    hist = stock.history(period="2d")
                    if not hist.empty:
                        latest = hist.iloc[-1]
                        prev = hist.iloc[-2] if len(hist) > 1 else latest
                        change = latest['Close'] - prev['Close']
                        change_pct = change / prev['Close'] * 100 if prev['Close'] > 0 else 0  # 统一存百分比，如 1.16

                        indices_data[name] = {
                            "name": info.get('shortName', name.upper()),
                            "code": ticker,
                            "close": float(latest['Close']),
                            "change": float(change),
                            "change_pct": round(float(change_pct), 2)
                        }
                except Exception as e:
                    logger.debug(f"获取 {ticker} 失败: {e}")
                    continue

            # 获取中概股数据（简化：只看腾讯）
            cdc_data = {}
            for name, ticker in chinadotcom_config.items():
                try:
                    stock = yf.Ticker(ticker)
                    hist = stock.history(period="2d")
                    if not hist.empty:
                        latest = hist.iloc[-1]
                        prev = hist.iloc[-2] if len(hist) > 1 else latest
                        change_pct = (latest['Close'] - prev['Close']) / prev['Close'] * 100 if prev['Close'] > 0 else 0  # 存百分比
                        cdc_data[name] = {
                            "name": stock.info.get('shortName', name),
                            "code": ticker,
                            "close": float(latest['Close']),
                            "change": float(latest['Close'] - prev['Close']),
                            "change_pct": round(float(change_pct), 2)
                        }
                except Exception as e:
                    logger.debug(f"获取 {ticker} 失败: {e}")
                    continue

            result = {
                "update_time": format_date(datetime.now(), '%Y-%m-%d %H:%M:%S'),
                "indices": indices_data,
                "chinadotcom": cdc_data
            }

            set_cache(cache_key, result, namespace='yfinance', ttl=1800)
            logger.info(f"✅ yfinance 获取美股数据成功")
            return {"success": True, "data": result, "source": "yfinance", "cached": False}

        except ImportError:
            logger.error("yfinance 未安装，无法获取美股数据")
            return {"success": False, "data": None, "error": "yfinance not installed", "source": "none", "cached": False}
        except Exception as e:
            logger.error(f"yfinance 获取美股数据失败: {e}")
            return {"success": False, "data": None, "error": str(e), "source": "yfinance", "cached": False}

    def get_sector_data(self, dt):
        """
        获取行业板块和概念板块的Top 5 + 领涨股/龙头股
        数据源：同花顺（ths）— 不依赖 push2.eastmoney.com，不受代理影响
        """
        date_str = format_date(dt)
        cache_key = f'sectors_{date_str}'
        cached = get_cache(cache_key, namespace='akshare', ttl=3600)
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
                set_cache(cache_key, result, namespace='akshare', ttl=3600)
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
        cached = get_cache(cache_key, namespace='akshare', ttl=3600)
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
                    set_cache(cache_key, result, namespace='akshare', ttl=3600)
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
                set_cache(cache_key, result, namespace='akshare', ttl=3600)
            logger.info(f"✅ tushare 龙虎榜: {len(result)} 条")
            return {"success": True, "data": result, "source": "tushare", "cached": False}

        except Exception as e:
            logger.warning(f"tushare 龙虎榜获取失败: {e}")
            return {"success": False, "data": None, "error": str(e), "source": "none"}

    def get_news(self, dt, limit=10):
        """
        获取财经新闻
        优先级：mx-search
        失败返回错误，无降级数据
        """
        date_str = format_date(dt, '%Y-%m-%d')
        cache_key = f'news_{date_str}'
        cached = get_cache(cache_key, namespace='mx_search', ttl=3600)
        if cached is not None:
            logger.debug(f"从缓存获取新闻数据: {date_str}")
            return {"success": True, "data": cached[:limit], "source": "cache", "cached": True}

        # 尝试 mx-search
        self._load_env()
        mx_api_key = self._get_mx_apikey()
        if mx_api_key:
            try:
                def _do_news_request(api_key):
                    url = 'https://mkapi2.dfcfs.com/finskillshub/api/claw/news-search'
                    headers = {'Content-Type': 'application/json', 'apikey': api_key}
                    payload = {'query': f'A股 {date_str} 财经新闻'}
                    return post_json_with_retry(
                        url=url,
                        payload=payload,
                        headers=headers,
                        timeout=TIMEOUTS['mx_news_sec'],
                        retries=RETRY_POLICY['http_retries'],
                        backoff_seconds=RETRY_POLICY['http_backoff_seconds'],
                    )

                resp = _do_news_request(mx_api_key)
                if resp.status_code == 200:
                    result = resp.json()
                    api_status = result.get('status', 0)
                    # status=113 调用耗尽，切换备用 key 重试
                    if api_status == 113:
                        self._handle_mx_status(api_status, result.get('message', ''))
                        retry_key = self._get_mx_apikey()
                        if retry_key and retry_key != mx_api_key:
                            logger.info("mx-search 使用备用key重试新闻获取")
                            resp = _do_news_request(retry_key)
                            if resp.status_code == 200:
                                result = resp.json()
                                api_status = result.get('status', 0)
                    if api_status != 0:
                        logger.warning(f"mx-search API error status={api_status}: {result.get('message','')}")
                    else:
                        # 妙想返回结构：{status, data: {data: {llmSearchResponse: {data: [...]}}}}
                        news_items = self._parse_mx_search_news(result, date_str)
                        if news_items:
                            set_cache(cache_key, news_items, namespace='mx_search', ttl=3600)
                            logger.info(f"✅ mx-search 获取新闻成功: {len(news_items)} 条")
                            return {"success": True, "data": news_items[:limit], "source": "mx-search", "cached": False}
                else:
                    logger.warning(f"mx-search 请求失败: {resp.status_code}")
            except requests.Timeout:
                logger.warning("mx-search 请求超时")
            except requests.ConnectionError as e:
                logger.warning(f"mx-search 连接失败: {e}")
            except requests.RequestException as e:
                logger.warning(f"mx-search 请求异常: {e}")
            except Exception as e:
                logger.warning(f"mx-search 获取新闻失败: {e}")

        # mx-search 不可用或失败
        return {"success": False, "data": None, "error": "无法获取新闻数据", "source": "none", "cached": False}

    def _parse_mx_search_news(self, result, date_str):
        """解析 mx-search 返回结果"""
        news_list = []

        # 解析路径：result['data']['data']['llmSearchResponse']['data']
        if isinstance(result, dict):
            outer_data = result.get('data', {})
            inner_data = outer_data.get('data', {})
            llm_response = inner_data.get('llmSearchResponse', {})
            items = llm_response.get('data', [])

            for item in items[:20]:
                title = item.get('title', '')
                if title:
                    content = item.get('content', '')
                    date = item.get('date', '')
                    source = item.get('source', '妙想资讯')
                    secu_list = item.get('secuList', [])

                    related_stocks = [s.get('secuName') for s in secu_list if s.get('secuName')]

                    news_list.append(asdict(NewsItem(
                        title=title,
                        content=content[:300],
                        source=source,
                        url=item.get('jumpUrl', ''),
                        publish_time=date if date else format_date(datetime.now(), '%Y-%m-%d %H:%M:%S'),
                        importance="high" if secu_list else "medium",
                        related_sectors=[],
                        related_stocks=related_stocks[:3],
                    )))

        return news_list
    def get_futures_data(self):
        """
        获取期指数据（A50期指、沪深300期指）
        优先级：mx-data → 新浪(CSI300) → yfinance(A50)
        失败返回错误，无降级数据
        返回结构：
        {
          "update_time": "2026-03-29 19:20:00",
          "futures": {
            "A50": {"name": "A50期指", "code": "CFF_RE_IF", "change_pct": 0.63, "impact": "..."},
            "CSI300": {"name": "沪深300期指", "code": "CFF_RE_IF", "change_pct": 0.58, "impact": "..."}
          }
        }
        """
        cache_key = 'futures_data'
        cached = get_cache(cache_key, namespace='mx_data', ttl=600)  # 10分钟缓存，期指变化频繁
        if cached is not None:
            return {"success": True, "data": cached, "source": "cache", "cached": True}

        # 初始化结果结构
        futures_data = {
            "update_time": format_date(datetime.now(), '%Y-%m-%d %H:%M:%S'),
            "futures": {}
        }
        sources = []

        # 优先级1：使用 mx-data Skill（需要 MX_APIKEY）
        self._load_env()  # 确保 .env 已加载
        mx_apikey = os.getenv('MX_APIKEY')
        logger.debug(f"MX_APIKEY状态: {'已设置' if mx_apikey else '未设置'}")
        if mx_apikey:
            try:
                url = "https://mkapi2.dfcfs.com/finskillshub/api/claw/query"
                headers = {"apikey": mx_apikey}

                # 并行查询沪深300和A50（避免串行超时叠加）
                queries = [
                    ("沪深300期货 最新价 涨跌幅", "CSI300"),
                    ("A50期货 最新价 涨跌幅", "A50")
                ]

                from concurrent.futures import ThreadPoolExecutor, as_completed

                def _fetch_one(query_key):
                    query, key = query_key
                    logger.debug(f"查询期指: {query}")
                    payload = {"toolQuery": query}
                    r = post_json_with_retry(
                        url=url,
                        payload=payload,
                        headers=headers,
                        timeout=TIMEOUTS['mx_futures_sec'],
                        retries=RETRY_POLICY['http_retries'],
                        backoff_seconds=RETRY_POLICY['http_backoff_seconds'],
                    )
                    if r.status_code == 200:
                        return key, r.json()
                    return key, None

                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures_map = {pool.submit(_fetch_one, q): q[1] for q in queries}
                    for fut in as_completed(futures_map, timeout=TIMEOUTS['mx_futures_parallel_wait_sec']):
                        try:
                            key, result = fut.result()
                            if result:
                                single_data = self._parse_mx_futures(result, key)
                                if single_data and 'futures' in single_data and key in single_data['futures']:
                                    futures_data['futures'][key] = single_data['futures'][key]
                                    logger.info(f"✅ 获取到 {key}: {single_data['futures'][key]['change_pct']}%")
                                else:
                                    logger.warning(f"⚠️ 查询 {key} 未返回有效数据")
                        except Exception as e:
                            logger.warning(f"期指单项查询失败: {e}")

                if futures_data['futures']:
                    sources.append('mx-data')
                else:
                    logger.warning("mx-data 未返回任何期指数据")
            except requests.Timeout:
                logger.warning("mx-data 期指请求超时")
            except requests.ConnectionError as e:
                logger.warning(f"mx-data 期指连接失败: {e}")
            except requests.RequestException as e:
                logger.warning(f"mx-data 期指请求异常: {e}")
            except Exception as e:
                logger.warning(f"mx-data 获取期指失败: {e}")
                import traceback
                logger.debug(traceback.format_exc())

        # 优先级2：如果A50缺失，用 mx-data 查上证50实时行情作为替代
        if not futures_data['futures'].get('A50') and mx_apikey:
            logger.info("A50期指未获取到，改用 mx-data 查上证50实时行情作为替代")
            try:
                url2 = "https://mkapi2.dfcfs.com/finskillshub/api/claw/query"
                resp2 = post_json_with_retry(
                    url=url2,
                    payload={"toolQuery": "上证50 最新价 涨跌幅"},
                    headers={"apikey": mx_apikey},
                    timeout=TIMEOUTS['mx_futures_a50_fallback_sec'],
                    retries=RETRY_POLICY['http_retries'],
                    backoff_seconds=RETRY_POLICY['http_backoff_seconds'],
                )
                if resp2.status_code == 200:
                    d2 = resp2.json()
                    tables2 = d2['data']['data']['searchDataResultDTO']['dataTableDTOList']
                    for t2 in tables2:
                        nm2 = t2.get('nameMap', {})
                        td2 = t2.get('table', {})
                        # 找涨跌幅字段
                        for fid, fname in nm2.items():
                            if fname == '涨跌幅':
                                vals = td2.get(fid, [])
                                if vals and vals[0] not in ['-', '', None]:
                                    chg = float(str(vals[0]).strip().rstrip('%'))
                                    futures_data['futures']['A50'] = asdict(FuturesItem(
                                        name="上证50(A50替代)",
                                        code="000016.SH",
                                        change_pct=round(chg, 2),
                                        impact=self._generate_impact_text(chg, "上证50"),
                                    ))
                                    sources.append('mx-data(A50替代)')
                                    logger.info(f"✅ mx-data 上证50替代A50: {chg}%")
                                    break
                        if futures_data['futures'].get('A50'):
                            break
            except Exception as e:
                logger.warning(f"mx-data 上证50替代失败: {e}")

        # 优先级3：如果沪深300缺失，尝试新浪财经API
        if not futures_data['futures'].get('CSI300'):
            try:
                import urllib.request
                url = "http://hq.sinajs.cn/list=CFF_RE_IF"
                content = urllib.request.urlopen(url, timeout=TIMEOUTS['sina_sec']).read().decode('gbk')
                parts = content.split('"')[1].split(',')
                if len(parts) >= 6:
                    change_pct_str = parts[5]  # 涨跌幅百分比
                    change_pct = float(change_pct_str) if change_pct_str else 0.0

                    futures_data['futures']['CSI300'] = asdict(FuturesItem(
                        name="沪深300期指",
                        code="CFF_RE_IF",
                        change_pct=change_pct,
                        impact=self._generate_impact_text(change_pct, "沪深300"),
                    ))
                    sources.append('sina(CSI300)')
                    logger.info(f"✅ 新浪财经API 获取 CSI300 数据成功")
            except Exception as e:
                logger.warning(f"新浪财经API 获取 CSI300 失败: {e}")

        # 检查：至少有一个期指数据
        if futures_data['futures']:
            set_cache(cache_key, futures_data, namespace='mx_data', ttl=600)
            source_str = ' + '.join(sources) if sources else 'unknown'
            logger.info(f"✅ 期指数据获取成功（来源: {source_str}）")
            return {"success": True, "data": futures_data, "source": source_str, "cached": False}

        # 无法获取期指数据
        return {"success": False, "data": None, "error": "无法获取期指数据", "source": "none", "cached": False}

    def _is_trading_hours(self):
        """
        判断当前是否在 A 股交易时间内（9:25-15:05，周一到周五）
        仅在交易时间内才使用 mx-data 实时行情，避免返回昨日数据
        """
        now = datetime.now()
        if now.weekday() >= 5:  # 周六/周日
            return False
        t = now.hour * 100 + now.minute
        return 925 <= t <= 1505

    def _get_mx_apikey(self):
        """
        获取有效的 MX API Key，主 key 耗尽（status=113）时自动切换备用 key。
        通过实例变量 _mx_key_exhausted 记录主 key 是否已耗尽。
        """
        self._load_env()
        if getattr(self, '_mx_key_exhausted', False):
            backup = os.getenv('MX_APIKEY_BACKUP', '')
            if backup:
                return backup
        return os.getenv('MX_APIKEY', '')

    def _handle_mx_status(self, status, message):
        """
        处理 mx-data API 业务状态码。
        status=113: 调用次数耗尽，标记主 key 并切换备用 key。
        非0状态: 抛出异常。
        """
        if status == 0:
            return
        if status == 113:
            # 调用耗尽，切换备用 key
            if not getattr(self, '_mx_key_exhausted', False):
                self._mx_key_exhausted = True
                backup = os.getenv('MX_APIKEY_BACKUP', '')
                if backup:
                    logger.warning(f"mx-data 主key调用次数耗尽(status=113)，已切换到备用key")
                else:
                    logger.warning(f"mx-data 主key调用次数耗尽(status=113)，备用key未配置")
        raise RuntimeError(f"mx-data API error status={status}: {message}")

    def _fetch_spot_from_mx_data(self, watchlist):
        """
        使用 mx-data 批量获取自选股行情
        返回 dict: {代码(不含后缀): {price, change_pct, amount, amplitude, turnover, volume_ratio}}
        """
        self._load_env()
        mx_key = self._get_mx_apikey()
        if not mx_key:
            raise ValueError("MX_APIKEY 未设置")

        import json, urllib.request, urllib.error

        result = {}
        for stock in watchlist:
            code_raw = stock.get('code', '')
            name = stock.get('name', code_raw)
            ak_code = code_raw.split('.')[0]

            try:
                query = f"{name}今日涨跌幅 最新价 成交额 换手率 量比 振幅 5日均线 20日均线"

                def _do_mx_request(api_key):
                    payload = json.dumps({"toolQuery": query}).encode('utf-8')
                    req = urllib.request.Request(
                        'https://mkapi2.dfcfs.com/finskillshub/api/claw/query',
                        data=payload,
                        headers={'Content-Type': 'application/json', 'apikey': api_key},
                        method='POST'
                    )
                    return urlopen_json_with_retry(
                        req=req,
                        timeout=TIMEOUTS['mx_watchlist_sec'],
                        retries=RETRY_POLICY['http_retries'],
                        backoff_seconds=RETRY_POLICY['http_backoff_seconds'],
                    )

                # 用当前有效 key 请求（已耗尽时自动取备用 key）
                cur_key = self._get_mx_apikey()
                raw = _do_mx_request(cur_key)

                # 检查业务状态码；status=113 时切换备用 key 并重试一次
                api_status = raw.get('status', 0)
                if api_status != 0:
                    self._handle_mx_status(api_status, raw.get('message', ''))
                    # _handle_mx_status 切换了 key，重试
                    retry_key = self._get_mx_apikey()
                    if retry_key and retry_key != cur_key:
                        logger.info(f"mx-data 使用备用key重试: {name}")
                        raw = _do_mx_request(retry_key)
                        api_status = raw.get('status', 0)
                        if api_status != 0:
                            raise RuntimeError(f"mx-data 备用key也失败 status={api_status}: {raw.get('message','')}")
                    else:
                        raise RuntimeError(f"mx-data 无可用备用key，放弃")

                # 正确解析路径：raw → data → data → searchDataResultDTO → dataTableDTOList
                outer = raw.get('data') or {}
                if not isinstance(outer, dict):
                    logger.warning(f"mx-data data 层非dict: {type(outer)}, 跳过")
                    continue
                inner = outer.get('data') or {}
                if not isinstance(inner, dict):
                    logger.warning(f"mx-data data.data 层非dict: {type(inner)}, 跳过")
                    continue
                search_dto = inner.get('searchDataResultDTO', inner)
                tables = search_dto.get('dataTableDTOList', [])

                row = {}
                for tbl in tables:
                    name_map = tbl.get('nameMap', {})
                    table_data = tbl.get('table', {})
                    for fid, fname in name_map.items():
                        vals = table_data.get(fid, [None])
                        v = vals[0] if vals else None
                        if v is None:
                            continue
                        fn = str(fname)
                        # 统一去除百分号，转 float
                        try:
                            v_float = float(str(v).replace('%', '').strip())
                        except (ValueError, TypeError):
                            continue
                        if '最新价' in fn or '收盘' in fn:
                            row['price'] = v_float
                        elif '涨跌幅' in fn:
                            row['change_pct'] = v_float
                        elif '成交额' in fn:
                            row['amount'] = v_float
                        elif '振幅' in fn:
                            row['amplitude'] = v_float
                        elif '换手率' in fn:
                            row['turnover'] = v_float
                        elif '量比' in fn:
                            row['volume_ratio'] = v_float
                        elif '5日' in fn and ('均线' in fn or 'MA' in fn.upper()):
                            row['ma5'] = v_float
                        elif '20日' in fn and ('均线' in fn or 'MA' in fn.upper()):
                            row['ma20'] = v_float

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

    def _parse_mx_futures(self, result, target_key=None):
        """
        解析 mx-data 期指响应
        target_key: 'CSI300' 或 'A50'，如果传入则只返回对应 key 的数据，否则返回完整结构
        """
        futures_data = {
            "update_time": format_date(datetime.now(), '%Y-%m-%d %H:%M:%S'),
            "futures": {}
        }

        try:
            # 解析路径：result['data']['data']['searchDataResultDTO']['dataTableDTOList']
            outer = result.get('data', {})
            inner = outer.get('data', {})
            search_dto = inner.get('searchDataResultDTO', {})

            # 调试：记录完整结构
            logger.debug(f"mx-data 期指响应结构: outer_keys={list(outer.keys())}, inner_keys={list(inner.keys())}, search_dto_keys={list(search_dto.keys())}")

            tables = search_dto.get('dataTableDTOList', [])

            if not tables:
                # 尝试其他可能的路径
                tables = inner.get('dataTableDTOList', []) or result.get('dataTableDTOList', [])
                logger.debug(f"尝试备用路径获取 tables: 找到 {len(tables)} 条")

            for table in tables:
                title = table.get('title', '').lower()
                name_map = table.get('nameMap', {})
                table_data = table.get('table', {})

                logger.debug(f"期指表格: title={title}, nameMap={name_map}, table_keys={list(table_data.keys())}")

                # 通过 nameMap 查找涨跌幅字段
                change_pct = 0.0
                close_price = None

                # 方法1: 在 nameMap 中查找"涨跌幅"
                for field_id, field_name in name_map.items():
                    if field_name == '涨跌幅':
                        values = table_data.get(field_id, [])
                        if values and values[0] not in ['-', '', None]:
                            # 兼容带 % 的字符串，如 '-0.23%' 或 '0.5'
                            try:
                                val_str = str(values[0]).strip().rstrip('%')
                                change_pct = float(val_str)
                            except (ValueError, TypeError):
                                change_pct = 0.0
                        break
                    elif field_name == '收盘价':
                        values = table_data.get(field_id, [])
                        if values and values[0] not in ['-', '', None]:
                            try:
                                close_price = float(str(values[0]).strip().replace(',', ''))
                            except (ValueError, TypeError):
                                close_price = None

                logger.debug(f"解析表格: title={title}, change_pct={change_pct}, close_price={close_price}")

                # entityName 在表格外层，不在 nameMap 里
                entity_name = table.get('entityName', '').lower()

                # 判断是A50还是沪深300（title 和 entityName 同时匹配）
                future_key = None
                if 'a50' in title or 'a50' in entity_name:
                    future_key = 'A50'
                elif '沪深300' in title or '沪深300' in entity_name or 'hs300' in title or 'csi300' in title:
                    future_key = 'CSI300'

                if future_key:
                    # 如果指定了 target_key，且不匹配则跳过
                    if target_key and future_key != target_key:
                        continue

                    # 优先取"最新价"表（headName 含今日时间，字段为 f2/f3 而非数字ID）
                    # 判断：nameMap 含 f2/f3 这类短字段 ID 的是实时行情表，数字ID是历史收盘
                    is_realtime = any(k.startswith('f') for k in name_map.keys())
                    if future_key in futures_data['futures'] and not is_realtime:
                        # 已有数据且当前表是历史表，跳过不覆盖
                        logger.debug(f"跳过历史收盘表，保留实时行情: {future_key}")
                        continue

                    item = asdict(FuturesItem(
                        name="A50期指" if future_key == 'A50' else "沪深300期指",
                        code="CFF_RE_IF",
                        change_pct=change_pct,
                        impact=self._generate_impact_text(change_pct, "A50" if future_key == 'A50' else "沪深300"),
                    ))
                    item["is_realtime"] = is_realtime
                    futures_data['futures'][future_key] = item
                    logger.info(f"✅ 解析到{future_key}: {change_pct}% ({'实时' if is_realtime else '历史收盘'})")

        except Exception as e:
            logger.warning(f"解析 mx-data 期指响应失败: {e}")
            import traceback
            logger.debug(traceback.format_exc())

        # 如果指定了 target_key 且没有找到，返回 None
        if target_key and target_key not in futures_data['futures']:
            return None

        return futures_data

    def _generate_impact_text(self, change_pct, name):
        """根据涨跌幅生成影响解读"""
        if change_pct > 0.5:
            return f"{name}强势上涨，对A股开盘有正面提振"
        elif change_pct > 0:
            return f"{name}小幅上涨，影响中性偏多"
        elif change_pct > -0.5:
            return f"{name}小幅回调，影响有限"
        else:
            return f"{name}下跌，可能压制A股开盘情绪"
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
        if self.ak and not DataFetcher._akshare_unavailable:
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
                    DataFetcher._akshare_unavailable = True
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
        mx_apikey = os.getenv('MX_APIKEY')
        if not mx_apikey:
            return {"success": False, "data": None, "error": "MX_APIKEY 未设置", "source": "none"}

        try:
            import json
            import urllib.request

            query = "A股行业板块资金流向排名 今日主力净流入 净流入 排名 板块名称 领涨股"
            payload = json.dumps({"toolQuery": query}).encode('utf-8')
            req = urllib.request.Request(
                'https://mkapi2.dfcfs.com/finskillshub/api/claw/query',
                data=payload,
                headers={'Content-Type': 'application/json', 'apikey': mx_apikey},
                method='POST'
            )
            raw = urlopen_json_with_retry(
                req=req,
                timeout=TIMEOUTS['mx_industry_flow_sec'],
                retries=RETRY_POLICY['http_retries'],
                backoff_seconds=RETRY_POLICY['http_backoff_seconds'],
            )

            api_status = raw.get('status', 0)
            if api_status == 0:
                pass
            elif api_status == 113:
                self._mx_key_exhausted = True
                backup = os.getenv('MX_APIKEY_BACKUP', '')
                if backup:
                    logger.warning(f"mx-data 主key耗尽，切换备用key")
                    req2 = urllib.request.Request(
                        'https://mkapi2.dfcfs.com/finskillshub/api/claw/query',
                        data=payload,
                        headers={'Content-Type': 'application/json', 'apikey': backup},
                        method='POST'
                    )
                    raw = urlopen_json_with_retry(
                        req=req2,
                        timeout=TIMEOUTS['mx_industry_flow_sec'],
                        retries=RETRY_POLICY['http_retries'],
                        backoff_seconds=RETRY_POLICY['http_backoff_seconds'],
                    )
                else:
                    return {"success": False, "data": None, "error": f"mx-data 调用耗尽 status={api_status}", "source": "none"}
            else:
                return {"success": False, "data": None, "error": f"mx-data 返回异常 status={api_status}", "source": "none"}

            # 解析 mx-data 返回的数据
            outer = raw.get('data') or {}
            inner = outer.get('data') or {}
            search_dto = inner.get('searchDataResultDTO', {})
            tables = search_dto.get('dataTableDTOList', [])

            if not tables:
                return {"success": False, "data": None, "error": "mx-data 未返回行业资金流数据", "source": "none"}

            inflow_top5 = []
            outflow_top5 = []
            all_rows = []

            for tbl in tables:
                name_map = tbl.get('nameMap', {})
                table_data = tbl.get('table', {})

                # 构建列名到字段ID的映射
                col_to_id = {}
                for fid, fname in name_map.items():
                    col_to_id[str(fname)] = fid

                rank_id = col_to_id.get('排名')
                net_id = col_to_id.get('今日主力净流入-净额')

                if not rank_id or not net_id:
                    continue

                rank_vals = table_data.get(rank_id, [])
                if not rank_vals:
                    continue

                rows = []
                num_rows = max(len(table_data.get(fid, [])) for fid in table_data if fid in name_map)
                for i in range(num_rows):
                    row = {}
                    for py_name, cn_name in {'rank': '排名', 'industry_name': '名称', 'net_inflow': '今日主力净流入-净额', 'change_pct': '今日涨跌幅', 'leading_stock': '今日主力净流入最大股'}.items():
                        fid = col_to_id.get(cn_name)
                        if fid and fid in table_data:
                            vals = table_data[fid]
                            if i < len(vals) and vals[i] not in ['-', '', None]:
                                row[py_name] = vals[i]
                    if 'rank' in row:
                        try:
                            row['rank_int'] = int(row['rank'])
                            try:
                                row['net_inflow_val'] = float(row['net_inflow'])
                            except (ValueError, TypeError):
                                row['net_inflow_val'] = 0
                            rows.append(row)
                        except (ValueError, TypeError):
                            pass

                all_rows.extend(rows)

            # 按净流入绝对值排序
            all_rows.sort(key=lambda x: x.get('net_inflow_val', 0), reverse=True)

            for idx, r in enumerate(all_rows):
                entry = {
                    "rank": idx + 1,
                    "industry": str(r.get('industry_name', '')),
                    "net_inflow": r.get('net_inflow_val', 0),
                    "leading_stock": str(r.get('leading_stock', '')),
                }
                if 'change_pct' in r:
                    try:
                        entry["leading_stock_change"] = float(r['change_pct'])
                    except (ValueError, TypeError):
                        entry["leading_stock_change"] = 0

                if r.get('net_inflow_val', 0) > 0:
                    if len(inflow_top5) < 5:
                        entry['rank'] = len(inflow_top5) + 1
                        inflow_top5.append(entry)
                else:
                    if len(outflow_top5) < 5:
                        outflow_top5.append(entry)

            # 反转 outflow 使其从流出最多到最少
            outflow_top5.reverse()
            for idx, item in enumerate(outflow_top5):
                item['rank'] = idx + 1

            data = {
                "update_time": format_date(datetime.now()),
                "total_industries": len(all_rows),
                "top_net_inflow": inflow_top5,
                "top_net_outflow": outflow_top5
            }

            return {"success": True, "data": data, "source": "mx-data", "cached": False}

        except Exception as e:
            logger.warning(f"mx-data 行业资金流降级失败: {e}")
            return {"success": False, "data": None, "error": str(e), "source": "none"}

    def get_international_events(self, dt=None):
        """
        获取昨夜今晨国际事件（可能影响 A股）
        数据源：Tavily 搜索引擎 + 美股/期指联动分析
        缓存 ttl=6h（早报生成后半天有效）
        """
        if dt is None:
            dt = datetime.now()
        date_str = format_date(dt, '%Y-%m-%d')
        cache_key = f'international_events_{date_str}'
        cached = get_cache(cache_key, namespace='tavily', ttl=21600)
        if cached is not None:
            return {"success": True, "data": cached, "source": "cache", "cached": True}

        events = []

        # ── 1. Tavily 搜索昨夜国际财经事件 ──
        try:
            import json
            import urllib.request

            prev_dt = parse_date(date_str) - timedelta(days=1)
            query = f"international events affect China stock market {format_date(prev_dt, '%Y-%m-%d')} trade war oil Fed geopolitical"

            self._load_env()
            api_key = os.getenv('TAVILY_API_KEY', '')

            if api_key:
                payload = json.dumps({
                    "query": query,
                    "max_results": 5,
                    "search_depth": "basic",
                    "include_answer": True,
                    "include_raw_content": False
                }).encode('utf-8')
                req = urllib.request.Request(
                    'https://api.tavily.com/search',
                    data=payload,
                    headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {api_key}'},
                    method='POST'
                )
                with urllib.request.urlopen(req, timeout=TIMEOUTS['tavily_sec']) as resp:
                    results = json.loads(resp.read().decode('utf-8'))

                if results.get('answer'):
                    events.append({
                        "title": "📊 昨夜今晨国际事件概览",
                        "description": results['answer'][:400],
                        "category": "综合",
                        "impact_level": "medium",
                        "a_share_impact": "综合判断以下事件对A股的潜在影响",
                        "affected_sectors": ["大盘"],
                        "source": "Tavily AI 摘要",
                        "url": ""
                    })

                for r in results.get('results', []):
                    title = r.get('title', '')
                    snippet = r.get('content', '')
                    url = r.get('url', '')
                    if title and len(snippet) > 15:
                        text = title + ' ' + snippet
                        events.append({
                            "title": title[:80],
                            "description": snippet[:250],
                            "category": self._classify_event_category(text),
                            "impact_level": self._judge_impact_level(text),
                            "a_share_impact": self._generate_a_share_impact(text),
                            "affected_sectors": self._get_affected_sectors(text),
                            "source": "Tavily 搜索",
                            "url": url
                        })
        except Exception as e:
            logger.warning(f"Tavily 国际事件搜索失败: {e}")

        # ── 2. 自动补充：美股指数大幅波动 ──
        us_result = self.get_us_market()
        if us_result.get('success'):
            us_data = us_result.get('data', {})
            for name, info in us_data.get('indices', {}).items():
                label = {"nasdaq": "纳斯达克", "sp500": "标普500", "dow": "道琼斯"}.get(name, name)
                chg = info.get('change_pct', 0)
                if abs(chg) > 0.5:
                    events.append({
                        "title": f"{label}{'大涨' if chg > 0 else '大跌'}{abs(chg):.2f}%",
                        "description": f"{info.get('name', label)} 收盘 {info.get('close', 0):.0f} 点，{chg:+.2f}%",
                        "category": "海外股市",
                        "impact_level": "high" if abs(chg) > 1.5 else "medium",
                        "a_share_impact": f"{'上涨提振A股开盘情绪' if chg > 0 else '下跌可能传染A股低开，外资或减仓'}",
                        "affected_sectors": self._get_a_share_impact_sectors(name, chg),
                        "source": "yfinance",
                        "url": ""
                    })

        # ── 3. 自动补充：中概股/港股重要表现 ──
        if us_result.get('success'):
            us_data = us_result.get('data', {})
            cdc = us_data.get('chinadotcom', {})
            for name, info in cdc.items():
                chg = info.get('change_pct', 0)
                if abs(chg) > 2:
                    display = info.get('name', name).replace('Group Holding Limited', '').replace('Holdings Inc.', '').strip()
                    events.append({
                        "title": f"{display}{'大涨' if chg > 0 else '大跌'}{abs(chg):.2f}%",
                        "description": f"收盘 {chg:+.2f}%，可能传导至A股相关板块",
                        "category": "中概股",
                        "impact_level": "medium",
                        "a_share_impact": "可能传导至A股科技/互联网/新能源等同概念板块",
                        "affected_sectors": ["科技", "互联网"] if chg > 0 else ["科技", "互联网"],
                        "source": "yfinance",
                        "url": ""
                    })

        # ── 4. 期指异动 ──
        futures_result = self.get_futures_data()
        if futures_result.get('success'):
            fut = futures_result.get('data', {})
            for key, fi in fut.get('futures', {}).items():
                chg = fi.get('change_pct', 0)
                if abs(chg) > 0.5:
                    events.append({
                        "title": f"{fi.get('name', key)}期指{chg:+.2f}%",
                        "description": f"{fi.get('impact', '')}",
                        "category": "期货市场",
                        "impact_level": "high" if abs(chg) > 1 else "medium",
                        "a_share_impact": fi.get('impact', ''),
                        "affected_sectors": ["大盘蓝筹"] if "A50" in key else ["权重股"],
                        "source": "mx-data",
                        "url": ""
                    })

        if events:
            set_cache(cache_key, events, namespace='tavily', ttl=21600)
            logger.info(f"✅ 国际事件获取成功: {len(events)} 条")
            return {"success": True, "data": events, "source": "combined", "cached": False}
        else:
            logger.info("昨夜今晨暂无重大国际事件")
            return {"success": True, "data": [], "source": "none", "cached": False}

    def _classify_event_category(self, text):
        """根据事件文本自动分类"""
        return classify_event_category(text)

    def _judge_impact_level(self, text):
        """判断事件影响等级"""
        return judge_impact_level(text)

    def _generate_a_share_impact(self, text):
        """根据事件文本生成对 A股的影响说明"""
        return generate_a_share_impact(text)

    def _get_affected_sectors(self, text):
        """根据事件文本提取受影响板块"""
        return infer_affected_sectors(text)

    def _get_a_share_impact_sectors(self, name, chg):
        """根据美股指数涨跌输出A股关联板块"""
        return infer_a_share_impact_sectors(name, chg)

    def get_major_indices(self, dt):
        """
        批量获取主要指数数据（10个指数）
        返回：dict，key为指数代码
        """
        date_str = format_date(dt)
        cache_key = f'major_indices_{date_str}'
        cached = get_cache(cache_key, namespace='indices', ttl=3600)
        if cached is not None:
            return {"success": True, "data": cached, "source": "cache", "cached": True}

        indices_config = dict(ALL_INDICES)

        result = {}
        errors = []

        # 并行查询所有指数，降低总耗时
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(self.get_index_data, code, dt): (code, name) for code, name in indices_config.items()}
            for future in futures:
                code, name = futures[future]
                try:
                    idx_data = future.result(timeout=TIMEOUTS['major_index_single_sec'])
                    if idx_data.get('success') and idx_data.get('data'):
                        result[code] = {
                            "code": code,
                            "name": name,
                            **idx_data['data']
                        }
                    else:
                        errors.append(f"{name}({code})")
                except Exception as e:
                    logger.warning(f"获取 {name}({code}) 失败: {e}")
                    errors.append(f"{name}({code})")
                    continue

        if result:
            set_cache(cache_key, result, namespace='indices', ttl=3600)
            logger.info(f"✅ 获取主要指数成功: {len(result)}/10")
            if errors:
                logger.warning(f"部分指数获取失败: {', '.join(errors)}")
            return {"success": True, "data": result, "source": "akshare/yfinance", "cached": False}
        else:
            logger.error("无法获取任何主要指数数据")
            return {"success": False, "data": None, "error": "无法获取主要指数", "source": "none", "cached": False}

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
