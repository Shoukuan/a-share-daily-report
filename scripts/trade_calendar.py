"""
交易日历模块
支持中国A股交易日判断（含法定节假日）
"""

from datetime import datetime, date, timedelta

from utils.helpers import parse_date, cn_today

# 中国A股法定节假日（手动维护，每年更新）
# 格式: 'YYYY-MM-DD'
HOLIDAYS = {
    # 2025
    '2025-01-01',  # 元旦
    '2025-01-28', '2025-01-29', '2025-01-30', '2025-01-31',
    '2025-02-03', '2025-02-04',  # 春节
    '2025-04-04', '2025-04-05', '2025-04-06',  # 清明
    '2025-05-01', '2025-05-02', '2025-05-03', '2025-05-04', '2025-05-05',  # 劳动节
    '2025-05-31', '2025-06-01', '2025-06-02',  # 端午
    '2025-10-01', '2025-10-02', '2025-10-03', '2025-10-04',
    '2025-10-05', '2025-10-06', '2025-10-07', '2025-10-08',  # 国庆+中秋
    # 2026
    '2026-01-01', '2026-01-02', '2026-01-03',  # 元旦
    '2026-02-16', '2026-02-17', '2026-02-18', '2026-02-19',
    '2026-02-20', '2026-02-21', '2026-02-22',  # 春节
    '2026-04-05', '2026-04-06', '2026-04-07',  # 清明
    '2026-05-01', '2026-05-02', '2026-05-03', '2026-05-04', '2026-05-05',  # 劳动节
    '2026-06-19', '2026-06-20', '2026-06-21',  # 端午
    '2026-09-25', '2026-09-26', '2026-09-27',  # 中秋节
    '2026-10-01', '2026-10-02', '2026-10-03',
    '2026-10-04', '2026-10-05', '2026-10-06', '2026-10-07',  # 国庆
}

# 调休补班日（周末但上班，A股不开市，但用于工作日判断）
# 注意：A股周末一律不开市，调休补班日也不开市
# 所以只需在 HOLIDAYS 中排除即可，无需额外处理


def _is_holiday(dt: date) -> bool:
    """判断是否为法定节假日"""
    return dt.isoformat() in HOLIDAYS


def is_trade_day(dt=None):
    """判断是否为交易日（非周末 + 非法定节假日）"""
    if dt is None:
        dt = cn_today()
    elif isinstance(dt, str):
        dt = parse_date(dt)
        if dt is None:
            return False
    if isinstance(dt, datetime):
        dt = dt.date()
    return dt.weekday() < 5 and not _is_holiday(dt)


def prev_trade_day(dt=None):
    """获取前一个交易日"""
    if dt is None:
        dt = cn_today()
    elif isinstance(dt, str):
        dt = parse_date(dt)
        if dt is None:
            dt = cn_today()
    if isinstance(dt, datetime):
        dt = dt.date()
    check_date = dt - timedelta(days=1)
    while not is_trade_day(check_date):
        check_date -= timedelta(days=1)
    return check_date


def next_trade_day(dt=None):
    """获取下一个交易日"""
    if dt is None:
        dt = cn_today()
    elif isinstance(dt, str):
        dt = parse_date(dt)
        if dt is None:
            dt = cn_today()
    if isinstance(dt, datetime):
        dt = dt.date()
    check_date = dt + timedelta(days=1)
    while not is_trade_day(check_date):
        check_date += timedelta(days=1)
    return check_date


def get_effective_date(dt=None, mode='morning'):
    """获取有效报告日期"""
    if dt is None:
        dt = cn_today()
    elif isinstance(dt, str):
        dt = parse_date(dt)
        if dt is None:
            dt = cn_today()
    if isinstance(dt, datetime):
        dt = dt.date()
    if not is_trade_day(dt):
        return prev_trade_day(dt)
    return dt
