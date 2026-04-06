"""
数据模型模块
定义各模块间传递的数据结构，替代裸 dict
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any


@dataclass
class IndexData:
    """指数行情数据"""
    ts_code: str
    name: str
    trade_date: str
    close: float
    open: float
    high: float
    low: float
    pre_close: float
    change: float
    change_pct: float
    vol: int = 0
    amount: int = 0
    source: str = ""


@dataclass
class MarketSentiment:
    """市场情绪数据"""
    trade_date: str
    limit_up_count: int = 0
    limit_down_count: int = 0
    failed_limit_up: int = 0
    failed_rate: float = 0.0
    prev_limit_up_avg_return: float = 0.0
    max_consec_up: int = 0
    total_turnover: float = 0.0
    turnover_change_pct: float = 0.0


@dataclass
class MoneyFlow:
    """资金流向数据"""
    trade_date: str
    northbound: Optional[float] = None
    main_capital: Optional[float] = None


@dataclass
class SectorInfo:
    """板块信息"""
    sector: str
    change_pct: float = 0.0
    leaders: List[Dict[str, Any]] = field(default_factory=list)
    driver: str = ""


@dataclass
class LHBItem:
    """龙虎榜单条数据"""
    code: str
    name: str
    net_inflow: float
    change_pct: float
    close: float


@dataclass
class NewsItem:
    """新闻条目"""
    title: str
    content: str = ""
    source: str = ""
    url: str = ""
    publish_time: str = ""
    importance: str = "medium"
    related_sectors: List[str] = field(default_factory=list)
    related_stocks: List[str] = field(default_factory=list)
    level: str = ""
    level_icon: str = ""
    level_name: str = ""


@dataclass
class USIndexData:
    """美股指数数据"""
    name: str
    code: str
    close: float
    change: float
    change_pct: float


@dataclass
class FuturesItem:
    """期指数据"""
    name: str
    code: str
    change_pct: float
    impact: str


@dataclass
class FetchResult:
    """统一的数据获取结果包装"""
    success: bool
    data: Any = None
    error: str = ""
    source: str = ""
    cached: bool = False
