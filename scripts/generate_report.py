
#!/usr/bin/env python3
"""
A股日报生成器 - 主入口脚本
"""

import os
import sys
import argparse
import yaml
import signal
import contextlib
from datetime import datetime, date

# 添加项目路径（让模块可以导入）
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

from utils import get_logger, format_date
from data_fetcher import DataFetcher
from analyzer import Analyzer
from renderer import Renderer
from trade_calendar import get_effective_date
from publisher import Publisher

logger = get_logger('report_generator')


@contextlib.contextmanager
def timeout(seconds):
    """上下文管理器：为一段代码执行设置超时（秒）"""
    def timeout_handler(signum, frame):
        raise TimeoutError(f"操作超时（{seconds}秒）")
    old_handler = signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)


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
        self.data_fetcher = DataFetcher(self.config)
        self.analyzer = Analyzer(self.config)
        self.renderer = Renderer(self.config)
        self.publisher = Publisher(self.config)

        logger.info("ReportGenerator 初始化完成")

    def _load_config(self, config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        except Exception as e:
            logger.warning(f"加载配置文件失败，使用默认配置: {e}")
            return {}

    def generate_morning_report(self, dt=None, publish=False):
        """
        生成早报（总超时 180s）

        Args:
            dt: 报告日期（默认为最近交易日）
            publish: 是否发布到飞书

        Returns:
            包含 markdown 和发布信息的字典
        """
        logger.info("开始生成早报（总超时 180s）...")
        effective_dt = get_effective_date(dt, mode='morning')
        date_str = format_date(effective_dt)
        logger.info(f"使用日期: {date_str}")

        # 总体超时保护（步骤1-5）
        try:
            with timeout(180):
                logger.info("步骤1: 采集数据...")
                data = self._fetch_morning_data(effective_dt)

                logger.info("步骤2: 分析数据...")
                analysis_result = self._analyze_morning_data(data)

                logger.info("步骤3: 渲染报告...")
                markdown = self.renderer.render_morning_report(analysis_result, effective_dt)

                logger.info("步骤4: 保存报告...")
                save_result = self._save_report(markdown, 'morning', effective_dt)
                if isinstance(save_result, tuple):
                    output_path, pdf_path = save_result
                else:
                    output_path, pdf_path = save_result, None
        except TimeoutError as e:
            logger.error(f"早报生成超时: {e}")
            raise
        except Exception as e:
            logger.error(f"早报生成异常: {e}")
            raise

        result = {
            'markdown': markdown,
            'output_path': output_path,
            'date': date_str,
            'mode': 'morning'
        }
        if pdf_path:
            result['pdf_path'] = pdf_path

        if publish:
            logger.info("步骤5: 发布到飞书...")
            publish_result = self.publisher.publish_morning_report(
                markdown, effective_dt, send_notification=True
            )
            result['publish'] = publish_result

        logger.info(f"早报生成完成: {output_path}")
        return result

    def generate_evening_report(self, dt=None, publish=False):
        """
        生成晚报（总超时 180s）

        Args:
            dt: 报告日期（默认为最近交易日）
            publish: 是否发布到飞书

        Returns:
            包含 markdown 和发布信息的字典
        """
        logger.info("开始生成晚报（总超时 180s）...")
        effective_dt = get_effective_date(dt, mode='evening')
        date_str = format_date(effective_dt)
        logger.info(f"使用日期: {date_str}")

        # 总体超时保护（步骤1-5）
        try:
            with timeout(180):
                logger.info("步骤1: 采集数据...")
                data = self._fetch_evening_data(effective_dt)

                logger.info("步骤2: 分析数据...")
                analysis_result = self._analyze_evening_data(data)

                logger.info("步骤3: 渲染报告...")
                markdown = self.renderer.render_evening_report(analysis_result, effective_dt)

                logger.info("步骤4: 保存报告...")
                save_result = self._save_report(markdown, 'evening', effective_dt)
                if isinstance(save_result, tuple):
                    output_path, pdf_path = save_result
                else:
                    output_path, pdf_path = save_result, None
        except TimeoutError as e:
            logger.error(f"晚报生成超时: {e}")
            raise
        except Exception as e:
            logger.error(f"晚报生成异常: {e}")
            raise

        result = {
            'markdown': markdown,
            'output_path': output_path,
            'date': date_str,
            'mode': 'evening'
        }
        if pdf_path:
            result['pdf_path'] = pdf_path

        if publish:
            logger.info("步骤5: 发布到飞书...")
            publish_result = self.publisher.publish_evening_report(
                markdown, effective_dt, send_notification=True
            )
            result['publish'] = publish_result

        logger.info(f"晚报生成完成: {output_path}")
        return result

    def _fetch_morning_data(self, dt):
        data = {}
        logger.info("采集A股指数数据...")
        index_sh = self.data_fetcher.get_index_data("000001.SH", dt)
        index_sz = self.data_fetcher.get_index_data("399001.SZ", dt)
        index_cyb = self.data_fetcher.get_index_data("399006.SZ", dt)
        data['index_sh'] = index_sh
        data['index_sz'] = index_sz
        data['index_cyb'] = index_cyb
        # 构建指数缓存供 sentiment 复用（避免重复查询三大指数）
        index_cache = {
            '000001.SH': index_sh,
            '399001.SZ': index_sz,
            '399006.SZ': index_cyb,
        }
        # 早报也需要 major_indices（供渲染器展示指数表格）
        data['major_indices'] = self.data_fetcher.get_major_indices(dt)

        logger.info("采集市场情绪数据...")
        data['sentiment'] = self.data_fetcher.get_market_sentiment(dt, index_cache=index_cache)

        logger.info("采集资金流向数据（北向/主力）...")
        data['money_flow'] = self.data_fetcher.get_money_flow(dt)

        logger.info("采集行业资金流向...")
        data['industry_fund_flow'] = self.data_fetcher.get_industry_fund_flow(dt)

        logger.info("采集美股数据...")
        data['us_market'] = self.data_fetcher.get_us_market()

        logger.info("采集期指数据...")
        data['futures'] = self.data_fetcher.get_futures_data()

        logger.info("采集国际事件数据...")
        data['international_events'] = self.data_fetcher.get_international_events(dt)

        logger.info("采集新闻数据...")
        data['news'] = self.data_fetcher.get_news(dt, limit=10)

        logger.info("获取自选股表现...")
        try:
            import yaml as _yaml
            current_dir = os.path.dirname(os.path.abspath(__file__))
            watchlist_path = self.config.get('watchlist', {}).get('path', 'config/watchlist.yaml')
            if not os.path.isabs(watchlist_path):
                watchlist_path = os.path.join(os.path.dirname(current_dir), watchlist_path)
            with open(watchlist_path, 'r', encoding='utf-8') as f:
                watchlist = _yaml.safe_load(f).get('watchlist', [])
        except Exception as e:
            logger.warning(f"加载自选股配置失败: {e}")
            watchlist = []
        perf_result = self.data_fetcher.get_watchlist_performance(watchlist, dt)
        data['watchlist_performance'] = perf_result.get('data', []) if perf_result.get('success') else []
        logger.info(f"自选股行情获取完成: {len(data['watchlist_performance'])} 只")

        return data

    def _fetch_evening_data(self, dt):
        data = {}
        logger.info("采集A股指数数据...")
        index_sh = self.data_fetcher.get_index_data("000001.SH", dt)
        index_sz = self.data_fetcher.get_index_data("399001.SZ", dt)
        index_cyb = self.data_fetcher.get_index_data("399006.SZ", dt)
        data['index_sh'] = index_sh
        data['index_sz'] = index_sz
        data['index_cyb'] = index_cyb
        # 构建指数缓存供 sentiment 复用
        index_cache = {
            '000001.SH': index_sh,
            '399001.SZ': index_sz,
            '399006.SZ': index_cyb,
        }

        logger.info("采集市场全景数据...")
        data['market_overview'] = self.data_fetcher.get_market_overview(dt)

        logger.info("采集市场深度数据...")
        data['market_depth'] = self.data_fetcher.get_market_depth(dt)

        logger.info("采集主要指数数据...")
        data['major_indices'] = self.data_fetcher.get_major_indices(dt)

        logger.info("采集全球资产数据...")
        data['global_assets'] = self.data_fetcher.get_global_assets()

        logger.info("采集市场情绪数据...")
        data['sentiment'] = self.data_fetcher.get_market_sentiment(dt, index_cache=index_cache)

        logger.info("采集资金流向数据（北向/主力）...")
        data['money_flow'] = self.data_fetcher.get_money_flow(dt)

        logger.info("采集行业资金流向...")
        data['industry_fund_flow'] = self.data_fetcher.get_industry_fund_flow(dt)

        logger.info("采集板块数据...")
        data['sectors'] = self.data_fetcher.get_sector_data(dt)

        logger.info("采集龙虎榜数据...")
        data['lhb'] = self.data_fetcher.get_lhb_data(dt)

        logger.info("采集新闻数据...")
        data['news'] = self.data_fetcher.get_news(dt, limit=10)

        logger.info("获取自选股表现...")
        # 读取自选股配置（与 Analyzer 相同逻辑）
        watchlist_path = self.config.get('watchlist', {}).get('path', 'config/watchlist.yaml')
        if not os.path.isabs(watchlist_path):
            watchlist_path = os.path.join(os.path.dirname(current_dir), watchlist_path)
        
        try:
            with open(watchlist_path, 'r', encoding='utf-8') as f:
                watchlist_config = yaml.safe_load(f)
                watchlist = watchlist_config.get('watchlist', [])
        except Exception as e:
            logger.warning(f"加载自选股配置失败: {e}")
            watchlist = []
        
        perf_result = self.data_fetcher.get_watchlist_performance(watchlist, dt)
        data['watchlist_performance'] = perf_result.get('data', []) if perf_result.get('success') else []

        return data

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
        base_dir = output_config.get('base_dir', 'reports')
        sub_dir = output_config.get(f'{mode}_subdir', mode)

        # 处理绝对路径和相对路径
        if os.path.isabs(base_dir):
            # 如果是绝对路径，直接使用
            base_path = base_dir
        else:
            # 如果是相对路径，使用项目根目录
            project_root = os.path.dirname(current_dir)
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
        pdf_output_dir = pdf_config.get('output_dir', 'reports/pdf')

        # 构建 PDF 输出路径
        if not os.path.isabs(pdf_output_dir):
            project_root = os.path.dirname(current_dir)
            pdf_output_dir = os.path.join(project_root, pdf_output_dir)
        os.makedirs(pdf_output_dir, exist_ok=True)

        date_str = format_date(dt, '%Y%m%d')
        mode_name = '早报' if mode == 'morning' else '晚报'
        pdf_filename = f'A股{mode_name}-{date_str}.pdf'
        pdf_path = os.path.join(pdf_output_dir, pdf_filename)

        title = f"A股{mode_name}-{date_str}"

        # 按引擎选择转换方式
        if engine == 'weasyprint':
            result = self._pdf_via_weasyprint(markdown, pdf_path, title)
        elif engine == 'wkhtmltopdf':
            result = self._pdf_via_wkhtmltopdf(markdown, pdf_path, title)
        else:
            result = self._pdf_via_fpdf2(markdown, pdf_path, title)

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
            for line in markdown_content.split('\n'):
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
                except Exception:
                    continue  # 跳过无法渲染的行
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
    print(f"REPORT_PATH:{result.get('report_path', '')}")


if __name__ == '__main__':
    main()
