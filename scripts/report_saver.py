#!/usr/bin/env python3
"""
报告保存模块
负责将 Markdown 报告保存到文件系统，并可选导出 PDF
"""

import os
from datetime import datetime
from typing import Optional, Tuple

from utils import get_logger, format_date, get_project_root
from pdf_converter import get_pdf_converter

logger = get_logger('report_saver')


class ReportSaver:
    """报告保存器"""

    def __init__(self, config, publisher=None):
        """
        Args:
            config: 配置字典
            publisher: Publisher 实例（用于 PDF 转换）
        """
        self.config = config
        self.publisher = publisher
        self.output_config = config.get('output', {})

    def save_markdown(self, markdown: str, mode: str, dt) -> str:
        """
        保存 Markdown 报告

        Args:
            markdown: 报告内容
            mode: 'morning' 或 'evening'
            dt: 报告日期

        Returns:
            保存的文件路径
        """
        base_dir = os.getenv('A_SHARE_OUTPUT_DIR', self.output_config.get('base_dir', 'reports'))
        base_dir = os.path.expanduser(base_dir)
        sub_dir = self.output_config.get(f'{mode}_subdir', mode)

        # 处理绝对路径和相对路径
        if os.path.isabs(base_dir):
            base_path = base_dir
        else:
            project_root = get_project_root()
            base_path = os.path.join(project_root, base_dir)

        output_dir = os.path.join(base_path, sub_dir)
        os.makedirs(output_dir, exist_ok=True)

        date_str = format_date(dt, '%Y%m%d')
        mode_name = '早报' if mode == 'morning' else '晚报'
        filename = f'A股{mode_name}-{date_str}.md'
        output_path = os.path.join(output_dir, filename)

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(markdown)

        logger.info(f"报告已保存: {output_path}")
        return output_path

    def export_pdf(self, markdown: str, md_path: str, mode: str, dt) -> Optional[str]:
        """
        导出 PDF（如果配置启用）

        Args:
            markdown: 报告内容
            md_path: Markdown 文件路径（用于生成相关 PDF 路径）
            mode: 'morning' 或 'evening'
            dt: 报告日期

        Returns:
            PDF 文件路径，如果失败或未启用则返回 None
        """
        pdf_config = self.config.get('publish', {}).get('pdf', {})
        if not pdf_config.get('enabled', False):
            return None

        engine = pdf_config.get('engine', 'fpdf2')
        pdf_output_dir = os.getenv('A_SHARE_PDF_OUTPUT_DIR', pdf_config.get('output_dir', 'reports/pdf'))
        pdf_output_dir = os.path.expanduser(pdf_output_dir)

        # 构建 PDF 输出路径
        if not os.path.isabs(pdf_output_dir):
            project_root = get_project_root()
            pdf_output_dir = os.path.join(project_root, pdf_output_dir)
        os.makedirs(pdf_output_dir, exist_ok=True)

        date_str = format_date(dt, '%Y%m%d')
        mode_name = '早报' if mode == 'morning' else '晚报'
        pdf_filename = f'A股{mode_name}-{date_str}.pdf'
        pdf_path = os.path.join(pdf_output_dir, pdf_filename)

        title = f"A股{mode_name}-{date_str}"

        # 使用 publisher 的转换能力或独立转换器
        converter = get_pdf_converter(engine=engine, publisher=self.publisher)
        result = converter.convert(markdown, pdf_path, title)

        if result:
            logger.info(f"PDF 已导出: {result}")
            return result
        else:
            logger.warning("PDF 导出失败，继续执行")
            return None

    def save_report_with_pdf(self, markdown: str, mode: str, dt) -> Tuple[str, Optional[str]]:
        """
        保存报告并可选导出 PDF

        Returns:
            (markdown_path, pdf_path) pdf_path 可能为 None
        """
        md_path = self.save_markdown(markdown, mode, dt)
        pdf_path = self.export_pdf(markdown, md_path, mode, dt)
        return md_path, pdf_path
