
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
    cn_now,
)

logger = get_logger('data_fetcher')

class InternationalFetcherMixin:
    def get_us_market(self):
        """
        获取美股指数和中概股数据
        优先级：yfinance
        失败返回错误，无降级数据
        """
        cache_key = 'us_market'
        ttl = CACHE_TTL_CONFIG.get('us_market', 3600)
        cached = get_cache(cache_key, namespace='yfinance', ttl=ttl)
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
                "update_time": format_date(cn_now(), '%Y-%m-%d %H:%M:%S'),
                "indices": indices_data,
                "chinadotcom": cdc_data
            }

            ttl = CACHE_TTL_CONFIG.get('us_market', 3600)
            set_cache(cache_key, result, namespace='yfinance', ttl=ttl)
            logger.info(f"✅ yfinance 获取美股数据成功")
            return {"success": True, "data": result, "source": "yfinance", "cached": False}

        except ImportError:
            logger.error("yfinance 未安装，无法获取美股数据")
            return {"success": False, "data": None, "error": "yfinance not installed", "source": "none", "cached": False}
        except Exception as e:
            logger.error(f"yfinance 获取美股数据失败: {e}")
            return {"success": False, "data": None, "error": str(e), "source": "yfinance", "cached": False}

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
        ttl = CACHE_TTL_CONFIG.get('futures', 300)
        cached = get_cache(cache_key, namespace='mx_data', ttl=ttl)
        if cached is not None:
            return {"success": True, "data": cached, "source": "cache", "cached": True}

        # 初始化结果结构
        futures_data = {
            "update_time": format_date(cn_now(), '%Y-%m-%d %H:%M:%S'),
            "futures": {}
        }
        sources = []

        # 优先级1：使用 mx-data Skill（需要 MX_APIKEY）
        self._load_env()  # 确保 .env 已加载
        mx_apikey = self._get_mx_apikey()
        logger.debug(f"MX_APIKEY状态: {'已设置' if mx_apikey else '未设置'}")
        if mx_apikey:
            try:
                # 并行查询沪深300和A50（避免串行超时叠加）
                queries = [
                    ("沪深300期货 最新价 涨跌幅", "CSI300"),
                    ("A50期货 最新价 涨跌幅", "A50")
                ]

                from concurrent.futures import ThreadPoolExecutor, as_completed

                def _fetch_one(query_key):
                    query, key = query_key
                    logger.debug(f"查询期指: {query}")
                    raw = self._mx_query_json(query, TIMEOUTS['mx_futures_sec'])
                    return key, raw

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
                d2 = self._mx_query_json("上证50 最新价 涨跌幅", TIMEOUTS['mx_futures_a50_fallback_sec'])
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
            ttl = CACHE_TTL_CONFIG.get('futures', 300)
            set_cache(cache_key, futures_data, namespace='mx_data', ttl=ttl)
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
        now = cn_now()
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
        返回值:
            True: 建议切换备用 key 重试（仅 status=113）
            False: 不需要重试
        """
        if status == 0:
            return False
        if status == 113:
            # 调用耗尽，切换备用 key
            if not getattr(self, '_mx_key_exhausted', False):
                self._mx_key_exhausted = True
                backup = os.getenv('MX_APIKEY_BACKUP', '')
                if backup:
                    logger.warning(f"mx-data 主key调用次数耗尽(status=113)，已切换到备用key")
                else:
                    logger.warning(f"mx-data 主key调用次数耗尽(status=113)，备用key未配置")
            return True
        raise RuntimeError(f"mx-data API error status={status}: {message}")

    def _mx_query_json(self, tool_query, timeout_sec):
        """
        调用 mx-data claw/query 并自动处理 status=113 的备用 key 重试。
        返回 raw json（status 必为0），否则抛异常。
        """
        self._load_env()
        return self.mx_provider.query_json(tool_query, timeout_sec)

    def _parse_mx_futures(self, result, target_key=None):
        """
        解析 mx-data 期指响应
        target_key: 'CSI300' 或 'A50'，如果传入则只返回对应 key 的数据，否则返回完整结构
        """
        try:
            futures_data = self.mx_provider.parse_futures(
                raw=result,
                build_impact_text=self._generate_impact_text,
                target_key=target_key,
            )
        except Exception as e:
            logger.warning(f"解析 mx-data 期指响应失败: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return None if target_key else {"update_time": format_date(cn_now(), '%Y-%m-%d %H:%M:%S'), "futures": {}}

        if target_key and not futures_data:
            return None

        futures_data['update_time'] = format_date(cn_now(), '%Y-%m-%d %H:%M:%S')
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

    def get_international_events(self, dt=None):
        """
        获取昨夜今晨国际事件（可能影响 A股）
        数据源：Tavily 搜索引擎 + 美股/期指联动分析
        缓存 ttl=6h（早报生成后半天有效）
        """
        if dt is None:
            dt = cn_now()
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
