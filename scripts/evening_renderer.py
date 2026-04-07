#!/usr/bin/env python3
"""
晚报渲染器（Jinja2 模板）
"""

from dataclasses import asdict
from datetime import datetime
import math

from constants import ALL_INDICES
from utils.helpers import cn_now
from models import (
    RenderIndexLine,
    RenderNewsLine,
    RenderMarketOverviewRow,
    RenderWatchlistEveningRow,
    RenderLHBRow,
)
from template_engine import render_template
from utils import get_logger, format_date

logger = get_logger('renderer')


class EveningRenderer:
    def __init__(self, config):
        self.config = config

    def _safe_pct(self, pct):
        if pct is None or (isinstance(pct, float) and math.isnan(pct)):
            return "暂无"
        try:
            return f"{float(pct):+.2f}%"
        except Exception:
            return "暂无"

    def _safe_number(self, val, ndigits=2, fallback='-'):
        try:
            num = float(val)
            if math.isnan(num):
                return fallback
            return f"{num:.{ndigits}f}"
        except Exception:
            return fallback

    def render_evening_report(self, analysis_result, dt=None):
        if dt is None:
            dt = cn_now()

        date_str = format_date(dt)
        gen_time = format_date(cn_now(), '%Y-%m-%d %H:%M')

        summary = analysis_result.get('summary')
        summary_data = summary.get('data', {}) if isinstance(summary, dict) else {}

        market_overview_rows = self._build_market_overview_rows(analysis_result)
        major_indices = self._build_major_indices(analysis_result)
        watchlist_rows = self._build_watchlist_rows(analysis_result)
        lhb_rows = self._build_lhb_rows(analysis_result)
        news_rows = self._build_news_rows(analysis_result)

        comprehensive = analysis_result.get('comprehensive', {})
        comprehensive_data = comprehensive.get('data', {}) if isinstance(comprehensive, dict) else {}

        missing_items = []
        for key, label in [
            ('major_indices', '主要指数'),
            ('market_overview', '市场全景'),
            ('market_depth', '盘面深度'),
            ('money_flow', '资金流向'),
            ('sectors', '板块数据'),
            ('lhb', '龙虎榜'),
            ('news', '财经新闻'),
        ]:
            wrapper = analysis_result.get(key, {})
            if not isinstance(wrapper, dict) or not wrapper.get('success', True):
                missing_items.append(label)

        context = {
            'date_str': date_str,
            'gen_time': gen_time,
            'one_sentence': summary_data.get('one_sentence', '数据获取失败'),
            'core_highlights': summary_data.get('core_highlights', []),
            'tomorrow_outlook': summary_data.get('tomorrow_outlook', []),
            'market_overview_rows': market_overview_rows,
            'major_indices': major_indices,
            'watchlist_rows': watchlist_rows,
            'lhb_rows': lhb_rows,
            'news_rows': news_rows,
            'trend_judge': comprehensive_data.get('trend_judge', '暂无结论'),
            'volume_analysis': comprehensive_data.get('volume_analysis', '暂无结论'),
            'style_analysis': comprehensive_data.get('style_analysis', '暂无结论'),
            'outlook': comprehensive_data.get('outlook', '暂无结论'),
            'missing_items': missing_items,
            'prediction_review': self._build_prediction_review(analysis_result),
            'sector_rotation': self._build_sector_rotation_rows(analysis_result),
            'strategy_adjustment': analysis_result.get('strategy_adjustment', {}),
        }
        return render_template('evening_report.md.j2', **context)

    def _build_market_overview_rows(self, analysis_result):
        overview_wrapper = analysis_result.get('market_overview', {})
        overview = overview_wrapper.get('data', {}) if isinstance(overview_wrapper, dict) else {}
        if not isinstance(overview, dict) or not overview:
            return []

        score = self._safe_number(overview.get('score', 0), ndigits=1, fallback='0.0')
        trend = overview.get('trend', '未知')
        suggest_pos = overview.get('suggest_position', 0)
        try:
            suggest_pos_text = f"{float(suggest_pos):.0%}"
            suggest_note = '偏高' if float(suggest_pos) >= 0.6 else '适中' if float(suggest_pos) >= 0.4 else '偏低'
        except Exception:
            suggest_pos_text = '-'
            suggest_note = '-'

        northbound = overview.get('northbound', 0)
        northbound_text = '-'
        northbound_note = '-'
        try:
            northbound_text = f"{float(northbound)/1e8:+.1f} 亿元"
            northbound_note = '流入' if float(northbound) >= 0 else '流出'
        except Exception:
            pass

        turnover_text = '-'
        try:
            turnover_text = f"{float(overview.get('turnover', 0))/1e12:.2f} 万亿元"
        except Exception:
            pass

        rows = [
            RenderMarketOverviewRow(label='情绪评分', value=f"{score} 分", note=trend),
            RenderMarketOverviewRow(
                label='上涨/下跌/平盘',
                value=f"{int(overview.get('up_count', 0))} / {int(overview.get('down_count', 0))} / {int(overview.get('flat_count', 0))}",
                note='全市场统计',
            ),
            RenderMarketOverviewRow(
                label='涨停/跌停',
                value=f"{int(overview.get('limit_up', 0))} / {int(overview.get('limit_down', 0))}",
                note='短线情绪',
            ),
            RenderMarketOverviewRow(label='成交额', value=turnover_text, note='市场活跃度'),
            RenderMarketOverviewRow(label='北向资金', value=northbound_text, note=northbound_note),
            RenderMarketOverviewRow(label='建议仓位', value=suggest_pos_text, note=suggest_note),
        ]
        return [asdict(r) for r in rows]

    def _build_major_indices(self, analysis_result):
        major_indices_raw = analysis_result.get('major_indices', {}).get('data', {})
        rows = []
        if isinstance(major_indices_raw, dict) and major_indices_raw:
            for code, label in ALL_INDICES:
                info = major_indices_raw.get(code)
                if isinstance(info, dict):
                    pct = info.get('change_pct')
                    pct_str = self._safe_pct(pct)
                    status = '📈' if isinstance(pct, (int, float)) and pct >= 0 else '📉'
                    if pct_str == '暂无':
                        status = '—'
                    rows.append(asdict(RenderIndexLine(label=label, pct_str=pct_str, status=status)))
                else:
                    rows.append(asdict(RenderIndexLine(label=label, pct_str='暂缺', status='—')))
        else:
            for _, label in ALL_INDICES:
                rows.append(asdict(RenderIndexLine(label=label, pct_str='暂无数据', status='—')))
        return rows

    def _build_watchlist_rows(self, analysis_result):
        watchlist_wrapper = analysis_result.get('watchlist_evening', {})
        watchlist_data = watchlist_wrapper.get('data', {}) if isinstance(watchlist_wrapper, dict) else {}
        stocks = watchlist_data.get('stocks', []) if isinstance(watchlist_data, dict) else []

        rows = []
        for item in stocks:
            name = item.get('name', item.get('code', '未知'))
            change_pct = self._safe_pct(item.get('change_pct', 0))
            avg_score = self._safe_number(item.get('avg_score', 0), ndigits=1)
            signal = item.get('signal', '-')
            reason = item.get('reason', '-')
            reason_category = item.get('reason_category', '-')
            rows.append(asdict(RenderWatchlistEveningRow(
                name=name,
                change_pct=change_pct,
                avg_score=avg_score,
                signal=signal,
                reason=reason,
                reason_category=reason_category,
            )))
        return rows

    def _build_prediction_review(self, analysis_result):
        """
        构建早报预测复盘数据，供模板渲染。
        返回 dict 或 None（无快照时）。
        """
        pred_review = analysis_result.get('prediction_review')
        if not pred_review or not isinstance(pred_review, dict):
            return None

        details = pred_review.get('details', [])
        hit_rate = pred_review.get('hit_rate')
        hit_rate_str = f"{hit_rate:.0%}" if hit_rate is not None else '—'

        # 构建每条对比行
        rows = []
        for d in details:
            hit_icon = '✅' if d.get('hit') else '❌'
            actual_pct = d.get('actual_pct', 0)
            actual_str = self._safe_pct(actual_pct)
            rows.append({
                'name': d.get('name', ''),
                'pred_view': d.get('pred_view', ''),
                'actual_pct': actual_str,
                'hit_icon': hit_icon,
                'miss_reason': d.get('miss_reason', ''),
            })

        return {
            'summary_line': pred_review.get('summary_line', ''),
            'hit_rate_str': hit_rate_str,
            'position_review': pred_review.get('position_review', ''),
            'rows': rows,
        }

    def _build_lhb_rows(self, analysis_result):
        lhb_wrapper = analysis_result.get('lhb', {})
        lhb_data = lhb_wrapper.get('data', []) if isinstance(lhb_wrapper, dict) else []

        rows = []
        for idx, item in enumerate(lhb_data[:5], start=1):
            rows.append(asdict(RenderLHBRow(
                rank=idx,
                name=item.get('name', ''),
                code=item.get('code', ''),
                change_pct=self._safe_pct(item.get('change_pct', 0)),
                close=self._safe_number(item.get('close', 0), ndigits=2),
                net_inflow=self._safe_number(item.get('net_inflow', 0), ndigits=0),
            )))
        return rows

    def _build_news_rows(self, analysis_result):
        news = analysis_result.get('news', {}).get('data', [])
        if not isinstance(news, list):
            return []

        rows = []
        for item in news[:10]:
            level = item.get('level', 'medium')
            icon = '🔴' if level == 'high' else '🟡' if level == 'medium' else '🟢'
            summary = (item.get('content', '') or '').replace('\n', ' ').strip()[:120]
            if item.get('content') and len(item.get('content', '')) > 120:
                summary += '...'
            rows.append(asdict(RenderNewsLine(
                title=item.get('title', '无标题'),
                level_icon=icon,
                url=item.get('url', ''),
                source=item.get('source', ''),
                summary=summary,
            )))
        return rows

    def _build_sector_rotation_rows(self, analysis_result):
        """
        构建板块轮动数据，供模板渲染。
        返回 dict 或 None（无数据时）。
        """
        sector_rotation_result = analysis_result.get('sector_rotation')
        if not sector_rotation_result or not isinstance(sector_rotation_result, dict):
            return None

        data = sector_rotation_result.get('data')
        if not data or not isinstance(data, dict):
            return None

        return {
            'rotation_type': data.get('rotation_type', '-'),
            'rotation_strength': data.get('rotation_strength', '-'),
            'mainline_sector': data.get('mainline_sector', '-'),
            'mainline_change': data.get('mainline_change', '-'),
            'prev_mainline': data.get('prev_mainline', '-'),
            'rotation_signal': data.get('rotation_signal', '-'),
        }
