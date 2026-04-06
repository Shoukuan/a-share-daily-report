"""
可观测性测试：trace 传播 / 脱敏 / 耗时记录
"""

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
SCRIPTS_DIR = os.path.join(PROJECT_ROOT, 'scripts')
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, SCRIPTS_DIR)

from scripts.utils.network import run_with_timeout
from scripts.utils.trace import get_trace_id, set_trace_id
from scripts.utils.logger import _sanitize_obj, _sanitize_text
from scripts.utils import observability


def test_trace_propagation_with_run_with_timeout():
    set_trace_id('trace_test_123')
    value = run_with_timeout(lambda: get_trace_id(), 2)
    assert value == 'trace_test_123'


def test_sensitive_data_redaction():
    payload = {
        'api_key': 'abc123456789',
        'token': 'tok_987654321',
        'nested': {'authorization': 'Bearer this_should_not_show'},
        'normal': 'hello',
    }
    sanitized = _sanitize_obj(payload)

    assert sanitized['api_key'] == '***'
    assert sanitized['token'] == '***'
    assert sanitized['nested']['authorization'] == '***'
    assert sanitized['normal'] == 'hello'

    text = 'Authorization=Bearer very_secret_token_12345'
    assert 'very_secret_token_12345' not in _sanitize_text(text)


def test_stage_timer_records_duration(monkeypatch):
    captured = {}

    def _fake_emit(stage, seconds, status='ok'):
        captured['stage'] = stage
        captured['seconds'] = seconds
        captured['status'] = status

    monkeypatch.setattr(observability, 'record_stage_duration', _fake_emit)

    with observability.stage_timer('unit.test.stage'):
        _ = 1 + 1

    assert captured['stage'] == 'unit.test.stage'
    assert captured['seconds'] >= 0
    assert captured['status'] == 'ok'
