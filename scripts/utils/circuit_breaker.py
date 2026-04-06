"""
熔断器模块（Circuit Breaker）
防止对故障数据源的无效重试，保护系统资源
"""

import time
import threading
from functools import wraps
from typing import Callable, Any, Dict, Tuple
from utils import get_logger

logger = get_logger('circuit_breaker')


class CircuitBreaker:
    """
    熔断器状态机：
    CLOSED → (failure_count >= threshold) → OPEN → (timeout) → HALF_OPEN → (success) → CLOSED
    """
    CLOSED = 'CLOSED'
    OPEN = 'OPEN'
    HALF_OPEN = 'HALF_OPEN'

    def __init__(self, name: str, failure_threshold: int = 3, recovery_timeout: int = 300):
        """
        Args:
            name: 熔断器名称（用于日志）
            failure_threshold: 触发熔断的连续失败次数
            recovery_timeout: 熔断后进入 HALF_OPEN 的等待时间（秒）
        """
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.state = self.CLOSED
        self.failure_count = 0
        self.last_failure_time = 0
        self._lock = threading.Lock()

    def __call__(self, func):
        """装饰器：保护函数调用"""
        @wraps(func)
        def wrapper(*args, **kwargs):
            return self.call(func, *args, **kwargs)
        return wrapper

    def call(self, func: Callable, *args, **kwargs) -> Any:
        """执行受保护的方法调用"""
        with self._lock:
            if self.state == self.OPEN:
                if time.time() - self.last_failure_time >= self.recovery_timeout:
                    self.state = self.HALF_OPEN
                    logger.info(f"Circuit breaker '{self.name}' 进入 HALF_OPEN 状态，尝试恢复")
                else:
                    raise RuntimeError(f"Circuit breaker '{self.name}' is OPEN until {self.last_failure_time + self.recovery_timeout}")

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise e

    def _on_success(self):
        """成功调用后的处理"""
        with self._lock:
            if self.state == self.HALF_OPEN:
                self.state = self.CLOSED
                logger.info(f"Circuit breaker '{self.name}' 恢复 CLOSED 状态")
            self.failure_count = 0

    def _on_failure(self):
        """失败后的处理"""
        with self._lock:
            self.failure_count += 1
            self.last_failure_time = time.time()
            if self.failure_count >= self.failure_threshold and self.state != self.OPEN:
                self.state = self.OPEN
                logger.warning(f"Circuit breaker '{self.name}' 触发熔断，进入 OPEN 状态（失败{self.failure_count}次）")

    def reset(self):
        """手动重置熔断器"""
        with self._lock:
            self.state = self.CLOSED
            self.failure_count = 0
            self.last_failure_time = 0

    def get_status(self) -> Dict[str, Any]:
        """获取熔断器状态"""
        with self._lock:
            return {
                'name': self.name,
                'state': self.state,
                'failure_count': self.failure_count,
                'last_failure_time': self.last_failure_time,
                'time_to_recovery': max(0, self.last_failure_time + self.recovery_timeout - time.time()) if self.state == self.OPEN else 0
            }


class CircuitBreakerManager:
    """熔断器管理器：管理多个熔断器实例"""
    _breakers: Dict[str, CircuitBreaker] = {}
    _global_lock = threading.Lock()

    @classmethod
    def get_breaker(cls, name: str, **kwargs) -> CircuitBreaker:
        """获取或创建熔断器实例"""
        with cls._global_lock:
            if name not in cls._breakers:
                cls._breakers[name] = CircuitBreaker(name, **kwargs)
            return cls._breakers[name]

    @classmethod
    def reset_all(cls):
        """重置所有熔断器"""
        with cls._global_lock:
            for breaker in cls._breakers.values():
                breaker.reset()

    @classmethod
    def get_all_status(cls) -> Dict[str, Dict[str, Any]]:
        """获取所有熔断器状态"""
        with cls._global_lock:
            return {name: breaker.get_status() for name, breaker in cls._breakers.items()}


def circuit_breaker(name: str = None, failure_threshold: int = 3, recovery_timeout: int = 300):
    """
    熔断器装饰器工厂函数

    Usage:
        @circuit_breaker('akshare.stock_zh_index_spot_em', failure_threshold=3, recovery_timeout=300)
        def get_data():
            ...
    """
    def decorator(func):
        breaker_name = name or f"{func.__module__}.{func.__qualname__}"
        breaker = CircuitBreakerManager.get_breaker(breaker_name, failure_threshold=failure_threshold, recovery_timeout=recovery_timeout)

        @wraps(func)
        def wrapper(*args, **kwargs):
            return breaker.call(func, *args, **kwargs)
        return wrapper
    return decorator
