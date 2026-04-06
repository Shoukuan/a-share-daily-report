#!/usr/bin/env python3
"""
早报渲染器（Jinja2 模板）
"""

from dataclasses import asdict
from datetime import datetime
import math

from constants import INDEX_DISPLAY_ORDER, ALL_INDICES
from models import (
    RenderRiskWarning,
    RenderWatchlistItem,
    RenderFocusStock,
    RenderIndexLine,
    RenderUSLine,
    RenderFuturesLine,
    RenderEventLine,
    RenderNewsLine,
)
from template_engine import render_template
from utils import get_logger, format_date

logger = get_logger('renderer')


class MorningRenderer:
    def __init__(self, config):
        self.config = config

    def _safe_pct(self, pct):
        if pct is None or (isinstance(pct, float) and math.isnan(pct)):
            return "暂无"
        try:
            return f"{float(pct):+.2f}%"
        except Exception:
            return "暂无"

    def render_morning_report(self, analysis_result, dt=None):
        if dt is None:
            dt = datetime.now()
        date_str = format_date(dt)
        gen_time = format_date(datetime.now(), '%Y-%m-%d %H:%M')

        summary = analysis_result.get('summary')
        summary_data = summary.get('data', {}) if isinstance(summary, dict) else {}

        watchlist_raw = analysis_result.get('watchlist_morning', {}).get('data', [])
        watchlist = [
            asdict(RenderWatchlistItem(
                name=s.get('name', '未知'),
                view=s.get('view', '震荡'),
                reason=s.get('reason', '关注市场整体表现'),
            ))
            for s in watchlist_raw
        ]

        strategy = analysis_result.get('strategy', {}).get('data', {})
        strategy_name = strategy.get('strategy_name', '观望')

        focus_stocks_raw = analysis_result.get('focus_stocks', {}).get('data', [])
        focus_stocks = [
            asdict(RenderFocusStock(
                name=s.get('name', ''),
                code=s.get('code', ''),
                focus_logic=s.get('focus_logic', ''),
                entry_range=s.get('entry_range', ''),
                stop_loss=s.get('stop_loss', ''),
            ))
            for s in focus_stocks_raw
        ]

        position = analysis_result.get('position', {}).get('data', {})
        pos_min = float(position.get('position_min', 0) or 0)
        pos_max = float(position.get('position_max', 0) or 0)
        if pos_max >= 70:
            risk_level = "🔴 高"
        elif pos_max >= 40:
            risk_level = "🟡 中"
        else:
            risk_level = "🟢 低"

        # 风险提示 dataclass
        risk_warnings = []
        for r in summary_data.get('risk_warnings', []):
            if isinstance(r, dict):
                level = r.get('level', 'medium')
                emoji = "🔴" if level == 'high' else "🟡" if level == 'medium' else "🟢"
                content = r.get('content', '')
            else:
                emoji = "🟡"
                content = str(r)
            risk_warnings.append(asdict(RenderRiskWarning(emoji=emoji, content=content)))

        # 主要指数
        major_indices_raw = analysis_result.get('major_indices', {}).get('data', {})
        major_indices = []
        if major_indices_raw:
            for code, label in ALL_INDICES:
                if code in major_indices_raw:
                    pct = major_indices_raw[code].get('change_pct', 0)
                    pct_str = self._safe_pct(pct)
                    status = "📈" if isinstance(pct, (int, float)) and pct >= 0 else "📉"
                    if pct_str == "暂无":
                        status = "—"
                    major_indices.append(asdict(RenderIndexLine(label=label, pct_str=pct_str, status=status)))
                else:
                    major_indices.append(asdict(RenderIndexLine(label=label, pct_str='暂缺', status='—')))
        else:
            for _, label in INDEX_DISPLAY_ORDER:
                major_indices.append(asdict(RenderIndexLine(label=label, pct_str='暂无数据', status='—')))

        # 美股与中概
        us_market_raw = analysis_result.get('us_market', {})
        if isinstance(us_market_raw, dict):
            us_market = us_market_raw.get('data') or us_market_raw
        else:
            us_market = {}

        us_indices = []
        indices = us_market.get('indices', {}) if isinstance(us_market, dict) else {}
        for name in ['nasdaq', 'sp500', 'dow']:
            if name in indices:
                info = indices[name]
                label = "纳指" if name == 'nasdaq' else "标普" if name == 'sp500' else "道指"
                us_indices.append(asdict(RenderUSLine(
                    label=label,
                    pct_str=self._safe_pct(info.get('change_pct', 0)),
                    impact=info.get('impact', ''),
                )))

        chinadotcom = []
        cdc = us_market.get('chinadotcom', {}) if isinstance(us_market, dict) else {}
        for name, info in cdc.items() if isinstance(cdc, dict) else []:
            display_name = info.get('name', name)
            short_name = display_name.replace('Group Holding Limited', '').replace('Holdings Inc.', '').strip()
            chinadotcom.append(asdict(RenderUSLine(
                label=short_name,
                pct_str=self._safe_pct(info.get('change_pct', 0)),
                impact=info.get('impact', ''),
            )))

        # 期指
        futures = []
        futures_wrapper = analysis_result.get('futures', {})
        futures_data = futures_wrapper.get('data', {}).get('futures', {}) if isinstance(futures_wrapper, dict) else {}
        a50 = futures_data.get('A50', {}) if isinstance(futures_data, dict) else {}
        csi300 = futures_data.get('CSI300', {}) if isinstance(futures_data, dict) else {}
        if a50:
            futures.append(asdict(RenderFuturesLine(name='A50期指', pct_str=self._safe_pct(a50.get('change_pct', 0)), impact=a50.get('impact', ''))))
        else:
            futures.append(asdict(RenderFuturesLine(name='A50期指', pct_str='暂无数据', impact='-')))
        if csi300:
            futures.append(asdict(RenderFuturesLine(name='沪深300期指', pct_str=self._safe_pct(csi300.get('change_pct', 0)), impact=csi300.get('impact', ''))))
        else:
            futures.append(asdict(RenderFuturesLine(name='沪深300期指', pct_str='暂无数据', impact='-')))

        # 国际事件
        events_wrapper = analysis_result.get('international_events', {})
        if isinstance(events_wrapper, dict):
            events_data = events_wrapper.get('data', []) or []
        elif isinstance(events_wrapper, list):
            events_data = events_wrapper
        else:
            events_data = []
        events = []
        events_data = sorted(events_data, key=lambda x: 0 if x.get('impact_level') == 'high' else 1)
        for evt in events_data[:8]:
            icon = '🔴' if evt.get('impact_level') == 'high' else '🟡'
            sectors = evt.get('affected_sectors', [])
            sector_tag = ' / '.join(sectors[:3]) if sectors else ''
            events.append(asdict(RenderEventLine(
                icon=icon,
                title=evt.get('title', ''),
                category=evt.get('category', ''),
                sector_tag=sector_tag,
                impact_text=evt.get('a_share_impact', ''),
                source=evt.get('source', ''),
            )))

        # 新闻
        news = analysis_result.get('news', {}).get('data', []) if isinstance(analysis_result.get('news', {}), dict) else []
        high_news = []
        medium_news = []
        low_news = []
        for item in news:
            level = item.get('level', 'medium')
            icon = '🔴' if level == 'high' else '🟡' if level == 'medium' else '🟢'
            summary = (item.get('content', '') or '').replace('\n', ' ').strip()[:150]
            if item.get('content') and len(item.get('content', '')) > 150:
                summary += '...'
            line = asdict(RenderNewsLine(
                title=item.get('title', '无标题'),
                level_icon=icon,
                url=item.get('url', ''),
                source=item.get('source', ''),
                summary=summary,
            ))
            if level == 'high':
                high_news.append(line)
            elif level == 'low':
                low_news.append(line)
            else:
                medium_news.append(line)

        context = {
            'date_str': date_str,
            'gen_time': gen_time,
            'one_sentence': summary_data.get('one_sentence', '数据获取失败'),
            'core_opportunities': summary_data.get('core_opportunities', []),
            'risk_warnings': risk_warnings,
            'watchlist': watchlist,
            'strategy_name': strategy_name,
            'strategy_logic': strategy.get('logic', ''),
            'focus_stocks': focus_stocks,
            'position_range': f"{pos_min:.0f}% - {pos_max:.0f}%",
            'position_logic': position.get('logic', '-'),
            'position_risk': risk_level,
            'major_indices': major_indices,
            'us_indices': us_indices,
            'chinadotcom': chinadotcom,
            'futures': futures,
            'events': events,
            'high_news': high_news[:5],
            'medium_news': medium_news[:10],
            'low_news': low_news[:5],
        }
        return render_template('morning_report.md.j2', **context)
