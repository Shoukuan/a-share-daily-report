"""
发布模块测试：模拟飞书 API 响应
"""

import os
import sys
import types
from datetime import date

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
SCRIPTS_DIR = os.path.join(PROJECT_ROOT, 'scripts')
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, SCRIPTS_DIR)

from scripts.publisher import Publisher


@pytest.fixture
def base_config():
    return {
        'publish': {
            'feishu_message': {
                'target_chat_id': 'ou_test_001',
            }
        }
    }


def test_publish_report_mock_success_with_notification(base_config, monkeypatch):
    monkeypatch.delenv('OPENCLAW_RUNTIME', raising=False)

    publisher = Publisher(base_config)
    monkeypatch.setattr(publisher, '_create_document_mock', lambda title, markdown: ('doc_1', 'https://doc/1'))
    monkeypatch.setattr(publisher, '_send_notification_mock', lambda *args: {'success': True, 'message_id': 'msg_1'})

    result = publisher.publish_morning_report('# test', date(2026, 4, 1), send_notification=True)

    assert result['success'] is True
    assert result['doc_id'] == 'doc_1'
    assert result['notification_sent'] is True
    assert result['notification_message_id'] == 'msg_1'


def test_publish_report_fail_when_create_document_raises(base_config, monkeypatch):
    publisher = Publisher(base_config)
    monkeypatch.setattr(publisher, '_create_document', lambda title, markdown: (_ for _ in ()).throw(RuntimeError('create failed')))

    result = publisher.publish_evening_report('# test', date(2026, 4, 1), send_notification=False)

    assert result['success'] is False
    assert 'create failed' in result['error']


def test_send_notification_without_user_open_id_returns_fail(monkeypatch):
    monkeypatch.delenv('FEISHU_NOTIFY_OPEN_ID', raising=False)
    monkeypatch.delenv('FEISHU_USER_OPEN_ID', raising=False)

    publisher = Publisher({'publish': {'feishu_message': {}}})
    result = publisher._send_notification('title', 'https://doc/1', date(2026, 4, 1), 'morning')

    assert result['success'] is False
    assert '未配置' in result['error']


def test_openclaw_real_path_uses_simulated_feishu_response(base_config, monkeypatch):
    monkeypatch.setenv('OPENCLAW_RUNTIME', '1')

    publisher = Publisher(base_config)
    assert publisher.in_openclaw is True

    monkeypatch.setattr(publisher, '_create_document_real', lambda title, markdown: ('doc_real', 'https://feishu/doc_real'))
    monkeypatch.setattr(publisher, '_send_notification_real', lambda *args: {'success': True, 'message_id': 'msg_real'})

    result = publisher.publish_evening_report('# test', date(2026, 4, 1), send_notification=True)

    assert result['success'] is True
    assert result['doc_id'] == 'doc_real'
    assert result['notification_sent'] is True
    assert result['notification_message_id'] == 'msg_real'


def test_real_notification_fail_does_not_fail_publish(base_config, monkeypatch):
    monkeypatch.setenv('OPENCLAW_RUNTIME', '1')

    publisher = Publisher(base_config)
    monkeypatch.setattr(publisher, '_create_document_real', lambda title, markdown: ('doc_real', 'https://feishu/doc_real'))
    monkeypatch.setattr(publisher, '_send_notification_real', lambda *args: {'success': False, 'error': 'send fail'})

    result = publisher.publish_morning_report('# test', date(2026, 4, 1), send_notification=True)

    assert result['success'] is True
    assert result['doc_id'] == 'doc_real'
    assert result['notification_sent'] is False


def test_openclaw_tools_real_call(base_config, monkeypatch):
    """真实路径：使用 openclaw.tools 提供的函数完成文档创建和消息发送。"""
    monkeypatch.setenv('OPENCLAW_RUNTIME', '1')

    calls = {'doc': 0, 'msg': 0}

    def _fake_create_doc(title, markdown, folder_token=None):
        calls['doc'] += 1
        return {'token': 'doc_tok_123', 'url': 'https://feishu/doc_tok_123'}

    def _fake_send_msg(action, msg_type, content, receive_id_type, receive_id):
        calls['msg'] += 1
        assert action == 'send'
        return {'data': {'message_id': 'msg_tok_456'}}

    fake_openclaw = types.ModuleType('openclaw')
    fake_tools = types.ModuleType('openclaw.tools')
    fake_tools.feishu_create_doc = _fake_create_doc
    fake_tools.feishu_im_user_message = _fake_send_msg
    fake_openclaw.tools = fake_tools

    monkeypatch.setitem(sys.modules, 'openclaw', fake_openclaw)
    monkeypatch.setitem(sys.modules, 'openclaw.tools', fake_tools)

    publisher = Publisher(base_config)
    result = publisher.publish_evening_report('# real', date(2026, 4, 1), send_notification=True)

    assert result['success'] is True
    assert result['doc_id'] == 'doc_tok_123'
    assert result['doc_url'] == 'https://feishu/doc_tok_123'
    assert result['notification_sent'] is True
    assert result['notification_message_id'] == 'msg_tok_456'
    assert calls['doc'] == 1
    assert calls['msg'] == 1
