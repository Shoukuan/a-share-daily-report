"""
trace 上下文传播工具
"""

import os
import uuid
from contextvars import ContextVar


_TRACE_ID: ContextVar[str] = ContextVar('a_share_trace_id', default='')


def get_trace_id() -> str:
    return _TRACE_ID.get() or ''


def set_trace_id(trace_id: str) -> str:
    trace_id = (trace_id or '').strip()
    if not trace_id:
        trace_id = uuid.uuid4().hex
    _TRACE_ID.set(trace_id)
    return trace_id


def ensure_trace_id(trace_id: str = None) -> str:
    if trace_id:
        return set_trace_id(trace_id)

    existing = get_trace_id()
    if existing:
        return existing

    env_trace = os.getenv('A_SHARE_TRACE_ID', '').strip()
    if env_trace:
        return set_trace_id(env_trace)

    return set_trace_id(uuid.uuid4().hex)
