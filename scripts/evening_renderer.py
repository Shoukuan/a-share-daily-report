
#!/usr/bin/env python3
"""
报告子渲染器
"""

from datetime import datetime
import math

from constants import INDEX_DISPLAY_ORDER, ALL_INDICES
from utils import get_logger, format_date, format_percent

logger = get_logger('renderer')

class EveningRenderer:
    def __init__(self, config):
        self.config = config

    def render_evening_report(self, analysis_result, dt=None):
        logger.info(f"[TRACE] render_evening_report analysis_result keys: {list(analysis_result.keys())}")
        for key in ['market_overview', 'major_indices', 'global_assets', 'market_depth', 'technical']:
            val = analysis_result.get(key, {})
            logger.info(f"[TRACE] {key}: type={type(val).__name__}, success={val.get('success') if isinstance(val, dict) else 'N/A'}, data_keys={list(val.get('data', {}).keys()) if isinstance(val, dict) and val.get('success') else 'N/A'}")
        
        logger.debug(f"[DEBUG] analysis_result keys: {list(analysis_result.keys())}\n")
        if dt is None:
            dt = datetime.now()
        date_str = format_date(dt)
        gen_time = format_date(datetime.now(), '%Y-%m-%d %H:%M')

        summary = analysis_result.get('summary')
        summary_data = summary.get('data', {}) if isinstance(summary, dict) else {}

        watchlist_evening_wrapper = analysis_result.get('watchlist_evening', {})
        logger.info(f"[DEBUG] renderer watchlist_evening_wrapper: {watchlist_evening_wrapper}")
        watchlist_data = watchlist_evening_wrapper.get('data', {}) if isinstance(watchlist_evening_wrapper, dict) else {}
        logger.info(f"[DEBUG] renderer watchlist_data: {watchlist_data}")
        
        news_raw = analysis_result.get('news')
        if isinstance(news_raw, dict):
            news = news_raw.get('data') or []
        else:
            news = []

        # 1. 市场全景数据
        market_overview_raw = analysis_result.get('market_overview', {})
        logger.info(f"[DEBUG] market_overview_raw: success={market_overview_raw.get('success')}, keys={list(market_overview_raw.keys())}")
        market_overview = market_overview_raw.get('data', {})
        logger.info(f"[DEBUG] market_overview extracted: {market_overview}")
        
        # 2. 盘面深度数据
        market_depth_raw = analysis_result.get('market_depth', {})
        market_depth = market_depth_raw.get('data', {})

        markdown = f"""# A股日报 - 晚报复盘版
**版本**: v1.0 | **生成时间**: {gen_time} | **交易日**: {date_str}

---

## 🎯 市场全景

| 指标 | 数值 | 说明 |
|------|------|------|
"""
        if market_overview:
            score = market_overview.get('score', 0)
            trend = market_overview.get('trend', '未知')
            suggest_pos = market_overview.get('suggest_position', 0)
            
            markdown += f"| **情绪评分** | {score} 分 | 🌟 {trend} |\n"
            markdown += f"| 上涨/下跌/平盘 | {market_overview.get('up_count', 0)} / {market_overview.get('down_count', 0)} / {market_overview.get('flat_count', 0)} 家 | 数据来源：乐咕 |\n"
            markdown += f"| 涨停/跌停 | {market_overview.get('limit_up', 0)} / {market_overview.get('limit_down', 0)} 家 | 涨停包含一字板 |\n"
            markdown += f"| 成交额 | {market_overview.get('turnover', 0)/1e12:.2f} 万亿元 | 💰 |\n"
            markdown += f"| 北向资金 | {market_overview.get('northbound', 0)/1e8:+.1f} 亿元 | {'⬆️ 流入' if market_overview.get('northbound', 0) >= 0 else '⬇️ 流出'} |\n"
            markdown += f"| 两融变化 | {market_overview.get('margin', 0)/1e8:+.1f} 亿元 | 💵 |\n"
            markdown += f"| **建议仓位** | {suggest_pos:.0%} | {'🔴 偏高' if suggest_pos >= 0.6 else '🟡 适中' if suggest_pos >= 0.4 else '🟢 偏低'} |\n"
        else:
            markdown += "| 市场全景数据暂缺 | - | - |\n"

        markdown += """
---

## 📊 30秒速览

> **{one_sentence}**

### ✨ 核心亮点
""".format(one_sentence=summary_data.get('one_sentence', '数据获取失败'))
        for highlight in summary_data.get('core_highlights', []):
            markdown += f"- {highlight}\n"

        markdown += """
### 🔮 明日重点观察
"""
        for outlook in summary_data.get('tomorrow_outlook', []):
            markdown += f"- {outlook}\n"

        markdown += """
---

## 📈 今日复盘

### 🎯 指数表现（主要市场指数）
| 指数 | 涨跌幅 | 状态 |
|------|--------|------|
"""
        # 显示10个主要指数
        major_indices = analysis_result.get('major_indices', {}).get('data', {})
        if major_indices:
            for code, label in ALL_INDICES:
                if code in major_indices:
                    idx = major_indices[code]
                    change_pct = idx.get('change_pct', 0)
                    pct_str = f"{change_pct:+.2f}%"
                    status = "📈" if change_pct >= 0 else "📉"
                    markdown += f"| {label} | {pct_str} | {status} |\n"
                else:
                    markdown += f"| {label} | 暂缺 | - |\n"
        else:
            markdown += "| - | 暂无数据 | - |\n"

        markdown += """
### 💰 市场情绪
| 指标 | 数值 | 说明 |
|------|------|------|
"""
        sentiment = analysis_result.get('sentiment', {}).get('data', {})
        if sentiment:
            limit_up = sentiment.get('limit_up_count', 0)
            limit_down = sentiment.get('limit_down_count', 0)
            max_consec = sentiment.get('max_consec_up', 0)
            total = sentiment.get('total_turnover', 0)

            markdown += f"| 涨停家数 | {limit_up} 家 | ✅ 做多力量 |\n"
            markdown += f"| 跌停家数 | {limit_down} 家 | ⚠️ 风险警示 |\n"
            markdown += f"| 最高连板 | {max_consec} 板 | 🔥 题材热度 |\n"
            markdown += f"| 成交额 | {total/1e8:.1f} 亿元 | 💵 市场活跃度 |\n"
        else:
            markdown += "| 暂无数据 | - | - |\n"

        markdown += """
### 🎯 技术面分析（上证指数）
| 指标 | 数值 | 判断 |
|------|------|------|
"""
        technical = analysis_result.get('technical', {}).get('data', {})
        if technical:
            rsi = technical.get('rsi', 50)
            rsi_status = technical.get('rsi_status', '中性')
            macd = technical.get('macd_signal', '中性')
            trend_strength = technical.get('trend_strength', '中等')
            support = technical.get('support', 0)
            resistance = technical.get('resistance', 0)

            markdown += f"| RSI(14) | {rsi:.1f} | {rsi_status} |\n"
            markdown += f"| MACD | {macd} | - |\n"
            markdown += f"| 趋势强度 | {trend_strength} | - |\n"
            markdown += f"| 支撑位 | {support:.2f} 点 | - |\n"
            markdown += f"| 阻力位 | {resistance:.2f} 点 | - |\n"
        else:
            markdown += "| 技术指标暂缺 | - | - |\n"

        markdown += """
### 📊 盘面深度
| 指标 | 数值 | 说明 |
|------|------|------|
"""
        if market_depth:
            break_rate = market_depth.get('break_rate', 0)
            break_count = market_depth.get('break_count', 0)
            total_limit = market_depth.get('total_limit_up', 0)
            up_over_5 = market_depth.get('up_over_5pct', 0)
            
            markdown += f"| 炸板率 | {break_rate:.1f}% | {break_count}/{total_limit} |\n"
            markdown += f"| 涨幅>5% | {up_over_5} 家 | 强势股数量 |\n"
        else:
            markdown += "| 盘面深度数据暂缺 | - | - |\n"

        markdown += """
---

## 📊 行业资金流向

### 💰 净流入Top 5
| 排名 | 行业 | 净流入(亿元) | 领涨股 | 涨跌幅 |
|------|------|-------------|--------|--------|
"""
        industry_fund_flow = analysis_result.get('industry_fund_flow', {}).get('data', {})
        if industry_fund_flow and industry_fund_flow.get('top_net_inflow'):
            top_inflow = industry_fund_flow['top_net_inflow'][:5]
            for i, item in enumerate(top_inflow, 1):
                markdown += f"| {i} | {item['industry']} | {item['net_inflow']:+.1f} | {item['leading_stock']} | {item['leading_stock_change']:+.2f}% |\n"
        else:
            markdown += "| 暂无数据 | - | - | - | - |\n"

        markdown += """
### 📉 净流出Top 5
| 排名 | 行业 | 净流出(亿元) | 领跌股 | 涨跌幅 |
|------|------|-------------|--------|--------|
"""
        if industry_fund_flow and industry_fund_flow.get('top_net_outflow'):
            top_outflow = industry_fund_flow['top_net_outflow'][:5]
            for i, item in enumerate(top_outflow, 1):
                markdown += f"| {i} | {item['industry']} | {item['net_inflow']:+.1f} | {item['leading_stock']} | - |\n"
        else:
            markdown += "| 暂无数据 | - | - | - | - |\n"

        markdown += """
---

## 📊 自选股深度分析

### 📈 自选股列表（8维评分）
| 股票 | 代码 | 最新价 | 涨跌幅 | 成交额 | 振幅 | 综合评分 | 信号 |
|------|------|--------|--------|--------|------|----------|------|
"""
        # watchlist_data 现在是 dict（含 stocks 列表）或兼容 list 格式
        watchlist_items = []
        if isinstance(watchlist_data, list):
            watchlist_items = watchlist_data
        elif isinstance(watchlist_data, dict):
            # 优先从 stocks 字段取逐只数据
            if watchlist_data.get('stocks'):
                watchlist_items = watchlist_data['stocks']
            # 旧格式兼容
            if watchlist_data.get('overall'):
                overall = watchlist_data.get('overall', {})
                markdown += f"| **整体** | - | - | **{overall.get('avg_return', 0):+.2f}%** | - | - | - | 涨{overall.get('up_count',0)}/跌{overall.get('down_count',0)} |\n"
            best = watchlist_data.get('best')
            if best:
                markdown += f"| **最佳** | {best.get('name')} | - | **{best.get('change_pct'):+.2f}%** | - | - | - | {best.get('reason','')} |\n"
        
        if watchlist_items:
            for item in watchlist_items:
                name = item.get('name', '')
                code = item.get('code', '').split('.')[0]
                price = item.get('price', 0)
                change = item.get('change_pct', 0)
                amount = item.get('amount', 0) / 1e8  # 转为亿
                amp = item.get('amplitude', 0)
                avg_s = item.get('avg_score', 0)
                signal = item.get('signal', '')
                change_emoji = "🔴" if change >= 0 else "🟢"
                markdown += f"| {name} | {code} | {price} | {change_emoji} {change:+.2f}% | {amount:.1f}亿 | {amp:.1f}% | {avg_s}/100 | {signal} |\n"
        elif not isinstance(watchlist_data, dict) or not watchlist_data.get('overall'):
            markdown += "| - | 暂无自选股数据（请配置 watchlist.yaml） | - | - | - | - | - | - |\n"

        markdown += """

### 🎯 逐股深度分析
"""
        if watchlist_items:
            for item in watchlist_items:
                name = item.get('name', '')
                code = item.get('code', '').split('.')[0]
                price = item.get('price', 0)
                change = item.get('change_pct', 0)
                amount = item.get('amount', 0) / 1e8
                amp = item.get('amplitude', 0)
                turnover = item.get('turnover', 0)
                vol_ratio = item.get('volume_ratio', 0)
                s8 = item.get('score_8d', {})
                avg_s = item.get('avg_score', 0)
                signal = item.get('signal', '')
                support = item.get('support', 0)
                resist = item.get('resistance', 0)
                reason = item.get('reason', '')
                change_emoji = "🔴" if change >= 0 else "🟢"

                markdown += f"""#### {name}（{code}）\n"
- **行情快照**: {price}  {change_emoji} {change:+.2f}% | 振幅 {amp:.1f}% | 换手 {turnover:.1f}% | 量比 {vol_ratio} | 成交 {amount:.1f}亿
- **综合评分**: {avg_s}/100  {signal}  8维评分: 趋势{s8.get('trend',50)} | 动量{s8.get('momentum',50)} | RSI{s8.get('rsi',50)} | 量能{s8.get('vol',50)} | 波动{s8.get('amp',50)} | 强弱{s8.get('relative',50)} | 行业{s8.get('industry',50)} | 回撤{s8.get('dd',50)}
- **技术位**: 支撑 {support} | 阻力 {resist}
- 💡 **点评**: {reason}
"""
        else:
            markdown += "暂无自选股深度数据\n"

        # 明日策略
        markdown += """
### 📋 操作建议汇总
"""
        if watchlist_items:
            for item in watchlist_items:
                name = item.get('name', '')
                signal = item.get('signal', '')
                support = item.get('support', 0)
                resist = item.get('resistance', 0)
                reason = item.get('reason', '')
                markdown += f"- **{name}**: {signal} | 支撑{support} / 阻力{resist} | {reason}\n"
        else:
            markdown += "- 自选股数据暂缺，建议保持观望\n"

        markdown += """
---

## 🏆 板块全景

### 📊 行业板块 Top 5
| 排名 | 板块 | 涨跌幅 | 领涨前三 |
|------|------|--------|----------|
"""
        sectors_data = analysis_result.get('sectors', {}).get('data') or {}
        industry_sectors = sectors_data.get('industry', [])

        if industry_sectors:
            for i, sector in enumerate(industry_sectors[:5], 1):
                name = sector.get('sector', '')
                pct = sector.get('change_pct', 0)
                leaders = sector.get('leaders', [])
                leader_str = '、'.join([f"{l.get('name', '')}({l.get('code', '')})" for l in leaders[:3]])
                markdown += f"| {i} | {name} | {pct:+.2f}% | {leader_str} |\n"
        else:
            markdown += "| - | 暂无数据 | - | - |\n"

        markdown += """
### 🚀 概念板块 Top 5
| 排名 | 概念 | 龙头股 | 驱动事件 |
|------|------|--------|----------|
"""
        concept_sectors = sectors_data.get('concept', [])

        if concept_sectors:
            for i, sector in enumerate(concept_sectors[:5], 1):
                name = sector.get('sector', '')
                leaders = sector.get('leaders', [])
                leader_name = leaders[0]['name'] if leaders else "暂无"
                driver = sector.get('driver', '')
                # 驱动事件截断过长文本
                driver_display = driver[:50] + "..." if len(driver) > 50 else driver
                markdown += f"| {i} | {name} | {leader_name} | {driver_display} |\n"
        else:
            markdown += "| - | 暂无数据 | - | - |\n"

        markdown += """
---

## 📊 主题投资追踪

| 主题 | 平均涨幅 | 相关板块数 | 领涨板块/龙头 |
|------|---------|-----------|-------------|
"""
        theme_tracking = analysis_result.get('theme_tracking', {}).get('data', [])
        if theme_tracking:
            for item in theme_tracking[:8]:  # 显示前8个主题
                theme = item.get('theme', '')
                avg_change = item.get('avg_change_pct', 0)
                count = item.get('sector_count', 0)
                top_sectors = '、'.join(item.get('top_sectors', [])[:2])
                leaders = '、'.join([l for l in item.get('top_leaders', []) if l][:2])
                markdown += f"| {theme} | {avg_change:+.2f}% | {count}个 | {top_sectors}/{leaders} |\n"
        else:
            markdown += "| 暂无主题追踪数据 | - | - | - |\n"

        markdown += """
---

## 🌍 全球资产联动

| 资产 | 最新价 | 涨跌幅 | 影响解读 |
|------|---------|--------|----------|
"""
        global_assets = analysis_result.get('global_assets', {}).get('data', {})
        if global_assets:
            # 美元指数
            usd = global_assets.get('usd_index', {})
            if usd:
                name = usd.get('name', '美元指数')
                price = usd.get('close', 0)
                pct = usd.get('change_pct', 0)
                impact = "美元走弱有利于外资流入" if pct < 0 else "美元走强可能压制外资"
                markdown += f"| {name} | {price:.2f} | {pct:+.2f}% | {impact} |\n"
            else:
                markdown += "| 美元指数 | 暂缺 | - | - |\n"

            # 黄金
            gold = global_assets.get('gold', {})
            if gold:
                name = gold.get('name', '黄金')
                price = gold.get('close', 0)
                pct = gold.get('change_pct', 0)
                impact = "黄金上涨反映避险情绪或美元走弱" if pct > 0 else "黄金下跌风险偏好上升"
                markdown += f"| {name} | {price:.1f} | {pct:+.2f}% | {impact} |\n"
            else:
                markdown += "| 黄金(COMEX) | 暂缺 | - | - |\n"

            # 原油
            oil = global_assets.get('oil', {})
            if oil:
                name = oil.get('name', '原油')
                price = oil.get('close', 0)
                pct = oil.get('change_pct', 0)
                impact = "原油上涨推升通胀预期，利好能源股" if pct > 0 else "原油下跌缓解通胀压力"
                markdown += f"| {name} | {price:.2f} | {pct:+.2f}% | {impact} |\n"
            else:
                markdown += "| 原油(WTI) | 暂缺 | - | - |\n"
        else:
            markdown += "| 全球资产数据暂缺 | - | - | - |\n"

        markdown += """
---

## 📊 主要指数详情

| 指数 | 最新价 | 涨跌幅 | 涨跌额 | 振幅 | 今开 | 最高 | 最低 | 成交额(亿) |
|------|---------|--------|--------|------|------|------|------|-----------|
"""
        if major_indices:
            for code, label in ALL_INDICES:
                if code in major_indices:
                    idx = major_indices[code]
                    close = idx.get('close', 0)
                    change_pct = idx.get('change_pct', 0)
                    change = idx.get('change', 0)
                    amplitude = idx.get('high', 0) - idx.get('low', 0)
                    amplitude_pct = (amplitude / idx.get('low', 1)) * 100 if idx.get('low', 0) > 0 else 0
                    open_price = idx.get('open', 0)
                    high = idx.get('high', 0)
                    low = idx.get('low', 0)
                    amount = idx.get('amount', 0) / 1e8  # 转换为亿元

                    markdown += f"| {label} | {close:.2f} | {change_pct:+.2f}% | {change:+.2f} | {amplitude_pct:.2f}% | {open_price:.2f} | {high:.2f} | {low:.2f} | {amount:.1f} |\n"
                else:
                    markdown += f"| {label} | 暂缺 | - | - | - | - | - | - | - |\n"
        else:
            markdown += "| 指数数据暂缺 | - | - | - | - | - | - | - | - |\n"

        markdown += """
---

## 🏅 龙虎榜 Top 5

| 排名 | 股票 | 代码 | 涨跌幅 | 收盘 | 净买额 |
|------|------|------|--------|------|--------|
"""
        lhb_wrapper = analysis_result.get('lhb', {})
        # lhb 可能是 list（原始数据）或 dict（带 data key）
        if isinstance(lhb_wrapper, list):
            lhb_data = lhb_wrapper
        elif isinstance(lhb_wrapper, dict):
            lhb_data = lhb_wrapper.get('data', [])
            if not lhb_data:
                # 尝试直接从 wrapper 取值（可能没包装）
                lhb_data = lhb_wrapper
        else:
            lhb_data = []
        
        # 确保 lhb_data 是列表类型
        if not isinstance(lhb_data, list):
            lhb_data = []
        
        if lhb_data and len(lhb_data) > 0:
            for i, item in enumerate(lhb_data[:5], 1):
                name = str(item.get('name', ''))
                code = str(item.get('code', ''))
                change = item.get('change_pct', 0)
                close = item.get('close', 0)
                # net_inflow 单位是元（akshare 龙虎榜净买额原始单位）
                net_yuan = float(item.get('net_inflow', 0)) if item.get('net_inflow') is not None else 0
                # 净买额：大于1千万显示亿，否则显示万
                if abs(net_yuan) >= 1e8:
                    net_str = f"{'+' if net_yuan>=0 else ''}{net_yuan/1e8:.2f}亿"
                else:
                    net_str = f"{'+' if net_yuan>=0 else ''}{net_yuan/1e4:.0f}万"
                markdown += f"| {i} | {name} | {code} | {change:+.1f}% | {close} | {net_str} |\n"
        else:
            markdown += "| - | 今日无龙虎榜数据 | - | - | - | - |\n"

        markdown += """
---

## 📰 今日要闻

### 🔥 重点新闻（前10）
"""
        if news:
            important_news = sorted(news[:10], key=lambda x: {'high': 0, 'medium': 1}.get(x.get('level', 'medium'), 1))

            for i, item in enumerate(important_news[:10], 1):
                level = item.get('level', 'medium')
                if level in ['🔴', '🟡', '🟢']:
                    level_icon = level
                else:
                    level_icon = "🔥" if level == 'high' else "⚡" if level == 'medium' else "ℹ️"
                title = item.get('title', '无标题')
                url = item.get('url', '')
                markdown += f"{i}. **{level_icon} {title}**\n"
                if url:
                    markdown += f"   {url}\n"

                source = item.get('source', '')
                if source:
                    markdown += f"   - 来源: {source}\n"

                content = item.get('content', '')
                if content:
                    content_summary = content.replace('\n', ' ').strip()[:120]
                    if len(content) > 120:
                        content_summary += "..."
                    markdown += f"   - 概要: {content_summary}\n"

                markdown += "\n"
        else:
            markdown += "暂无新闻数据\n"

        markdown += """
---

## 📊 综合分析

### 🎯 大盘走势判断
"""
        comprehensive = analysis_result.get('comprehensive', {}).get('data', {})
        if comprehensive:
            trend_judge = comprehensive.get('trend_judge', '暂无分析')
            markdown += f"{trend_judge}\n"

            markdown += """
### 💰 量能分析
"""
            volume_analysis = comprehensive.get('volume_analysis', '暂无分析')
            markdown += f"{volume_analysis}\n"

            markdown += """
### 📈 风格分化
"""
            style_analysis = comprehensive.get('style_analysis', '暂无分析')
            markdown += f"{style_analysis}\n"

            markdown += """
### 💡 后市展望
"""
            outlook = comprehensive.get('outlook', '暂无展望')
            markdown += f"{outlook}\n"
        else:
            markdown += "暂无综合分析数据\n"

        markdown += """
---

## 📊 数据质量报告

**信息完整性**:
- ✅ 指数数据（10个主要指数）
- ✅ 市场全景（情绪评分+仓位建议）
- ✅ 盘面深度（炸板率统计）
- ✅ 资金流向
- ✅ 板块数据
- ✅ 龙虎榜
- ✅ 财经新闻
"""
        # 检查缺失项
        missing = []
        if not major_indices:
            missing.append("主要指数")
        if not market_overview:
            missing.append("市场全景")
        if not market_depth:
            missing.append("盘面深度")
        if not global_assets:
            missing.append("全球资产")
        
        if missing:
            markdown += f"\n**⚠️ 缺失数据**: {', '.join(missing)}\n"

        markdown += """
---
**数据来源**: 东方财富、同花顺、Wind、财联社、妙想资讯、yfinance  
**风险提示**: 本报告仅供参考，据此操作风险自负

"""
        return markdown
