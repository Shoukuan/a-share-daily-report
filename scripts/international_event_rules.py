"""
国际事件规则模块
将文本规则从 data_fetcher.py 拆分出来，便于维护和测试。
"""


def classify_event_category(text):
    t = text.lower()
    if any(k in t for k in ['石油', '原油', 'oil', 'opec', '能源', '油价']):
        return "能源"
    if any(k in t for k in ['贸易', '关税', 'tariff', '制裁', 'wto']):
        return "贸易战"
    if any(k in t for k in ['美联储', 'fed', '利率', '加息', '降息', '通胀', 'cpi', 'fomc']):
        return "货币政策"
    if any(k in t for k in ['战争', '冲突', '导弹', '军事', '海峡', '制裁']):
        return "地缘政治"
    if any(k in t for k in ['科技', '芯片', '半导体', 'huawei', '华为', '制裁']):
        return "科技制裁"
    if any(k in t for k in ['黄金', 'gold', '贵金属']):
        return "大宗商品"
    if any(k in t for k in ['汇率', 'dollar', '美元', '人民币', 'rmb', 'forex']):
        return "汇率"
    return "宏观经济"


def judge_impact_level(text):
    t = text.lower()
    high_words = ['战', '危机', '暴涨', '暴跌', '制裁', '冲突', '紧急', '崩盘', '暴雷']
    if any(w in t for w in high_words):
        return "high"
    return "medium"


def generate_a_share_impact(text):
    t = text.lower()
    if any(k in t for k in ['石油', '原油', 'oil', '油价']):
        if any(w in t for w in ['涨', '升', '飙升']):
            return "油价上涨推升输入性通胀压力，不利航空/化工/物流等成本敏感行业，利好石油开采/新能源替代板块"
        return "油价下跌利好航空物流降成本，利空石油开采板块"
    if any(k in t for k in ['关税', '贸易', '制裁']):
        return "贸易摩擦升级打压出口企业，国产替代/内需受益，出口链承压"
    if any(k in t for k in ['美联储', 'fed', '加息']):
        return "美联储鹰派信号或加剧外资流出压力，人民币承压，北向资金可能减仓"
    if any(k in t for k in ['降息', '宽松']):
        return "降息利好全球风险偏好，外资或回流新兴市场，A股获支撑"
    if any(k in t for k in ['美元', 'dollar']):
        if any(w in t for w in ['涨', '强', '升']):
            return "美元走强压制新兴市场资产价格，人民币汇率承压，外资流出概率上升"
        return "美元走弱利好新兴市场资产流入"
    return "事件可能通过情绪面传导至A股市场，关注相关板块联动"


def get_affected_sectors(text):
    t = text.lower()
    sectors = []
    if any(k in t for k in ['石油', '原油', 'oil', '能源']):
        sectors += ['石油石化', '新能源', '航空', '化工', '物流']
    if any(k in t for k in ['贸易', '关税', '出口']):
        sectors += ['出口链', '外贸', '国产替代', '半导体']
    if any(k in t for k in ['半导体', '芯片', '科技', '华为']):
        sectors += ['半导体', '信创', '国产替代']
    if any(k in t for k in ['黄金', 'gold']):
        sectors += ['黄金', '贵金属']
    if any(k in t for k in ['美元', '汇率']):
        sectors += ['银行', '地产', '出口链']
    if any(k in t for k in ['美联储', '利率', '降息', '通胀']):
        sectors += ['大盘蓝筹', '券商']
    return sectors if sectors else ['大盘']


def get_a_share_impact_sectors(name, _chg):
    sectors = {"大盘", "大盘蓝筹"}
    if name == "nasdaq":
        sectors = ["科技", "半导体", "人工智能", "消费电子"]
    elif name == "sp500":
        sectors = ["大盘蓝筹", "消费", "医药"]
    elif name == "dow":
        sectors = ["金融", "工业", "能源"]
    return list(sectors)
