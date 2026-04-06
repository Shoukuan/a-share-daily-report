
#!/usr/bin/env python3
"""
报告子渲染器
"""

from datetime import datetime
import math

from constants import INDEX_DISPLAY_ORDER, ALL_INDICES
from utils import get_logger, format_date, format_percent

logger = get_logger('renderer')

class MorningRenderer:
    def __init__(self, config):
        self.config = config

    def render_morning_report(self, analysis_result, dt=None):
        if dt is None:
            dt = datetime.now()
        date_str = format_date(dt)
        gen_time = format_date(datetime.now(), '%Y-%m-%d %H:%M')

        # 安全提取数据
        summary = analysis_result.get('summary')
        summary_data = summary.get('data', {}) if isinstance(summary, dict) else {}

        watchlist = analysis_result.get('watchlist_morning', {}).get('data', [])
        strategy = analysis_result.get('strategy', {}).get('data', {})
        focus_stocks = analysis_result.get('focus_stocks', {}).get('data', [])
        position = analysis_result.get('position', {}).get('data', {})

        # 修复：兼容 wrapper（带 data 键）和裸 dict 两种格式
        us_market_raw = analysis_result.get('us_market', {})
        if isinstance(us_market_raw, dict):
            # 如果是 wrapper 结构（带 data 键），先取 data
            us_market = us_market_raw.get('data') or {}
            # 兼容裸 dict 格式（直接有 indices 键）
            if not us_market and 'indices' in us_market_raw:
                us_market = us_market_raw
        else:
            us_market = {}

        news = analysis_result.get('news', {}).get('data', [])

        markdown = f"""# A股日报 - 早报预测版
**版本**: v1.0 | **生成时间**: {gen_time} | **交易日**: {date_str}

---

## 📊 30秒速览

> **{summary_data.get('one_sentence', '数据获取失败')}**

### 🎯 核心机会
"""
        for opp in summary_data.get('core_opportunities', []):
            markdown += f"- {opp}\n"

        markdown += """
### ⚠️ 风险提示
"""
        for risk in summary_data.get('risk_warnings', []):
            if isinstance(risk, dict):
                level = risk.get('level', 'medium')
                emoji = "🔴" if level == 'high' else "🟡" if level == 'medium' else "🟢"
                markdown += f"- {emoji} {risk.get('content', '')}\n"
            else:
                markdown += f"- {str(risk)}\n"

        markdown += """
---

## 📈 自选股预测

| 股票 | 预判 | 核心逻辑 |
|------|------|----------|
"""
        if watchlist:
            for stock in watchlist:
                name = stock.get('name', '未知')
                view = stock.get('view', '震荡')
                reason = stock.get('reason', '关注市场整体表现')
                markdown += f"| {name} | {view} | {reason} |\n"
        else:
            markdown += "| 暂无数据 | - | - |\n"

        markdown += """
---

## 🚀 核心决策

### 📊 今日策略
"""
        strategy_name = strategy.get('strategy_name', '观望')
        strategy_emoji = "🚀 进攻" if strategy_name == '进攻' else "🛡️ 防守" if strategy_name == '防守' else "👁️ 观望"
        strategy_color = "🔴" if strategy_name == '进攻' else "🔵" if strategy_name == '防守' else "⚪"
        markdown += f"**{strategy_emoji}** - {strategy.get('logic', '')}\n\n"

        markdown += "### 🔍 重点关注\n| 股票 | 关注逻辑 | 介入区间 | 止损参考 |\n|------|----------|----------|----------|\n"
        if focus_stocks:
            for stock in focus_stocks:
                name = stock.get('name', '')
                code = stock.get('code', '')
                logic = stock.get('focus_logic', '')
                entry = stock.get('entry_range', '')
                stop = stock.get('stop_loss', '')
                markdown += f"| {name}({code[-2:]}) | {logic} | {entry} | {stop} |\n"
        else:
            markdown += "| 暂无 | - | - | - |\n"

        markdown += """
### 💰 仓位建议
| 建议区间 | 配置逻辑 | 风险等级 |
|----------|----------|----------|
"""
        pos_min = position.get('position_min', 0)  # 整数百分比（如30）
        pos_max = position.get('position_max', 0)  # 整数百分比（如50）
        pos_min_str = f"{pos_min:.0f}%"
        pos_max_str = f"{pos_max:.0f}%"
        logic = position.get('logic', '-')
        # 根据区间判断风险等级（使用原始百分比数值）
        if pos_max >= 70:
            risk_level = "🔴 高"
        elif pos_max >= 40:
            risk_level = "🟡 中"
        else:
            risk_level = "🟢 低"
        markdown += f"| {pos_min_str} - {pos_max_str} | {logic} | {risk_level} |\n"

        # ── A股主要指数 ──
        major_indices = analysis_result.get('major_indices', {}).get('data', {})
        markdown += """---

## 📈 A股主要指数

| 指数 | 涨跌幅 | 状态 |
|------|--------|------|
"""
        if major_indices:
            for code, label in ALL_INDICES:
                if code in major_indices:
                    idx = major_indices[code]
                    pct = idx.get('change_pct', 0)
                    
                    if pct is None or (isinstance(pct, float) and math.isnan(pct)):
                        pct_str = "暂无"
                        status = "—"
                    else:
                        pct_str = f"{pct:+.2f}%"
                        status = "📈" if pct >= 0 else "📉"
                    markdown += f"| {label} | {pct_str} | {status} |\n"
                else:
                    markdown += f"| {label} | 暂缺 | — |\n"
        else:
            for _, label in INDEX_DISPLAY_ORDER:
                markdown += f"| {label} | 暂无数据 | — |\n"

        markdown += """
---

## 🌍 昨夜今晨

### 📈 美股指数
| 指数 | 涨跌幅 | 影响解读 |
|------|--------|----------|
"""
        indices = us_market.get('indices', {})
        if indices:
            for name in ['nasdaq', 'sp500', 'dow']:
                if name in indices:
                    info = indices[name]
                    label = "纳指" if name == 'nasdaq' else "标普" if name == 'sp500' else "道指"
                    pct = info.get('change_pct', 0)
                    pct_str = f"{pct:+.2f}%"
                    impact = info.get('impact', '')
                    markdown += f"| {label} | {pct_str} | {impact} |\n"
        else:
            markdown += "| 暂无数据 | - | - |\n"

        markdown += """
### 🇨🇳 中概股/港股
| 股票 | 涨跌幅 | 传导逻辑 |
|------|--------|----------|
"""
        cdc = us_market.get('chinadotcom', {})
        if cdc:
            for name, info in cdc.items():
                pct = info.get('change_pct', 0)
                pct_str = f"{pct:+.2f}%"
                display_name = info.get('name', name)
                short_name = display_name.replace('Group Holding Limited', '').replace('Holdings Inc.', '').strip()
                impact = info.get('impact', '')
                markdown += f"| {short_name} | {pct_str} | {impact} |\n"
        else:
            markdown += "| 暂无数据 | - | - |\n"

        markdown += """
### 📉 期指表现
| 品种 | 涨跌幅 | 夜盘指引 |
|------|--------|----------|
"""
        futures_wrapper = analysis_result.get('futures', {})
        futures_container = futures_wrapper.get('data') if futures_wrapper else {}
        futures_data = futures_container.get('futures', {}) if futures_container else {}
        if futures_data:
            # A50期指
            a50 = futures_data.get('A50', {})
            if a50:
                pct = a50.get('change_pct', 0)
                
                if pct is None or (isinstance(pct, float) and math.isnan(pct)):
                    pct_str = "暂无"
                else:
                    pct_str = f"{pct:+.2f}%"
                impact = a50.get('impact', '')
                markdown += f"| A50期指 | {pct_str} | {impact} |\n"
            else:
                markdown += "| A50期指 | 暂无数据 | - |\n"

            # 沪深300期指
            csi300 = futures_data.get('CSI300', {})
            if csi300:
                pct = csi300.get('change_pct', 0)
                if pct is None or (isinstance(pct, float) and math.isnan(pct)):
                    pct_str = "暂无"
                else:
                    pct_str = f"{pct:+.2f}%"
                impact = csi300.get('impact', '')
                markdown += f"| 沪深300期指 | {pct_str} | {impact} |\n"
            else:
                markdown += "| 沪深300期指 | 暂无数据 | - |\n"
        else:
            markdown += "| A50期指 | 暂无数据 | - |\n"
            markdown += "| 沪深300期指 | 暂无数据 | - |\n"

        markdown += """
---

## 🌍 昨夜今晨 · 国际事件

> **关注可能影响 A股开盘的外部因素**

"""
        events_wrapper = analysis_result.get('international_events', {})
        if isinstance(events_wrapper, dict):
            events_data = events_wrapper.get('data', []) or []
        elif isinstance(events_wrapper, list):
            events_data = events_wrapper
        else:
            events_data = []

        if events_data:
            # 按影响等级排序：high 在前
            events_data.sort(key=lambda x: 0 if x.get('impact_level') == 'high' else 1)
            for evt in events_data[:8]:
                title = evt.get('title', '')
                category = evt.get('category', '')
                impact_level = evt.get('impact_level', 'medium')
                impact_text = evt.get('a_share_impact', '')
                sectors = evt.get('affected_sectors', [])
                source = evt.get('source', '')

                # 图标：等级
                if impact_level == 'high':
                    icon = '🔴'
                else:
                    icon = '🟡'

                # 板块标签
                sector_str = ' / '.join(sectors[:3]) if sectors else ''
                sector_tag = f" | 关联板块: {sector_str}" if sector_str else ''

                markdown += f"{icon} **{title}**（{category}）{sector_tag}\n"
                if impact_text:
                    markdown += f"   → {impact_text}\n"
                if source:
                    markdown += f"   - 来源: {source}\n"
                markdown += "\n"
        else:
            markdown += "昨夜今晨暂无重大国际事件\n\n"

        markdown += """
---

## 📰 国内要闻

### 🔥 重大影响（核心）
"""
        if news:
            # 分离重要级别
            high_news = [n for n in news if n.get('level') == 'high']
            medium_news = [n for n in news if n.get('level') == 'medium']
            low_news = [n for n in news if n.get('level') == 'low']

            # 重大影响（全部展示，含分析）
            for i, item in enumerate(high_news[:5], 1):
                title = item.get('title', '无标题')
                source = item.get('source', '')
                content = item.get('content', '')
                url = item.get('url', '')
                markdown += f"{i}. **🔴 {title}**\n"
                if url:
                    markdown += f"   - {url}\n"
                if source:
                    markdown += f"   - 来源: {source}\n"
                if content:
                    summary = content.replace('\n', ' ').strip()[:150]
                    if len(content) > 150:
                        summary += "..."
                    markdown += f"   - 核心: {summary}\n"
                markdown += "\n"

            # 中等影响（标题+裸URL）
            if medium_news:
                markdown += "### ⚡ 中等影响（关注）\n"
                for i, item in enumerate(medium_news[:10], len(high_news[:5]) + 1):
                    title = item.get('title', '无标题')
                    url = item.get('url', '')
                    markdown += f"{i}. **🟡 {title}**\n"
                    if url:
                        markdown += f"   {url}\n"
                markdown += "\n"

            # 一般影响（标题+裸URL）
            if low_news:
                markdown += "### ℹ️ 一般信息\n"
                for i, item in enumerate(low_news[:5], len(high_news[:5]) + len(medium_news[:10]) + 1):
                    title = item.get('title', '无标题')
                    url = item.get('url', '')
                    markdown += f"{i}. **🟢 {title}**\n"
                    if url:
                        markdown += f"   {url}\n"
                markdown += "\n"
        else:
            markdown += "暂无新闻数据\n"

        markdown += """
---

## 📊 数据质量报告

**信息完整性**:
- ✅ 指数数据
- ✅ 市场情绪
- ✅ 资金流向
- ✅ 美股/中概股
- ✅ 财经新闻

---
**数据来源**: 东方财富、同花顺、Wind、财联社、妙想资讯  
**风险提示**: 本报告仅供参考，据此操作风险自负

"""
        return markdown
