"""
配置校验器（Pydantic V2）
用 Pydantic 模型对 config.yaml 进行强类型验证，在启动时尽早暴露配置问题。
"""

from typing import Optional, Literal
from pydantic import BaseModel, Field, field_validator, ConfigDict

from errors import ConfigValidationError


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------

class OutputConfig(BaseModel):
    model_config = ConfigDict(extra='ignore')
    base_dir: str
    morning_subdir: str = "morning"
    evening_subdir: str = "evening"

    @field_validator('base_dir', 'morning_subdir', 'evening_subdir')
    @classmethod
    def must_be_non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError('不能为空字符串')
        return v.strip()


class DataSourceEntry(BaseModel):
    model_config = ConfigDict(extra='ignore')
    enabled: bool = True
    cache_ttl: int = Field(default=3600, ge=0)


class DataSourcesConfig(BaseModel):
    model_config = ConfigDict(extra='ignore')
    akshare: DataSourceEntry = Field(default_factory=DataSourceEntry)
    tushare: DataSourceEntry = Field(default_factory=DataSourceEntry)
    mx_data: DataSourceEntry = Field(default_factory=DataSourceEntry)
    sina: DataSourceEntry = Field(default_factory=DataSourceEntry)


class WatchlistConfig(BaseModel):
    model_config = ConfigDict(extra='ignore')
    path: str

    @field_validator('path')
    @classmethod
    def must_be_non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError('watchlist.path 不能为空')
        return v.strip()


class PdfConfig(BaseModel):
    model_config = ConfigDict(extra='ignore')
    enabled: bool = False
    output_dir: str = "reports/pdf"
    engine: Literal['fpdf2', 'weasyprint', 'wkhtmltopdf'] = 'fpdf2'

    @field_validator('output_dir')
    @classmethod
    def must_be_non_empty_if_set(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError('pdf.output_dir 不能为空')
        return v.strip()


class FeishuDocConfig(BaseModel):
    model_config = ConfigDict(extra='ignore')
    enabled: bool = True
    folder_token: str = ""


class FeishuMessageConfig(BaseModel):
    model_config = ConfigDict(extra='ignore')
    enabled: bool = True
    target_chat_id: str = ""
    message_template: str = ""


class PublishConfig(BaseModel):
    model_config = ConfigDict(extra='ignore')
    feishu_doc: FeishuDocConfig = Field(default_factory=FeishuDocConfig)
    pdf: PdfConfig = Field(default_factory=PdfConfig)
    feishu_message: FeishuMessageConfig = Field(default_factory=FeishuMessageConfig)
    dry_run: bool = False


class KellyConfig(BaseModel):
    model_config = ConfigDict(extra='ignore')
    win_rate: float = Field(default=0.5, ge=0.0, le=1.0)
    risk_reward_ratio: float = Field(default=2.0, gt=0.0)
    half_kelly: bool = False


class AnalysisConfig(BaseModel):
    model_config = ConfigDict(extra='ignore')
    kelly: KellyConfig = Field(default_factory=KellyConfig)


class AppConfig(BaseModel):
    """顶层配置模型，对应 config.yaml 根节点。"""
    model_config = ConfigDict(extra='ignore')

    version: str = "1.0"
    output: OutputConfig
    data_sources: DataSourcesConfig = Field(default_factory=DataSourcesConfig)
    watchlist: WatchlistConfig
    publish: PublishConfig = Field(default_factory=PublishConfig)
    analysis: AnalysisConfig = Field(default_factory=AnalysisConfig)


# ---------------------------------------------------------------------------
# Public API — backward-compatible with existing callers
# ---------------------------------------------------------------------------

def validate_config(config: dict) -> None:
    """
    校验关键配置。仅检查启动期必须项，避免运行中才暴露配置问题。
    校验失败时抛出 ConfigValidationError。
    """
    if not isinstance(config, dict):
        raise ConfigValidationError("配置文件解析失败：根节点必须为 object")

    try:
        AppConfig(**config)
    except Exception as e:
        raise ConfigValidationError(f"配置校验失败: {e}") from e
