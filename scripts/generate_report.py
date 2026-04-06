
#!/usr/bin/env python3
"""
A股日报生成器 - 主入口脚本
"""

import os
import sys
import argparse
import yaml
from datetime import datetime, date

# 添加项目路径（让模块可以导入）
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

from constants import TIMEOUTS
from utils import (
    get_logger,
    log_event,
    format_date,
    run_with_timeout,
    get_project_root,
    ensure_trace_id,
    get_trace_id,
    stage_timer,
    monitor_stage,
)
from data_fetcher import DataFetcher
from analyzer import Analyzer
from renderer import Renderer
from trade_calendar import get_effective_date
from publisher import Publisher
from data_collectors import MorningDataCollector, EveningDataCollector
from config_validator import validate_config
from errors import DataFetchError, AnalysisError, RenderError
from pdf_converter import get_pdf_converter

logger = get_logger('report_generator')


class ReportGenerator:
    """
    报告生成主控制器
    协调整个报告生成流程
    """

    def __init__(self, config_path=None):
        """
        初始化报告生成器

        Args:
            config_path: 配置文件路径
        """
        if config_path is None:
            config_path = os.path.join(current_dir, '..', 'config', 'config.yaml')
            config_path = os.path.normpath(config_path)

        self.config = self._load_config(config_path)
        validate_config(self.config)
        self.data_fetcher = DataFetcher(self.config)
        self.analyzer = Analyzer(self.config)
        self.renderer = Renderer(self.config)
        self.publisher = Publisher(self.config)
        self.morning_collector = MorningDataCollector(self.data_fetcher, self.analyzer, logger)
        self.evening_collector = EveningDataCollector(self.data_fetcher, self.analyzer, logger)

        log_event(logger, "info", "report_generator_init", config_path=config_path)

    def _load_config(self, config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        except Exception as e:
            logger.warning(f"加载配置文件失败，使用默认配置: {e}")
            return {}

    @monitor_stage("report.generate.morning.total")
    def generate_morning_report(self, dt=None, publish=False):
        """
        生成早报（总超时 180s）

        Args:
            dt: 报告日期（默认为最近交易日）
            publish: 是否发布到飞书

        Returns:
            包含 markdown 和发布信息的字典
        """
        total_timeout = TIMEOUTS['report_generate_total_sec']
        trace_id = ensure_trace_id()
        log_event(logger, "info", "report_generate_start", mode="morning", timeout_sec=total_timeout)
        effective_dt = get_effective_date(dt, mode='morning')
        date_str = format_date(effective_dt)
        log_event(logger, "info", "report_effective_date", mode="morning", date=date_str)

        # 总体超时保护（步骤1-5）
        try:
            def _do_generate():
                logger.info("步骤1: 采集数据...")
                with stage_timer("report.morning.fetch"):
                    try:
                        data = self._fetch_morning_data(effective_dt)
                    except Exception as e:
                        raise DataFetchError(str(e)) from e
                logger.info("步骤2: 分析数据...")
                with stage_timer("report.morning.analyze"):
                    try:
                        analysis_result = self._analyze_morning_data(data)
                    except Exception as e:
                        raise AnalysisError(str(e)) from e
                logger.info("步骤3: 渲染报告...")
                with stage_timer("report.morning.render"):
                    try:
                        markdown = self.renderer.render_morning_report(analysis_result, effective_dt)
                    except Exception as e:
                        raise RenderError(str(e)) from e
                logger.info("步骤4: 保存报告...")
                with stage_timer("report.morning.save"):
                    save_result = self._save_report(markdown, 'morning', effective_dt)
                if isinstance(save_result, tuple):
                    output_path, pdf_path = save_result
                else:
                    output_path, pdf_path = save_result, None
                return markdown, output_path, pdf_path

            markdown, output_path, pdf_path = run_with_timeout(_do_generate, total_timeout)
        except TimeoutError as e:
            log_event(logger, "error", "report_generate_timeout", mode="morning", error=e)
            raise
        except (DataFetchError, AnalysisError, RenderError) as e:
            log_event(logger, "error", "report_generate_stage_error", mode="morning", error=e)
            raise
        except Exception as e:
            log_event(logger, "error", "report_generate_error", mode="morning", error=e)
            raise

        result = {
            'markdown': markdown,
            'output_path': output_path,
            'report_path': output_path,
            'date': date_str,
            'mode': 'morning',
            'trace_id': trace_id,
        }
        if pdf_path:
            result['pdf_path'] = pdf_path

        if publish:
            log_event(logger, "info", "report_publish_start", mode="morning")
            with stage_timer("report.morning.publish"):
                publish_result = self.publisher.publish_morning_report(
                    markdown, effective_dt, send_notification=True
                )
            result['publish'] = publish_result

        log_event(
            logger,
            "info",
            "report_generate_done",
            mode="morning",
            output_path=output_path,
            trace_id=get_trace_id(),
        )
        return result

    @monitor_stage("report.generate.evening.total")
    def generate_evening_report(self, dt=None, publish=False):
        """
        生成晚报（总超时 180s）

        Args:
            dt: 报告日期（默认为最近交易日）
            publish: 是否发布到飞书

        Returns:
            包含 markdown 和发布信息的字典
        """
        total_timeout = TIMEOUTS['report_generate_total_sec']
        trace_id = ensure_trace_id()
        log_event(logger, "info", "report_generate_start", mode="evening", timeout_sec=total_timeout)
        effective_dt = get_effective_date(dt, mode='evening')
        date_str = format_date(effective_dt)
        log_event(logger, "info", "report_effective_date", mode="evening", date=date_str)

        # 总体超时保护（步骤1-5）
        try:
            def _do_generate():
                logger.info("步骤1: 采集数据...")
                with stage_timer("report.evening.fetch"):
                    try:
                        data = self._fetch_evening_data(effective_dt)
                    except Exception as e:
                        raise DataFetchError(str(e)) from e
                logger.info("步骤2: 分析数据...")
                with stage_timer("report.evening.analyze"):
                    try:
                        analysis_result = self._analyze_evening_data(data)
                    except Exception as e:
                        raise AnalysisError(str(e)) from e
                logger.info("步骤3: 渲染报告...")
                with stage_timer("report.evening.render"):
                    try:
                        markdown = self.renderer.render_evening_report(analysis_result, effective_dt)
                    except Exception as e:
                        raise RenderError(str(e)) from e
                logger.info("步骤4: 保存报告...")
                with stage_timer("report.evening.save"):
                    save_result = self._save_report(markdown, 'evening', effective_dt)
                if isinstance(save_result, tuple):
                    output_path, pdf_path = save_result
                else:
                    output_path, pdf_path = save_result, None
                return markdown, output_path, pdf_path

            markdown, output_path, pdf_path = run_with_timeout(_do_generate, total_timeout)
        except TimeoutError as e:
            log_event(logger, "error", "report_generate_timeout", mode="evening", error=e)
            raise
        except (DataFetchError, AnalysisError, RenderError) as e:
            log_event(logger, "error", "report_generate_stage_error", mode="evening", error=e)
            raise
        except Exception as e:
            log_event(logger, "error", "report_generate_error", mode="evening", error=e)
            raise

        result = {
            'markdown': markdown,
            'output_path': output_path,
            'report_path': output_path,
            'date': date_str,
            'mode': 'evening',
            'trace_id': trace_id,
        }
        if pdf_path:
            result['pdf_path'] = pdf_path

        if publish:
            log_event(logger, "info", "report_publish_start", mode="evening")
            with stage_timer("report.evening.publish"):
                publish_result = self.publisher.publish_evening_report(
                    markdown, effective_dt, send_notification=True
                )
            result['publish'] = publish_result

        log_event(
            logger,
            "info",
            "report_generate_done",
            mode="evening",
            output_path=output_path,
            trace_id=get_trace_id(),
        )
        return result

    def _fetch_morning_data(self, dt):
        return self.morning_collector.collect(dt)

    def _fetch_evening_data(self, dt):
        return self.evening_collector.collect(dt)

    def _analyze_morning_data(self, data):
        result = {}
        result['summary'] = self.analyzer.generate_summary(data, mode='morning')
        result['watchlist_morning'] = self.analyzer.analyze_watchlist_morning(data)
        result['strategy'] = self.analyzer.generate_trading_strategy(data)
        result['focus_stocks'] = self.analyzer.analyze_focus_stocks(data)
        result['position'] = self.analyzer.suggest_position(data)
        result['us_market'] = data.get('us_market', {})
        result['futures'] = data.get('futures', {})  # 新增期指数据
        result['international_events'] = data.get('international_events', {})  # 国际事件
        result['industry_fund_flow'] = data.get('industry_fund_flow', {})
        result['major_indices'] = self.analyzer.analyze_major_indices(data)  # A股主要指数
        # 新闻分类
        news_list = data.get('news', {}).get('data', [])
        result['news'] = self.analyzer.classify_news(news_list)
        return result

    def _analyze_evening_data(self, data):
        result = {}
        try:
            logger.info("生成30秒速览...")
            result['summary'] = self.analyzer.generate_summary(data, mode='evening')
        except Exception as e:
            logger.error(f"summary 失败: {e}")
            result['summary'] = {"success": False, "data": None}
        try:
            logger.info("分析自选股表现...")
            result['watchlist_evening'] = self.analyzer.analyze_watchlist_evening(data)
        except Exception as e:
            logger.error(f"watchlist 失败: {e}")
            result['watchlist_evening'] = {"success": False, "data": None}
        
        # 新模块：每个独立 try-except，不因单个失败中断
        for key in ['market_overview', 'market_depth', 'major_indices', 'global_assets']:
            try:
                result[key] = data.get(key, {})
                logger.info(f"[OK] {key}: data ready")
            except Exception as e:
                logger.error(f"{key} 失败: {e}")
                result[key] = {"success": False, "data": None}
        
        # 技术分析类
        for key in ['technical', 'comprehensive', 'theme_tracking']:
            try:
                method = getattr(self.analyzer, f'analyze_{key}', None)
                if method:
                    result[key] = method(data)
                    logger.info(f"[OK] {key}: success={result[key].get('success')}")
                else:
                    result[key] = {"success": False, "data": None}
            except Exception as e:
                logger.error(f"{key} 失败: {e}")
                result[key] = {"success": False, "data": None, "error": str(e)}
        
        # 打通 money_flow → market_overview 的北向资金
        self._patch_market_overview_northbound(result)
        
        # 传递原始数据供渲染器使用
        for key in ['index_sh', 'index_sz', 'index_cyb', 'sentiment', 'money_flow',
                     'industry_fund_flow', 'sectors', 'lhb']:
            result[key] = data.get(key, {})
        
        # 新闻分类
        try:
            news_list = data.get('news', {}).get('data', [])
            result['news'] = self.analyzer.classify_news(news_list)
        except Exception as e:
            logger.error(f"news 失败: {e}")
            result['news'] = {"success": False, "data": []}
        
        logger.info(f"analysis_result keys: {list(result.keys())}")
        return result

    def _patch_market_overview_northbound(self, result):
        """打通 money_flow 的北向资金到 market_overview，修复渲染层读不到北向的问题"""
        money_flow = result.get('money_flow', {})
        overview = result.get('market_overview', {})
        if not money_flow or not isinstance(overview, dict):
            return
        # 获取北向资金（money_flow 结构：{success, data: {northbound, main_capital}}）
        nf_data = money_flow.get('data', money_flow) if isinstance(money_flow, dict) else {}
        northbound = nf_data.get('northbound')
        if northbound is not None and isinstance(northbound, (int, float)):
            if 'data' in overview and isinstance(overview['data'], dict):
                # 有 {success, data} 包装
                overview['data']['northbound'] = northbound
            else:
                # 裸 dict
                overview['northbound'] = northbound
            logger.info(f"✅ 已打通北向资金: {northbound/1e8:.2f} 亿")

    def _save_report(self, markdown, mode, dt):
        output_config = self.config.get('output', {})
        base_dir = os.getenv('A_SHARE_OUTPUT_DIR', output_config.get('base_dir', 'reports'))
        base_dir = os.path.expanduser(base_dir)
        sub_dir = output_config.get(f'{mode}_subdir', mode)

        # 处理绝对路径和相对路径
        if os.path.isabs(base_dir):
            # 如果是绝对路径，直接使用
            base_path = base_dir
        else:
            # 如果是相对路径，使用项目根目录
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

        # PDF 导出（可选，根据 config.publish.pdf.enabled 决定）
        pdf_config = self.config.get('publish', {}).get('pdf', {})
        if pdf_config.get('enabled', False):
            pdf_result = self._export_pdf(markdown, output_path, mode, dt, pdf_config)
            if pdf_result:
                return output_path, pdf_result

        return output_path

    def _export_pdf(self, markdown, md_path, mode, dt, pdf_config):
        """将 Markdown 报告导出为 PDF"""
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

        converter = get_pdf_converter(engine=engine, publisher=self.publisher)
        result = converter.convert(markdown, pdf_path, title)

        if result:
            logger.info(f"PDF 已导出: {result}")
            return result
        else:
            logger.warning("PDF 导出失败，继续执行")
            return None

    def _pdf_via_fpdf2(self, markdown_content, pdf_path, title):
        """使用 fpdf2 转换 PDF（纯 Python，无系统依赖）"""
        try:
            from fpdf import FPDF
        except ImportError:
            logger.warning("fpdf2 未安装，跳过 PDF 导出")
            return None

        try:
            pdf = FPDF(format='A4')
            pdf.set_margins(10, 10, 10)
            pdf.set_auto_page_break(auto=True, margin=10)

            # 查找中文字体
            font_path = self._find_cjk_font()
            if font_path:
                pdf.add_font('CJK', '', font_path)
                font_name = 'CJK'
            else:
                font_name = 'Helvetica'
                logger.warning("未找到中文字体，PDF 中中文可能显示异常")

            pdf.add_page()
            pdf.set_font(font_name, size=8)

            # 逐行写入（跳过表格，只渲染文本）
            in_table = False
            for line_num, line in enumerate(markdown_content.split('\n'), start=1):
                stripped = line.strip()
                if not stripped:
                    pdf.ln(3)
                    in_table = False
                    continue

                # 检测表格开始
                if stripped.startswith('|') and '---' in stripped:
                    in_table = True
                    continue
                if in_table and stripped.startswith('|'):
                    continue  # 跳过表格行
                if in_table and not stripped.startswith('|'):
                    in_table = False

                try:
                    # 标题
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

                    # 分隔线
                    if stripped.startswith('---'):
                        pdf.ln(2)
                        continue

                    # 普通文本（去掉 Markdown 标记）
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

    def _pdf_via_weasyprint(self, markdown_content, pdf_path, title):
        """使用 weasyprint 转换 PDF"""
        try:
            from weasyprint import HTML
        except ImportError:
            logger.warning("weasyprint 未安装，跳过 PDF 导出")
            return None

        try:
            html_content = self.publisher._markdown_to_html(markdown_content, title)
            HTML(string=html_content).write_pdf(pdf_path)
            return pdf_path
        except Exception as e:
            logger.error(f"weasyprint 转换失败: {e}")
            return None

    def _find_cjk_font(self):
        """查找系统中可用的中文字体"""
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

    def _pdf_via_wkhtmltopdf(self, markdown_content, pdf_path, title):
        """使用 wkhtmltopdf 转换 PDF"""
        result = self.publisher.convert_to_pdf(markdown_content, pdf_path, title)
        if result.get('success'):
            return result.get('pdf_path')
        return None


def main():
    parser = argparse.ArgumentParser(description='A股日报生成器')
    parser.add_argument('--mode', type=str, choices=['morning', 'evening'],
                        default='morning', help='早报或晚报 (默认: morning)')
    parser.add_argument('--date', type=str, default=None,
                        help='日期 (默认: 今天)')
    parser.add_argument('--config', type=str, default=None,
                        help='配置文件路径')
    parser.add_argument('--publish', action='store_true',
                        help='发布到飞书（需要配置 feishu）')
    parser.add_argument('--outdir', type=str, default=None,
                        help='输出目录（覆盖配置文件中的设置）')

    args = parser.parse_args()

    generator = ReportGenerator(args.config)

    # 如果指定了outdir，覆盖配置
    if args.outdir:
        output_config = generator.config.get('output', {})
        output_config['base_dir'] = args.outdir
        generator.config['output'] = output_config

    if args.mode == 'morning':
        result = generator.generate_morning_report(args.date, publish=args.publish)
    else:
        result = generator.generate_evening_report(args.date, publish=args.publish)

    print("\n" + "="*80)
    print(result['markdown'])
    print("="*80 + "\n")

    if args.publish and result.get('publish', {}).get('success'):
        print(f"✅ 已发布到飞书: {result['publish']['doc_url']}")
    elif args.publish:
        print(f"⚠️ 发布失败: {result.get('publish', {}).get('error', '未知错误')}")

    # 输出报告文件路径，供 OpenClaw Agent 读取后发布到飞书
    print(f"REPORT_PATH:{result.get('output_path', '')}")


if __name__ == '__main__':
    main()
