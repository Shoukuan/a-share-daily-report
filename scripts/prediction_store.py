"""
早报预测快照存储
早报生成时保存自选股预测和仓位建议，晚报读取后做预测 vs 实际对比。
文件格式：reports/predictions/YYYYMMDD.json（每日一文件）
"""

import json
import os
from typing import Optional

from utils import get_logger, get_project_root, format_date

logger = get_logger('prediction_store')

_PREDICTIONS_SUBDIR = os.path.join('reports', 'predictions')


def _pred_path(dt) -> str:
    date_str = format_date(dt, '%Y%m%d')
    base = os.path.join(get_project_root(), _PREDICTIONS_SUBDIR)
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, f'{date_str}.json')


def save_morning_prediction(dt, watchlist_morning: list, position: dict) -> None:
    """
    早报生成后调用：把自选股预测和仓位建议持久化。

    Args:
        dt: 交易日
        watchlist_morning: analyzer.analyze_watchlist_morning 返回的 data 列表
            每项: {code, name, view, reason, change_pct, price}
        position: analyzer.suggest_position 返回的 data dict
            包含 position_min, position_max, logic 等
    """
    try:
        payload = {
            'date': format_date(dt, '%Y-%m-%d'),
            'watchlist': watchlist_morning,
            'position': position,
        }
        path = _pred_path(dt)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        logger.info(f'早报预测快照已保存: {path}')
    except Exception as e:
        logger.warning(f'保存早报预测快照失败（不影响主流程）: {e}')


def load_morning_prediction(dt) -> Optional[dict]:
    """
    晚报生成时调用：读取同日早报预测快照。

    Returns:
        {'date': str, 'watchlist': list, 'position': dict} 或 None（无快照时）
    """
    try:
        path = _pred_path(dt)
        if not os.path.exists(path):
            logger.info(f'无当日早报预测快照: {path}')
            return None
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f'读取早报预测快照失败: {e}')
        return None


def compare_predictions(morning_pred: dict, watchlist_actual: list) -> dict:
    """
    对比早报预测与晚报实际表现，生成复盘结果。

    Args:
        morning_pred: load_morning_prediction 返回的预测快照
        watchlist_actual: 晚报自选股实际表现列表
            每项需含 code/name/change_pct

    Returns:
        {
          'summary_line': str,        # 一句话命中率总结
          'hit_rate': float,          # 预测命中率 0-1
          'details': list,            # 每只股票的预测 vs 实际
          'position_review': str,     # 仓位建议回顾
        }
    """
    if not morning_pred or not watchlist_actual:
        return {
            'summary_line': '无早报预测快照，无法复盘',
            'hit_rate': None,
            'details': [],
            'position_review': '',
        }

    pred_map = {
        item.get('code', '').split('.')[0]: item
        for item in morning_pred.get('watchlist', [])
    }
    actual_map = {
        item.get('code', '').split('.')[0]: item
        for item in watchlist_actual
    }

    details = []
    hit_count = 0
    total = 0

    for code, pred in pred_map.items():
        actual = actual_map.get(code)
        if actual is None:
            continue
        total += 1
        pred_view = pred.get('view', '')
        actual_pct = actual.get('change_pct', 0)

        # 命中判断：看涨/偏多/震荡偏多 → 实际上涨；看跌/偏空 → 实际下跌；震荡 → 涨跌幅小
        hit = False
        if pred_view in ('看涨', '偏多', '震荡偏多') and actual_pct > 0:
            hit = True
        elif pred_view in ('看跌', '偏空') and actual_pct < 0:
            hit = True
        elif pred_view == '震荡' and abs(actual_pct) <= 2:
            hit = True

        if hit:
            hit_count += 1

        details.append({
            'code': pred.get('code', code),
            'name': pred.get('name', ''),
            'pred_view': pred_view,
            'actual_pct': actual_pct,
            'hit': hit,
            'miss_reason': _miss_reason(pred_view, actual_pct) if not hit else '',
        })

    hit_rate = hit_count / total if total > 0 else None

    if hit_rate is None:
        summary_line = '自选股实际数据不足，无法计算命中率'
    elif hit_rate >= 0.8:
        summary_line = f'早报预测命中率 {hit_rate:.0%}（{hit_count}/{total}），预测质量优秀'
    elif hit_rate >= 0.6:
        summary_line = f'早报预测命中率 {hit_rate:.0%}（{hit_count}/{total}），预测质量良好'
    elif hit_rate >= 0.4:
        summary_line = f'早报预测命中率 {hit_rate:.0%}（{hit_count}/{total}），预测质量一般'
    else:
        summary_line = f'早报预测命中率 {hit_rate:.0%}（{hit_count}/{total}），市场与预期偏差较大'

    # 仓位回顾
    position = morning_pred.get('position', {})
    pos_min = position.get('position_min', '-')
    pos_max = position.get('position_max', '-')
    position_review = f"早报建议仓位 {pos_min}%-{pos_max}%"

    return {
        'summary_line': summary_line,
        'hit_rate': hit_rate,
        'details': details,
        'position_review': position_review,
    }


def _miss_reason(pred_view: str, actual_pct: float) -> str:
    """生成预测失误原因描述"""
    if pred_view in ('看涨', '偏多', '震荡偏多') and actual_pct <= 0:
        return f'预测偏多但实际下跌{abs(actual_pct):.1f}%'
    elif pred_view in ('看跌', '偏空') and actual_pct >= 0:
        return f'预测偏空但实际上涨{actual_pct:.1f}%'
    elif pred_view == '震荡' and abs(actual_pct) > 2:
        return f'预测震荡但实际波动{actual_pct:+.1f}%超出区间'
    return f'实际{actual_pct:+.1f}%'
