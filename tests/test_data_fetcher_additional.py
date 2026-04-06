"""
数据采集模块补充测试：覆盖 success/fail 场景
"""

import os
import sys
import types
from datetime import date

import pandas as pd
import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
SCRIPTS_DIR = os.path.join(PROJECT_ROOT, 'scripts')
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, SCRIPTS_DIR)

from scripts.data_fetcher import DataFetcher
from scripts.utils.cache import clear_cache


class _DummyAK:
    def stock_market_activity_legu(self):
        return pd.DataFrame()


@pytest.fixture
def fetcher(monkeypatch):
    def _fake_init_akshare(self):
        self.ak = _DummyAK()

    def _fake_init_tushare(self):
        self.ts = None
        self.pro = None

    monkeypatch.setattr(DataFetcher, '_init_akshare', _fake_init_akshare)
    monkeypatch.setattr(DataFetcher, '_init_tushare', _fake_init_tushare)

    for namespace in [
        'akshare', 'yfinance', 'mx_search', 'mx_data', 'indices', 'overview', 'depth'
    ]:
        clear_cache(namespace=namespace)

    return DataFetcher({'data_sources': {}})


def test_index_fetch_success_from_akshare_spot(fetcher, monkeypatch):
    df = pd.DataFrame([{
        '代码': '000001',
        '最新价': 3200.0,
        '昨收': 3180.0,
        '涨跌幅': 0.63,
        '今开': 3190.0,
        '最高': 3210.0,
        '最低': 3188.0,
        '涨跌额': 20.0,
        '成交量': 123456,
        '成交额': 500000000000,
    }])
    monkeypatch.setattr(fetcher, '_get_spot_em', lambda: (df, None))

    result = fetcher.get_index_data('000001.SH', date(2026, 4, 1))

    assert result['success'] is True
    assert result['source'] == 'akshare_spot'
    assert result['data']['ts_code'] == '000001.SH'
    assert result['data']['amount'] == 500000000000


def test_index_fetch_fail_all_sources(fetcher, monkeypatch):
    monkeypatch.setattr(fetcher, '_get_spot_em', lambda: (None, 'spot unavailable'))
    monkeypatch.setattr(fetcher, '_get_index_data_baostock', lambda code, dt: {'success': False, 'source': 'baostock'})
    monkeypatch.setattr(fetcher, '_get_index_data_yfinance', lambda code, dt: {'success': False, 'source': 'none'})

    result = fetcher.get_index_data('000001.SH', date(2026, 4, 1))

    assert result['success'] is False
    assert result['source'] == 'none'


def test_sentiment_fetch_success(fetcher, monkeypatch):
    df_limit = pd.DataFrame({'连板数': [1, 2, 5]})
    monkeypatch.setattr(fetcher.ak, 'stock_zt_pool_em', lambda date: df_limit, raising=False)
    monkeypatch.setattr(fetcher, 'get_index_data', lambda code, dt: {'success': True, 'data': {'amount': 100000000000}})

    result = fetcher.get_market_sentiment(date(2026, 4, 1))

    assert result['success'] is True
    assert result['source'] == 'akshare'
    assert result['data']['limit_up_count'] == 3
    assert result['data']['max_consec_up'] == 5


def test_sentiment_fetch_fail_without_sources(fetcher):
    fetcher.ak = None
    fetcher.pro = None

    result = fetcher.get_market_sentiment(date(2026, 4, 1))

    assert result['success'] is False
    assert result['source'] == 'none'


def test_money_flow_fallback_to_tushare(fetcher):
    fetcher.ak = None

    class _DummyPro:
        def moneyflow_hsgt(self, start_date, end_date):
            return pd.DataFrame([{'trade_date': '20260401', 'north_money': 12345.6}])

    fetcher.pro = _DummyPro()
    result = fetcher.get_money_flow(date(2026, 4, 1))

    assert result['success'] is True
    assert result['data']['northbound'] == pytest.approx(12345.6 * 1e4)


def test_industry_fund_flow_fail_without_ak_and_mx_key(fetcher, monkeypatch):
    fetcher.ak = None
    monkeypatch.setattr(fetcher, '_get_mx_apikey', lambda: '')

    result = fetcher.get_industry_fund_flow(date(2026, 4, 1))

    assert result['success'] is False
    assert result['source'] == 'none'


def test_us_market_success_with_mock_yfinance(fetcher, monkeypatch):
    class _DummyTicker:
        def __init__(self, ticker):
            self.ticker = ticker
            self.info = {'shortName': ticker}

        def history(self, period='2d'):
            return pd.DataFrame([
                {'Close': 100.0},
                {'Close': 101.5},
            ])

    fake_module = types.SimpleNamespace(Ticker=_DummyTicker)
    monkeypatch.setitem(sys.modules, 'yfinance', fake_module)

    result = fetcher.get_us_market()

    assert result['success'] is True
    assert result['source'] == 'yfinance'
    assert 'indices' in result['data']
    assert 'nasdaq' in result['data']['indices']


def test_us_market_fail_when_yfinance_missing(fetcher, monkeypatch):
    real_import = __import__

    def _mock_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == 'yfinance':
            raise ImportError('no yfinance')
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr('builtins.__import__', _mock_import)

    result = fetcher.get_us_market()

    assert result['success'] is False
    assert result['source'] == 'none'


def test_news_success_and_fail(fetcher, monkeypatch):
    class _Resp:
        status_code = 200

        def json(self):
            return {
                'status': 0,
                'data': {
                    'data': {
                        'llmSearchResponse': {
                            'data': [
                                {
                                    'title': '测试新闻',
                                    'content': '内容',
                                    'date': '2026-04-01 09:00:00',
                                    'source': 'mock',
                                    'jumpUrl': 'https://example.com',
                                    'secuList': [],
                                }
                            ]
                        }
                    }
                },
            }

    monkeypatch.setattr(fetcher, '_get_mx_apikey', lambda: 'dummy')
    monkeypatch.setattr('fetchers.news_fetcher.post_json_with_retry', lambda **kwargs: _Resp())

    success_result = fetcher.get_news(date(2026, 4, 1), limit=5)
    assert success_result['success'] is True
    assert success_result['source'] == 'mx-search'

    monkeypatch.setattr(fetcher, '_get_mx_apikey', lambda: '')
    fail_result = fetcher.get_news(date(2026, 4, 2), limit=5)
    assert fail_result['success'] is False
    assert fail_result['source'] == 'none'


def test_sector_success_and_fail(fetcher, monkeypatch):
    monkeypatch.setattr(fetcher.ak, 'stock_board_industry_summary_ths', lambda: pd.DataFrame({
        '板块': ['芯片', '算力'],
        '涨跌幅': [2.5, 1.5],
        '领涨股': ['中芯国际', '浪潮信息'],
        '领涨股-涨跌幅': [3.1, 2.2],
    }), raising=False)
    monkeypatch.setattr(fetcher.ak, 'stock_board_concept_summary_ths', lambda: pd.DataFrame({
        '概念名称': ['AI', '机器人'],
        '龙头股': ['科大讯飞', '埃斯顿'],
        '驱动事件': ['算力扩容', '政策支持'],
    }), raising=False)

    success_result = fetcher.get_sector_data(date(2026, 4, 1))
    assert success_result['success'] is True
    assert success_result['source'] == 'akshare_ths'
    assert len(success_result['data']['industry']) == 2

    fetcher.ak = None
    fail_result = fetcher.get_sector_data(date(2026, 4, 2))
    assert fail_result['success'] is False
    assert fail_result['source'] == 'none'
