"""
配置校验器
"""

from errors import ConfigValidationError


def _require_dict(conf, key, errors):
    val = conf.get(key)
    if not isinstance(val, dict):
        errors.append(f"缺少或非法配置: {key} (需为 object)")
        return {}
    return val


def _require_str(conf, key, errors):
    val = conf.get(key)
    if not isinstance(val, str) or not val.strip():
        errors.append(f"缺少或非法配置: {key} (需为非空字符串)")
        return ""
    return val.strip()


def validate_config(config):
    """
    校验关键配置。
    仅检查启动期必须项，避免运行中才暴露配置问题。
    """
    if not isinstance(config, dict):
        raise ConfigValidationError("配置文件解析失败：根节点必须为 object")

    errors = []
    output = _require_dict(config, "output", errors)
    _require_str(output, "base_dir", errors)
    _require_str(output, "morning_subdir", errors)
    _require_str(output, "evening_subdir", errors)

    watchlist = _require_dict(config, "watchlist", errors)
    _require_str(watchlist, "path", errors)

    _require_dict(config, "data_sources", errors)

    publish = config.get("publish", {})
    if isinstance(publish, dict):
        pdf = publish.get("pdf", {})
        if isinstance(pdf, dict) and pdf.get("enabled"):
            _require_str(pdf, "output_dir", errors)
            _require_str(pdf, "engine", errors)

    if errors:
        raise ConfigValidationError("配置校验失败: " + "; ".join(errors))
