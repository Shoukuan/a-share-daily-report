"""
数据验证层（Pydantic Schemas）
为关键数据模型提供类型校验和数据清洗
"""

from datetime import datetime, date
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, validator, root_validator


class IndexDataSchema(BaseModel):
    """指数行情数据验证"""
    ts_code: str
    name: str
    trade_date: str
    close: float = Field(..., ge=0)
    open: float = Field(..., ge=0)
    high: float = Field(..., ge=0)
    low: float = Field(..., ge=0)
    pre_close: float = Field(..., ge=0)
    change: float
    change_pct: float = Field(..., ge=-20, le=20)  # A股涨跌幅限制
    vol: int = Field(..., ge=0)
    amount: int = Field(..., ge=0)
    source: str = ""

    @validator('trade_date')
    def validate_date_format(cls, v):
        """校验日期格式 YYYY-MM-DD"""
        if not isinstance(v, str):
            raise ValueError('trade_date must be string')
        # 简单格式检查
        parts = v.split('-')
        if len(parts) != 3:
            raise ValueError('trade_date must be YYYY-MM-DD')
        return v

    @validator('name')
    def validate_name_not_empty(cls, v):
        if not v or not v.strip():
            raise ValueError('name cannot be empty')
        return v.strip()

    class Config:
        extra = 'ignore'  # 忽略额外字段


class MarketSentimentSchema(BaseModel):
    """市场情绪数据验证"""
    trade_date: str
    limit_up_count: int = Field(..., ge=0)
    limit_down_count: int = Field(..., ge=0)
    failed_limit_up: int = Field(..., ge=0)
    failed_rate: float = Field(..., ge=0, le=100)
    prev_limit_up_avg_return: float
    max_consec_up: int = Field(..., ge=0)
    total_turnover: int = Field(..., ge=0)
    turnover_change_pct: float

    @validator('trade_date')
    def validate_date(cls, v):
        if not isinstance(v, str):
            raise ValueError('trade_date must be string')
        return v

    class Config:
        extra = 'ignore'


class MoneyFlowSchema(BaseModel):
    """资金流向数据验证"""
    trade_date: str
    northbound: Optional[float] = None
    main_capital: Optional[float] = None

    class Config:
        extra = 'ignore'


class SectorInfoSchema(BaseModel):
    """板块信息验证"""
    sector: str
    change_pct: float
    leaders: List[Dict[str, Any]] = Field(default_factory=list)
    driver: str = ""

    @validator('sector')
    def validate_sector_not_empty(cls, v):
        if not v or not v.strip():
            raise ValueError('sector cannot be empty')
        return v.strip()

    class Config:
        extra = 'ignore'


class SectorDataSchema(BaseModel):
    """板块数据完整结构验证"""
    industry: List[SectorInfoSchema] = Field(default_factory=list)
    concept: List[SectorInfoSchema] = Field(default_factory=list)

    class Config:
        extra = 'ignore'


class LHBItemSchema(BaseModel):
    """龙虎榜单项验证"""
    code: str
    name: str
    net_inflow: float
    change_pct: float
    close: float

    class Config:
        extra = 'ignore'


class NewsItemSchema(BaseModel):
    """新闻条目验证"""
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

    @validator('title')
    def validate_title_not_empty(cls, v):
        if not v or not v.strip():
            raise ValueError('title cannot be empty')
        return v.strip()

    @validator('importance')
    def validate_importance(cls, v):
        if v not in ['high', 'medium', 'low']:
            raise ValueError('importance must be high/medium/low')
        return v

    class Config:
        extra = 'ignore'


class MarketOverviewSchema(BaseModel):
    """市场全景数据验证"""
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

    class Config:
        extra = 'ignore'


class MarketDepthSchema(BaseModel):
    """盘面深度数据验证"""
    break_rate: float = Field(..., ge=0, le=100)
    break_count: int = Field(..., ge=0)
    total_limit_up: int = Field(..., ge=0)
    up_over_5pct: int = Field(..., ge=0)
    down_over_5pct: int = Field(..., ge=0)
    prev_limit_up_return: float

    class Config:
        extra = 'ignore'


class GlobalAssetsSchema(BaseModel):
    """全球资产验证"""
    name: str
    code: str
    close: float = Field(..., ge=0)
    change: float
    change_pct: float

    class Config:
        extra = 'ignore'


class WatchlistPerformanceSchema(BaseModel):
    """自选股表现验证"""
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

    class Config:
        extra = 'ignore'


# 统一验证接口
def validate_schema(data: dict, schema_class):
    """
    使用指定 schema 验证数据

    Args:
        data: 待验证数据字典
        schema_class: Pydantic Schema 类

    Returns:
        (validated_data, errors): 验证通过的数据和错误列表
    """
    try:
        validated = schema_class(**data)
        return validated.dict(), []
    except Exception as e:
        return data, [str(e)]


def validate_many(data_list: List[dict], schema_class):
    """批量验证"""
    results = []
    errors = []
    for i, item in enumerate(data_list):
        try:
            validated = schema_class(**item)
            results.append(validated.dict())
        except Exception as e:
            errors.append(f"Item {i}: {str(e)}")
            results.append(item)  # 返回原始数据继续流程
    return results, errors
