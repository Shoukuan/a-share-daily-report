"""
数据验证层（Pydantic V2 Schemas）
为关键数据模型提供类型校验和数据清洗
"""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, field_validator, ConfigDict


class IndexDataSchema(BaseModel):
    """指数行情数据验证"""
    model_config = ConfigDict(extra='ignore')

    ts_code: str
    name: str
    trade_date: str
    close: float = Field(..., ge=0)
    open: float = Field(..., ge=0)
    high: float = Field(..., ge=0)
    low: float = Field(..., ge=0)
    pre_close: float = Field(..., ge=0)
    change: float
    change_pct: float = Field(..., ge=-20, le=20)
    vol: int = Field(..., ge=0)
    amount: int = Field(..., ge=0)
    source: str = ""

    @field_validator('trade_date')
    @classmethod
    def validate_date_format(cls, v: str) -> str:
        if not isinstance(v, str):
            raise ValueError('trade_date must be string')
        parts = v.split('-')
        if len(parts) != 3:
            raise ValueError('trade_date must be YYYY-MM-DD')
        return v

    @field_validator('name')
    @classmethod
    def validate_name_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError('name cannot be empty')
        return v.strip()


class MarketSentimentSchema(BaseModel):
    """市场情绪数据验证"""
    model_config = ConfigDict(extra='ignore')

    trade_date: str
    limit_up_count: int = Field(..., ge=0)
    limit_down_count: int = Field(..., ge=0)
    failed_limit_up: int = Field(..., ge=0)
    failed_rate: float = Field(..., ge=0, le=100)
    prev_limit_up_avg_return: float
    max_consec_up: int = Field(..., ge=0)
    total_turnover: int = Field(..., ge=0)
    turnover_change_pct: float

    @field_validator('trade_date')
    @classmethod
    def validate_date(cls, v: str) -> str:
        if not isinstance(v, str):
            raise ValueError('trade_date must be string')
        return v


class MoneyFlowSchema(BaseModel):
    """资金流向数据验证"""
    model_config = ConfigDict(extra='ignore')

    trade_date: str
    northbound: Optional[float] = None
    main_capital: Optional[float] = None


class SectorInfoSchema(BaseModel):
    """板块信息验证"""
    model_config = ConfigDict(extra='ignore')

    sector: str
    change_pct: float
    leaders: List[Dict[str, Any]] = Field(default_factory=list)
    driver: str = ""

    @field_validator('sector')
    @classmethod
    def validate_sector_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError('sector cannot be empty')
        return v.strip()


class SectorDataSchema(BaseModel):
    """板块数据完整结构验证"""
    model_config = ConfigDict(extra='ignore')

    industry: List[SectorInfoSchema] = Field(default_factory=list)
    concept: List[SectorInfoSchema] = Field(default_factory=list)


class LHBItemSchema(BaseModel):
    """龙虎榜单项验证"""
    model_config = ConfigDict(extra='ignore')

    code: str
    name: str
    net_inflow: float
    change_pct: float
    close: float


class NewsItemSchema(BaseModel):
    """新闻条目验证"""
    model_config = ConfigDict(extra='ignore')

    title: str
    content: str = ""
    source: str = ""
    url: str = ""
    publish_time: str = ""
    importance: str = "medium"
    related_sectors: List[str] = Field(default_factory=list)
    related_stocks: List[str] = Field(default_factory=list)
    level: str = ""
    level_icon: str = ""
    level_name: str = ""

    @field_validator('title')
    @classmethod
    def validate_title_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError('title cannot be empty')
        return v.strip()

    @field_validator('importance')
    @classmethod
    def validate_importance(cls, v: str) -> str:
        if v not in ['high', 'medium', 'low']:
            raise ValueError('importance must be high/medium/low')
        return v


class MarketOverviewSchema(BaseModel):
    """市场全景数据验证"""
    model_config = ConfigDict(extra='ignore')

    score: float = Field(..., ge=0, le=100)
    trend: str
    up_count: int = Field(..., ge=0)
    down_count: int = Field(..., ge=0)
    flat_count: int = Field(..., ge=0)
    limit_up: int = Field(..., ge=0)
    limit_down: int = Field(..., ge=0)
    turnover: int = Field(..., ge=0)
    northbound: Optional[float] = None
    suggest_position: float = Field(..., ge=0, le=1)


class MarketDepthSchema(BaseModel):
    """盘面深度数据验证"""
    model_config = ConfigDict(extra='ignore')

    break_rate: float = Field(..., ge=0, le=100)
    break_count: int = Field(..., ge=0)
    total_limit_up: int = Field(..., ge=0)
    up_over_5pct: int = Field(..., ge=0)
    down_over_5pct: int = Field(..., ge=0)
    prev_limit_up_return: float


class GlobalAssetsSchema(BaseModel):
    """全球资产验证"""
    model_config = ConfigDict(extra='ignore')

    name: str
    code: str
    close: float = Field(..., ge=0)
    change: float
    change_pct: float


class WatchlistPerformanceSchema(BaseModel):
    """自选股表现验证"""
    model_config = ConfigDict(extra='ignore')

    code: str
    name: str
    price: float = Field(..., ge=0)
    change_pct: float
    amount: int = Field(..., ge=0)
    amplitude: float = Field(..., ge=0, le=100)
    turnover: float = Field(..., ge=0, le=100)
    volume_ratio: float = Field(..., ge=0)
    ma5: float = Field(..., ge=0)
    ma20: float = Field(..., ge=0)
    avg_score: int = Field(..., ge=0, le=100)
    signal: str


def validate_schema(data: dict, schema_class):
    """
    使用指定 schema 验证数据。返回 (validated_data, errors)。
    """
    try:
        validated = schema_class(**data)
        return validated.model_dump(), []
    except Exception as e:
        return data, [str(e)]


def validate_many(data_list: List[dict], schema_class):
    """批量验证，失败项保留原始数据。"""
    results = []
    errors = []
    for i, item in enumerate(data_list):
        try:
            validated = schema_class(**item)
            results.append(validated.model_dump())
        except Exception as e:
            errors.append(f"Item {i}: {str(e)}")
            results.append(item)
    return results, errors
