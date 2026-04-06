#!/usr/bin/env python3
"""
报告生成模块
负责将分析结果渲染为 Markdown 格式
"""

from datetime import datetime
import math


from morning_renderer import MorningRenderer
from evening_renderer import EveningRenderer

from utils import get_logger, format_date, format_percent

logger = get_logger('renderer')


class Renderer:
    def __init__(self, config):
        self.config = config
        self._morning_renderer = MorningRenderer(config)
        self._evening_renderer = EveningRenderer(config)
        logger.info("Renderer 初始化完成")

    def render_morning_report(self, analysis_result, dt=None):
        return self._morning_renderer.render_morning_report(analysis_result, dt)

    def render_evening_report(self, analysis_result, dt=None):
        return self._evening_renderer.render_evening_report(analysis_result, dt)



    def render_empty_data(self):
        """渲染无数据提示"""
        return "# 数据获取失败\n\n无法获取今日市场数据，请稍后重试。"
