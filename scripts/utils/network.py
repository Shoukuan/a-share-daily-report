"""
网络与超时工具
"""

import json
import time
import urllib.request
from contextvars import copy_context
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Any, Iterable, Optional

import requests


def run_with_timeout(func, seconds, *args, **kwargs):
    """在线程池中执行函数并附加超时。"""
    ctx = copy_context()

    def _runner():
        return ctx.run(func, *args, **kwargs)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_runner)
        try:
            return future.result(timeout=seconds)
        except FuturesTimeoutError:
            raise TimeoutError(f"操作超时（{seconds}秒）")


def post_json_with_retry(
    url: str,
    payload: dict,
    headers: Optional[dict] = None,
    timeout: int = 10,
    retries: int = 1,
    backoff_seconds: float = 0.2,
    retry_statuses: Optional[Iterable[int]] = None,
) -> requests.Response:
    """
    requests.post + 轻量重试。
    仅在网络异常或 retry_statuses 中的 HTTP 状态码时重试。
    """
    retry_status_set = set(retry_statuses or (429, 500, 502, 503, 504))
    last_error: Optional[Exception] = None

    for attempt in range(retries + 1):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
            if resp.status_code in retry_status_set and attempt < retries:
                time.sleep(backoff_seconds * (attempt + 1))
                continue
            return resp
        except (requests.Timeout, requests.ConnectionError, requests.RequestException) as e:
            last_error = e
            if attempt >= retries:
                raise
            time.sleep(backoff_seconds * (attempt + 1))

    if last_error is not None:
        raise last_error
    raise RuntimeError("post_json_with_retry failed unexpectedly")


def urlopen_json_with_retry(
    req: urllib.request.Request,
    timeout: int = 8,
    retries: int = 1,
    backoff_seconds: float = 0.2,
) -> Any:
    """urllib 请求 JSON + 轻量重试。"""
    last_error: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            last_error = e
            if attempt >= retries:
                raise
            time.sleep(backoff_seconds * (attempt + 1))

    if last_error is not None:
        raise last_error
    raise RuntimeError("urlopen_json_with_retry failed unexpectedly")
