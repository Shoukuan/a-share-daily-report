
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
from schemas import IndexDataSchema, validate_schema

logger = get_logger('data_fetcher')

class IndexFetcherMixin:
    def get_index_data(self, index_code, dt):
        """
        获取指数数据（优先 akshare 实时行情含成交额 → baostock 兜底 → yfinance）
        三层数据源，确保指数数据不断层
        """
        date_str = format_date(dt)
        cache_key = f'index_{index_code}_{date_str}'
        ttl = CACHE_TTL_CONFIG.get('index_data', 60)

        cached = get_cache(cache_key, namespace='akshare', ttl=ttl)
        if cached is not None:
            return {"success": True, "data": cached, "source": "cache", "cached": True}

        # ── 第一层：akshare stock_zh_index_spot_em（实时行情，含成交额）──
        if self.ak and not type(self)._akshare_unavailable:
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
                        ttl = CACHE_TTL_CONFIG.get('index_data', 60)
                        # 数据验证（非阻塞，失败仅记录）
                        validated_data, errors = validate_schema(data, IndexDataSchema)
                        if errors:
                            logger.warning(f"指数数据验证失败: {errors}; 使用原始数据")
                        else:
                            data = validated_data
                        set_cache(cache_key, data, namespace='akshare', ttl=ttl)
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

                # 数据验证（非阻塞，失败仅记录）
                validated_data, errors = validate_schema(data, IndexDataSchema)
                if errors:
                    logger.warning(f"baostock 指数数据验证失败: {errors}; 使用原始数据")
                else:
                    data = validated_data
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
                    ttl = CACHE_TTL_CONFIG.get('index_data', 60)
                    # 数据验证（非阻塞，失败仅记录）
                    validated_data, errors = validate_schema(data, IndexDataSchema)
                    if errors:
                        logger.warning(f"yfinance 指数数据验证失败: {errors}; 使用原始数据")
                    else:
                        data = validated_data
                    set_cache(cache_key, data, namespace='yfinance', ttl=ttl)
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

    def get_major_indices(self, dt):
        """
        批量获取主要指数数据（10个指数）
        返回：dict，key为指数代码
        """
        date_str = format_date(dt)
        cache_key = f'major_indices_{date_str}'
        ttl = CACHE_TTL_CONFIG.get('index_data', 60)
        cached = get_cache(cache_key, namespace='indices', ttl=ttl)
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
            ttl = CACHE_TTL_CONFIG.get('index_data', 60)
            set_cache(cache_key, result, namespace='indices', ttl=ttl)
            logger.info(f"✅ 获取主要指数成功: {len(result)}/10")
            if errors:
                logger.warning(f"部分指数获取失败: {', '.join(errors)}")
            return {"success": True, "data": result, "source": "akshare/yfinance", "cached": False}
        else:
            logger.error("无法获取任何主要指数数据")
            return {"success": False, "data": None, "error": "无法获取主要指数", "source": "none", "cached": False}
