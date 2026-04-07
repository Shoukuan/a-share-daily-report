
"""Data fetcher mixins by domain."""

from .index_fetcher import IndexFetcherMixin
from .sentiment_fetcher import SentimentFetcherMixin
from .money_fetcher import MoneyFetcherMixin
from .international_fetcher import InternationalFetcherMixin
from .news_fetcher import NewsFetcherMixin
from .sector_fetcher import SectorFetcherMixin
from .margin_fetcher import MarginFetcherMixin
from .block_trade_fetcher import BlockTradeFetcherMixin

__all__ = [
    "IndexFetcherMixin",
    "SentimentFetcherMixin",
    "MoneyFetcherMixin",
    "InternationalFetcherMixin",
    "NewsFetcherMixin",
    "SectorFetcherMixin",
    "MarginFetcherMixin",
    "BlockTradeFetcherMixin",
]
