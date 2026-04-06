"""
PDF 转换策略模块
"""

import os
import subprocess
import tempfile
from abc import ABC, abstractmethod

from utils import get_logger

logger = get_logger('pdf_converter')


class PDFConverter(ABC):
    """PDF 转换策略接口。"""

    @abstractmethod
    def convert(self, markdown_content, pdf_path, title=None):
        """执行转换，成功返回 pdf_path，失败返回 None。"""


class Fpdf2Converter(PDFConverter):
    """使用 fpdf2 转换（纯 Python，无外部二进制依赖）。"""

    def convert(self, markdown_content, pdf_path, title=None):
        try:
            from fpdf import FPDF
        except ImportError:
            logger.warning("fpdf2 未安装，跳过 PDF 导出")
            return None

        try:
            pdf = FPDF(format='A4')
            pdf.set_margins(10, 10, 10)
            pdf.set_auto_page_break(auto=True, margin=10)

            font_path = _find_cjk_font()
            if font_path:
                pdf.add_font('CJK', '', font_path)
                font_name = 'CJK'
            else:
                font_name = 'Helvetica'
                logger.warning("未找到中文字体，PDF 中中文可能显示异常")

            pdf.add_page()
            pdf.set_font(font_name, size=8)

            in_table = False
            for line_num, line in enumerate(markdown_content.split('\n'), start=1):
                stripped = line.strip()
                if not stripped:
                    pdf.ln(3)
                    in_table = False
                    continue

                if stripped.startswith('|') and '---' in stripped:
                    in_table = True
                    continue
                if in_table and stripped.startswith('|'):
                    continue
                if in_table and not stripped.startswith('|'):
                    in_table = False

                try:
                    if stripped.startswith('# '):
                        pdf.set_font(font_name, size=13)
                        pdf.multi_cell(0, 7, stripped[2:].strip())
                        pdf.set_font(font_name, size=8)
                        pdf.ln(2)
                        continue
                    if stripped.startswith('## '):
                        pdf.set_font(font_name, size=11)
                        pdf.multi_cell(0, 6, stripped[3:].strip())
                        pdf.set_font(font_name, size=8)
                        pdf.ln(1)
                        continue
                    if stripped.startswith('### '):
                        pdf.set_font(font_name, size=9)
                        pdf.multi_cell(0, 5, stripped[4:].strip())
                        pdf.set_font(font_name, size=8)
                        continue
                    if stripped.startswith('---'):
                        pdf.ln(2)
                        continue

                    clean = stripped.replace('**', '').replace('__', '').replace('*', '').replace('_', '')
                    if clean:
                        pdf.multi_cell(0, 4, clean)
                except Exception as e:
                    logger.warning(f"第 {line_num} 行渲染失败: {e}, 内容: {stripped[:80]}")
                    continue

            pdf.output(pdf_path)
            return pdf_path
        except Exception as e:
            logger.error(f"fpdf2 转换失败: {e}")
            return None


class WeasyprintConverter(PDFConverter):
    """使用 weasyprint 转换。"""

    def __init__(self, markdown_to_html=None):
        self._markdown_to_html = markdown_to_html

    def convert(self, markdown_content, pdf_path, title=None):
        try:
            from weasyprint import HTML
        except ImportError:
            logger.warning("weasyprint 未安装，跳过 PDF 导出")
            return None

        try:
            html_content = _to_html(markdown_content, title, self._markdown_to_html)
            HTML(string=html_content).write_pdf(pdf_path)
            return pdf_path
        except Exception as e:
            logger.error(f"weasyprint 转换失败: {e}")
            return None


class WkhtmltopdfConverter(PDFConverter):
    """使用 wkhtmltopdf 转换。"""

    def __init__(self, publisher=None, markdown_to_html=None):
        self._publisher = publisher
        self._markdown_to_html = markdown_to_html

    def convert(self, markdown_content, pdf_path, title=None):
        if self._publisher is not None:
            try:
                result = self._publisher.convert_to_pdf(markdown_content, pdf_path, title)
                if result.get('success'):
                    return result.get('pdf_path')
                return None
            except Exception as e:
                logger.error(f"publisher wkhtmltopdf 转换失败: {e}")
                return None

        html_content = _to_html(markdown_content, title, self._markdown_to_html)
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.html', encoding='utf-8') as f:
                f.write(html_content)
                html_path = f.name

                result = subprocess.run(
                    ['wkhtmltopdf', html_path, pdf_path],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if result.returncode == 0:
                    return pdf_path
                logger.warning(f"wkhtmltopdf 转换失败: {result.stderr}")
                return None
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            logger.warning(f"wkhtmltopdf 不可用: {e}")
            return None
        except Exception as e:
            logger.error(f"wkhtmltopdf 转换失败: {e}")
            return None


def get_pdf_converter(engine, publisher=None):
    """根据 engine 返回转换策略实例。"""
    if engine == 'weasyprint':
        return WeasyprintConverter(markdown_to_html=getattr(publisher, '_markdown_to_html', None))
    if engine == 'wkhtmltopdf':
        return WkhtmltopdfConverter(
            publisher=publisher,
            markdown_to_html=getattr(publisher, '_markdown_to_html', None),
        )
    return Fpdf2Converter()


def _to_html(markdown_content, title, markdown_to_html):
    if callable(markdown_to_html):
        return markdown_to_html(markdown_content, title)

    # fallback
    try:
        import markdown
        body = markdown.markdown(markdown_content, extensions=['tables', 'fenced_code'])
    except Exception:
        body = markdown_content.replace('\n', '<br>')

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset=\"UTF-8\">
      <title>{title or 'A股日报'}</title>
      <style>
        body {{ font-family: \"PingFang SC\", \"Microsoft YaHei\", sans-serif; margin: 40px; line-height: 1.6; }}
        h1, h2, h3 {{ color: #333; }}
      </style>
    </head>
    <body>
      <h1>{title or 'A股日报'}</h1>
      {body}
    </body>
    </html>
    """


def _find_cjk_font():
    candidates = [
        '/System/Library/Fonts/PingFang.ttc',
        '/System/Library/Fonts/STHeiti Light.ttc',
        '/System/Library/Fonts/STHeiti Medium.ttc',
        '/Library/Fonts/Arial Unicode.ttf',
        '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None
