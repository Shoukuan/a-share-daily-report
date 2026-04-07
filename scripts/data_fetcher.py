
"""
数据采集模块
从各数据源采集原始数据，处理降级逻辑
"""

import os
import threading
import time
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
from providers import MXDataProvider

from fetchers import (
    IndexFetcherMixin,
    SentimentFetcherMixin,
    MoneyFetcherMixin,
    InternationalFetcherMixin,
    NewsFetcherMixin,
    SectorFetcherMixin,
    MarginFetcherMixin,
    BlockTradeFetcherMixin,
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
    circuit_breaker,
)

logger = get_logger('data_fetcher')

class DataFetcher(IndexFetcherMixin, SentimentFetcherMixin, MoneyFetcherMixin, InternationalFetcherMixin, NewsFetcherMixin, SectorFetcherMixin, MarginFetcherMixin, BlockTradeFetcherMixin):
    # 类级别的 spot_em 缓存（所有实例共享，避免重复拉取）
    _spot_cache: "pd.DataFrame | None" = None
    _spot_cache_ts: "float | None" = None   # 上次成功获取的 time.time() 戳
    _spot_cache_ttl: int = 300              # 缓存有效期（秒），5 分钟
    _spot_lock = threading.Lock()
    _akshare_unavailable = False

    def __init__(self, config):
        self.config = config
        # 确保 .env 文件被加载（支持子进程环境）
        self._load_env()
        self._init_akshare()
        self._init_tushare()
        self.mx_provider = MXDataProvider(
            logger=logger,
            get_apikey=self._get_mx_apikey,
            handle_status=self._handle_mx_status,
            post_json_with_retry=post_json_with_retry,
            retry_policy=RETRY_POLICY,
        )
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


    @circuit_breaker('akshare.stock_zh_index_spot_em', failure_threshold=3, recovery_timeout=300)
    def _get_spot_em(self):
        """获取 spot_em DataFrame，带 TTL 的类级别内存缓存 + 线程安全。"""
        cls = type(self)
        with cls._spot_lock:
            now = time.time()
            # 缓存命中
            if (
                cls._spot_cache is not None
                and cls._spot_cache_ts is not None
                and now - cls._spot_cache_ts < cls._spot_cache_ttl
            ):
                return cls._spot_cache, None

            # 缓存过期或为空，重新拉取
            try:
                df = self.ak.stock_zh_index_spot_em()
                cls._spot_cache = df
                cls._spot_cache_ts = now
                cls._akshare_unavailable = False
                return df, None
            except Exception as e:
                # 拉取失败：清空缓存时间戳，下次调用仍可重试
                cls._spot_cache_ts = None
                err_str = str(e)
                if 'RemoteDisconnected' in err_str or 'push2.eastmoney.com' in err_str:
                    cls._akshare_unavailable = True
                    logger.warning(f"akshare 东方财富接口不可用: {e}")
                return None, err_str




































