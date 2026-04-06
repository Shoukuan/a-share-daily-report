"""
日志工具模块
- 支持文本/JSON 两种输出（JSON 便于 ELK 收集）
- 自动注入 trace_id
- 自动脱敏敏感信息（token / api key / authorization）
"""

import json
import logging
import os
import re
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from typing import Any, Dict

from .trace import get_trace_id

# 日志根目录
LOG_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    'logs'
)

# 全局logger缓存
_loggers: Dict[str, logging.Logger] = {}


_SENSITIVE_KEY_RE = re.compile(
    r'(api[_-]?key|token|secret|authorization|password|passwd|access[_-]?key|private[_-]?key)',
    re.IGNORECASE,
)

_SENSITIVE_TEXT_PATTERNS = [
    # key=value / key: value / key=Bearer token
    (
        re.compile(
            r'(?i)(api[_-]?key|token|secret|password|authorization)\s*[:=]\s*(?:Bearer\s+)?([A-Za-z0-9\-\._~\+/=]{6,})'
        ),
        lambda m: f"{m.group(1)}=***",
    ),
    # Bearer xxxx
    (
        re.compile(r'(?i)(bearer\s+)([A-Za-z0-9\-\._~\+/=]{6,})'),
        lambda m: f"{m.group(1)}***",
    ),
]


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {'1', 'true', 'yes', 'on'}


def _sanitize_text(text: str) -> str:
    if not text:
        return text
    out = str(text)
    for pattern, repl in _SENSITIVE_TEXT_PATTERNS:
        out = pattern.sub(repl, out)
    return out


def _sanitize_obj(value: Any, key: str = '') -> Any:
    if value is None:
        return None

    if isinstance(value, dict):
        sanitized = {}
        for k, v in value.items():
            sanitized[k] = _sanitize_obj(v, key=str(k))
        return sanitized

    if isinstance(value, (list, tuple, set)):
        return [_sanitize_obj(v, key=key) for v in value]

    if key and _SENSITIVE_KEY_RE.search(key):
        return '***'

    if isinstance(value, str):
        return _sanitize_text(value)

    return value


class _TraceFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = get_trace_id() or '-'
        return True


class _TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        # 复制并脱敏 message
        msg = record.getMessage()
        msg = _sanitize_text(msg)

        event = getattr(record, 'event', None)
        fields = _sanitize_obj(getattr(record, 'fields', {}) or {})

        if event:
            kv = ' '.join([f"{k}={fields[k]}" for k in sorted(fields.keys())]) if fields else ''
            if kv:
                msg = f"event={event} {kv} | {msg}"
            else:
                msg = f"event={event} | {msg}"

        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).astimezone().strftime('%Y-%m-%d %H:%M:%S')
        return f"{ts} - {record.name} - {record.levelname} - trace_id={getattr(record, 'trace_id', '-')} - {msg}"


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            'timestamp': datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'trace_id': getattr(record, 'trace_id', '-') or '-',
            'message': _sanitize_text(record.getMessage()),
        }

        event = getattr(record, 'event', None)
        fields = _sanitize_obj(getattr(record, 'fields', {}) or {})
        if event:
            payload['event'] = event
        if fields:
            payload['fields'] = fields

        if record.exc_info:
            payload['exception'] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False)


def log_event(logger: logging.Logger, level: str, event: str, **fields: Any) -> None:
    """Emit structured event log with optional JSON output support."""
    sanitized_fields = _sanitize_obj(fields)
    message = f"event={event}"
    if sanitized_fields:
        message += ' ' + ' '.join([f"{k}={sanitized_fields[k]}" for k in sorted(sanitized_fields.keys())])

    log_fn = getattr(logger, str(level).lower(), logger.info)
    log_fn(message, extra={'event': event, 'fields': sanitized_fields})


def get_logger(
    name='a_share_daily_report',
    log_file=None,
    level=logging.INFO,
    max_bytes=10 * 1024 * 1024,
    backup_count=5,
):
    """获取或创建 logger。"""
    if name in _loggers:
        return _loggers[name]

    env_level = os.getenv('A_SHARE_LOG_LEVEL', '').strip().upper()
    if env_level:
        level = getattr(logging, env_level, level)
    elif isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)

    os.makedirs(LOG_ROOT, exist_ok=True)

    if log_file is None:
        log_file = f'{name}.log'
    log_path = os.path.join(LOG_ROOT, log_file)

    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False

    if logger.handlers:
        _loggers[name] = logger
        return logger

    formatter = _JsonFormatter() if _env_flag('A_SHARE_LOG_JSON', default=False) else _TextFormatter()
    trace_filter = _TraceFilter()

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding='utf-8',
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(level)
    file_handler.addFilter(trace_filter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(level)
    console_handler.addFilter(trace_filter)
    logger.addHandler(console_handler)

    _loggers[name] = logger
    return logger
