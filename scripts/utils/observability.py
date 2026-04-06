"""
性能监控与指标上报
支持：Prometheus（可选）/ StatsD（可选）
"""

import os
import socket
import time
from functools import wraps

from .logger import get_logger, log_event
from .trace import get_trace_id

logger = get_logger('observability')


class _MetricsEmitter:
    def __init__(self):
        self._statsd_host = os.getenv('STATSD_HOST', '').strip()
        self._statsd_port = int(os.getenv('STATSD_PORT', '8125'))
        self._statsd_prefix = os.getenv('STATSD_PREFIX', 'a_share_report').strip() or 'a_share_report'
        self._statsd_socket = None

        self._prom_histogram = None
        try:
            from prometheus_client import Histogram
            self._prom_histogram = Histogram(
                'a_share_stage_duration_seconds',
                'A-share report stage duration in seconds',
                ['stage', 'status'],
            )
        except Exception:
            self._prom_histogram = None

    def emit_duration(self, stage: str, seconds: float, status: str = 'ok'):
        if seconds is None:
            return

        # 结构化日志（用于 ELK）
        log_event(
            logger,
            'info',
            'stage_duration',
            stage=stage,
            duration_ms=f"{seconds * 1000:.2f}",
            status=status,
            trace_id=get_trace_id(),
        )

        # StatsD
        self._emit_statsd(stage=stage, seconds=seconds)

        # Prometheus
        if self._prom_histogram is not None:
            try:
                self._prom_histogram.labels(stage=stage, status=status).observe(seconds)
            except Exception:
                pass

    def _emit_statsd(self, stage: str, seconds: float):
        if not self._statsd_host:
            return

        metric_name = stage.replace('.', '_').replace('/', '_').replace(' ', '_')
        payload = f"{self._statsd_prefix}.{metric_name}:{seconds * 1000:.2f}|ms"
        try:
            if self._statsd_socket is None:
                self._statsd_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._statsd_socket.sendto(payload.encode('utf-8'), (self._statsd_host, self._statsd_port))
        except Exception:
            # 指标上报不应影响主流程
            pass


_EMITTER = _MetricsEmitter()


def record_stage_duration(stage: str, seconds: float, status: str = 'ok'):
    _EMITTER.emit_duration(stage=stage, seconds=seconds, status=status)


def monitor_stage(stage: str):
    """函数装饰器：记录耗时到日志 + Prometheus/StatsD。"""

    def _decorator(func):
        @wraps(func)
        def _wrapped(*args, **kwargs):
            start = time.perf_counter()
            status = 'ok'
            try:
                return func(*args, **kwargs)
            except Exception:
                status = 'error'
                raise
            finally:
                elapsed = time.perf_counter() - start
                record_stage_duration(stage=stage, seconds=elapsed, status=status)

        return _wrapped

    return _decorator


class stage_timer:
    """上下文管理器：用于块级耗时统计。"""

    def __init__(self, stage: str):
        self.stage = stage
        self.start = 0.0
        self.status = 'ok'

    def __enter__(self):
        self.start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is not None:
            self.status = 'error'
        elapsed = time.perf_counter() - self.start
        record_stage_duration(stage=self.stage, seconds=elapsed, status=self.status)
        return False
