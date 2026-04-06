"""
统一异常定义
"""


class ReportError(Exception):
    """报告流程基础异常。"""


class DataFetchError(ReportError):
    """数据采集异常。"""


class AnalysisError(ReportError):
    """数据分析异常。"""


class RenderError(ReportError):
    """报告渲染异常。"""


class ConfigValidationError(ReportError):
    """配置校验异常。"""
