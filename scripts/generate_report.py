
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
from report_saver import ReportSaver

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
        self.saver = ReportSaver(self.config, self.publisher)
        self.morning_collector = MorningDataCollector(self.data_fetcher, self.analyzer, logger)
        self.evening_collector = EveningDataCollector(self.data_fetcher, self.analyzer, logger)

        log_event(logger, "info", "report_generator_init", config_path=config_path)

    def _load_config(self, config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            # 展开输出目录中的环境变量
            self._expand_config_env_vars(config)
            return config
        except Exception as e:
            logger.warning(f"加载配置文件失败，使用默认配置: {e}")
            return {}

    def _expand_config_env_vars(self, config):
        """递归展开配置中的环境变量 ${VAR:-default}"""
        if isinstance(config, dict):
            for key, value in config.items():
                if isinstance(value, str):
                    # 支持 ${VAR:-default} 语法
                    import re
                    pattern = r'\$\{([^}]+)\}'
                    matches = re.findall(pattern, value)
                    for match in matches:
                        if ':-' in match:
                            var_name, default = match.split(':-', 1)
                            expanded = os.getenv(var_name, default)
                        else:
                            expanded = os.getenv(match, '')
                        value = value.replace(f'${{{match}}}', expanded)
                    config[key] = value
                else:
                    self._expand_config_env_vars(value)
        elif isinstance(config, list):
            for item in config:
                self._expand_config_env_vars(item)

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
                    output_path, pdf_path = self.saver.save_report_with_pdf(markdown, 'morning', effective_dt)
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
                    output_path, pdf_path = self.saver.save_report_with_pdf(markdown, 'evening', effective_dt)
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

        # 计算自选股整体统计（用于早报摘要或后续分析）
        watchlist_performance = data.get('watchlist_performance', [])
        if watchlist_performance:
            up_count = sum(1 for p in watchlist_performance if p.get('change_pct', 0) > 0)
            down_count = sum(1 for p in watchlist_performance if p.get('change_pct', 0) < 0)
            avg_return = sum(p.get('change_pct', 0) for p in watchlist_performance) / len(watchlist_performance)
            result['watchlist_stats'] = {
                'up_count': up_count,
                'down_count': down_count,
                'avg_return': round(avg_return, 2)
            }

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
