
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
from schemas import NewsItemSchema, validate_many

logger = get_logger('data_fetcher')

class NewsFetcherMixin:
    def get_news(self, dt, limit=10):
        """
        获取财经新闻
        优先级：mx-search
        失败返回错误，无降级数据
        """
        date_str = format_date(dt, '%Y-%m-%d')
        cache_key = f'news_{date_str}'
        ttl = CACHE_TTL_CONFIG.get('news', 900)
        cached = get_cache(cache_key, namespace='mx_search', ttl=ttl)
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
                        should_retry = self._handle_mx_status(api_status, result.get('message', ''))
                        retry_key = self._get_mx_apikey()
                        if should_retry and retry_key and retry_key != mx_api_key:
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
                            # 数据验证（非阻塞，批量验证）
                            validated_items, errors = validate_many(news_items, NewsItemSchema)
                            if errors:
                                logger.warning(f"新闻数据批量验证失败: {len(errors)} 条错误; 使用原始数据")
                            else:
                                news_items = validated_items
                            ttl = CACHE_TTL_CONFIG.get('news', 900)
                            set_cache(cache_key, news_items, namespace='mx_search', ttl=ttl)
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
        """解析 mx-search 返回结果（支持多级路径 fallback）"""
        news_list = []

        if not isinstance(result, dict):
            return news_list

        # 多级路径探测：尝试提取新闻列表
        items = self._extract_news_items(result)

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
                    publish_time=date if date else format_date(cn_now(), '%Y-%m-%d %H:%M:%S'),
                    importance="high" if secu_list else "medium",
                    related_sectors=[],
                    related_stocks=related_stocks[:3],
                )))

        return news_list

    def _extract_news_items(self, data):
        """
        从 mx-search 返回结构中提取新闻列表
        支持多级嵌套结构，按优先级尝试
        """
        # 路径 1: 原始结构 result['data']['data']['llmSearchResponse']['data']
        if 'data' in data:
            outer = data['data']
            if isinstance(outer, dict):
                inner = outer.get('data', {})
                if isinstance(inner, dict):
                    llm = inner.get('llmSearchResponse', {})
                    if isinstance(llm, dict) and 'data' in llm:
                        items = llm['data']
                        if isinstance(items, list):
                            return items

        # 路径 2: 简化结构 result['llmSearchResponse']['data']
        llm_direct = data.get('llmSearchResponse', {})
        if isinstance(llm_direct, dict) and 'data' in llm_direct:
            items = llm_direct['data']
            if isinstance(items, list):
                return items

        # 路径 3: 直接列表 result['data'] 或 result['items']
        if 'data' in data and isinstance(data['data'], list):
            return data['data']
        if 'items' in data and isinstance(data['items'], list):
            return data['items']
        if 'news' in data and isinstance(data['news'], list):
            return data['news']

        # 路径 4: 深度搜索任意包含 news/item 的列表
        def _find_list(obj, depth=0):
            if depth > 5:  # 限制递归深度
                return None
            if isinstance(obj, dict):
                for key, value in obj.items():
                    if key in ('data', 'items', 'news', 'list') and isinstance(value, list):
                        return value
                    found = _find_list(value, depth + 1)
                    if found:
                        return found
            elif isinstance(obj, list):
                return obj
            return None

        return _find_list(data) or []
