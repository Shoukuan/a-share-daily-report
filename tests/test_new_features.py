"""
新增功能单元测试
覆盖：Kelly 公式配置化、交易日历（2026 中秋）、Pydantic V2 schemas、config_validator
"""

import os
import sys
import pytest
from datetime import date

PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
SCRIPTS_DIR = os.path.join(PROJECT_ROOT, "scripts")
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, SCRIPTS_DIR)

pytestmark = pytest.mark.ci_smoke


# ---------------------------------------------------------------------------
# 1. Kelly 公式 — 从配置加载参数
# ---------------------------------------------------------------------------

class TestKellyConfig:
    """凯利公式参数通过 config 注入"""

    def _make_analyzer(self, win_rate=0.5, risk_reward=2.0, half_kelly=False):
        from scripts.analyzer import Analyzer
        return Analyzer({
            "watchlist": {"path": "config/watchlist.yaml"},
            "analysis": {
                "kelly": {
                    "win_rate": win_rate,
                    "risk_reward_ratio": risk_reward,
                    "half_kelly": half_kelly,
                }
            }
        })

    def test_default_kelly_params(self):
        """默认参数：p=0.5, b=2.0，不使用半凯利"""
        a = self._make_analyzer()
        # Kelly parameters are now in PositionSizer module
        assert a.position_sizer._kelly_win_rate == 0.5
        assert a.position_sizer._kelly_risk_reward == 2.0
        assert a.position_sizer._kelly_half is False

    def test_custom_kelly_params(self):
        """自定义参数被正确加载"""
        a = self._make_analyzer(win_rate=0.6, risk_reward=3.0, half_kelly=True)
        assert a.position_sizer._kelly_win_rate == 0.6
        assert a.position_sizer._kelly_risk_reward == 3.0
        assert a.position_sizer._kelly_half is True

    def test_half_kelly_reduces_max_position(self):
        """半凯利模式下仓位上限应低于普通模式"""
        normal = self._make_analyzer(half_kelly=False)
        half = self._make_analyzer(half_kelly=True)

        data = {
            "sentiment": {"success": True, "data": {"limit_up_count": 80, "max_consec_up": 3}},
            "money_flow": {"success": True, "data": {"northbound": 2e9}},
            "index_sh": {"success": True, "data": {"change_pct": 0.5}},
        }
        r_normal = normal.suggest_position(data)
        r_half = half.suggest_position(data)

        assert r_normal["success"] is True
        assert r_half["success"] is True
        assert r_half["data"]["position_max"] <= r_normal["data"]["position_max"]

    def test_higher_win_rate_raises_position(self):
        """胜率更高时仓位上限应不低于默认胜率"""
        default = self._make_analyzer(win_rate=0.5)
        high = self._make_analyzer(win_rate=0.7)

        data = {
            "sentiment": {"success": True, "data": {"limit_up_count": 60, "max_consec_up": 2}},
            "money_flow": {"success": True, "data": {"northbound": 1e9}},
            "index_sh": {"success": True, "data": {"change_pct": 0.2}},
        }
        r_default = default.suggest_position(data)
        r_high = high.suggest_position(data)

        assert r_high["data"]["kelly_fraction"] >= r_default["data"]["kelly_fraction"]

    def test_kelly_logic_mentions_half_mode(self):
        """半凯利模式时 logic 字段应含说明"""
        a = self._make_analyzer(half_kelly=True)
        data = {
            "sentiment": {"success": True, "data": {"limit_up_count": 50}},
            "money_flow": {"success": True, "data": {}},
            "index_sh": {"success": True, "data": {"change_pct": 0.3}},
        }
        result = a.suggest_position(data)
        assert "半凯利" in result["data"]["logic"]


# ---------------------------------------------------------------------------
# 2. 交易日历 — 2026 中秋节
# ---------------------------------------------------------------------------

class TestTradeCalendar2026:
    """2026 年新增节假日验证"""

    def test_mid_autumn_festival_is_holiday(self):
        """2026-09-25（中秋节）应为非交易日"""
        from scripts.trade_calendar import is_trade_day
        assert is_trade_day("2026-09-25") is False
        assert is_trade_day("2026-09-26") is False
        assert is_trade_day("2026-09-27") is False

    def test_day_before_mid_autumn_is_trade_day(self):
        """2026-09-24（周四，中秋前一天）应为交易日"""
        from scripts.trade_calendar import is_trade_day
        assert is_trade_day("2026-09-24") is True

    def test_day_after_golden_week_is_trade_day(self):
        """2026-10-08（国庆后第一个交易日，周四）应为交易日"""
        from scripts.trade_calendar import is_trade_day
        assert is_trade_day("2026-10-08") is True

    def test_prev_trade_day_skips_mid_autumn(self):
        """从 2026-09-27 往前找，应跳过中秋节回到 2026-09-24"""
        from scripts.trade_calendar import prev_trade_day
        result = prev_trade_day("2026-09-27")
        assert result == date(2026, 9, 24)

    def test_qingming_2026_is_holiday(self):
        """2026 清明节 04-05/06/07 应为非交易日"""
        from scripts.trade_calendar import is_trade_day
        assert is_trade_day("2026-04-05") is False
        assert is_trade_day("2026-04-06") is False
        assert is_trade_day("2026-04-07") is False


# ---------------------------------------------------------------------------
# 3. Pydantic V2 schemas
# ---------------------------------------------------------------------------

class TestSchemasV2:
    """验证 schemas.py 已迁移到 Pydantic V2"""

    def test_index_schema_valid(self):
        from scripts.schemas import IndexDataSchema
        data = dict(
            ts_code="000001.SH", name="上证指数", trade_date="2026-04-01",
            close=3200.0, open=3190.0, high=3210.0, low=3185.0,
            pre_close=3195.0, change=5.0, change_pct=0.16,
            vol=100000, amount=500000000, source="akshare",
        )
        schema = IndexDataSchema(**data)
        dumped = schema.model_dump()  # Pydantic V2 API
        assert dumped["ts_code"] == "000001.SH"
        assert dumped["change_pct"] == 0.16

    def test_index_schema_rejects_extreme_change_pct(self):
        from scripts.schemas import IndexDataSchema
        import pydantic
        data = dict(
            ts_code="000001.SH", name="上证指数", trade_date="2026-04-01",
            close=3200.0, open=3190.0, high=3210.0, low=3185.0,
            pre_close=3195.0, change=700.0, change_pct=25.0,  # 超限
            vol=100000, amount=500000000,
        )
        with pytest.raises(pydantic.ValidationError):
            IndexDataSchema(**data)

    def test_news_schema_validates_importance(self):
        from scripts.schemas import NewsItemSchema
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            NewsItemSchema(title="test", importance="critical")  # 非法值

    def test_validate_schema_returns_model_dump(self):
        from scripts.schemas import IndexDataSchema, validate_schema
        data = dict(
            ts_code="000001.SH", name="上证指数", trade_date="2026-04-01",
            close=3200.0, open=3190.0, high=3210.0, low=3185.0,
            pre_close=3195.0, change=5.0, change_pct=0.16,
            vol=100000, amount=500000000,
        )
        validated, errors = validate_schema(data, IndexDataSchema)
        assert errors == []
        assert isinstance(validated, dict)
        assert validated["name"] == "上证指数"

    def test_validate_schema_returns_errors_on_bad_data(self):
        from scripts.schemas import IndexDataSchema, validate_schema
        bad_data = dict(ts_code="x", name="", trade_date="bad", close=-1,
                        open=0, high=0, low=0, pre_close=0, change=0,
                        change_pct=0, vol=0, amount=0)
        _, errors = validate_schema(bad_data, IndexDataSchema)
        assert len(errors) > 0


# ---------------------------------------------------------------------------
# 4. Config validator (Pydantic V2)
# ---------------------------------------------------------------------------

class TestConfigValidator:
    """config_validator.py 使用 Pydantic V2 AppConfig 验证"""

    def _minimal_config(self):
        return {
            "output": {"base_dir": "reports", "morning_subdir": "morning", "evening_subdir": "evening"},
            "watchlist": {"path": "config/watchlist.yaml"},
            "data_sources": {},
        }

    def test_valid_config_passes(self):
        from scripts.config_validator import validate_config
        validate_config(self._minimal_config())  # 不应抛出异常

    def test_missing_output_raises(self):
        from scripts.config_validator import validate_config
        from errors import ConfigValidationError
        cfg = self._minimal_config()
        del cfg["output"]
        with pytest.raises(ConfigValidationError):
            validate_config(cfg)

    def test_missing_watchlist_path_raises(self):
        from scripts.config_validator import validate_config
        from errors import ConfigValidationError
        cfg = self._minimal_config()
        cfg["watchlist"] = {"path": ""}  # 空字符串应失败
        with pytest.raises(ConfigValidationError):
            validate_config(cfg)

    def test_invalid_pdf_engine_raises(self):
        from scripts.config_validator import validate_config
        from errors import ConfigValidationError
        cfg = self._minimal_config()
        cfg["publish"] = {"pdf": {"enabled": True, "output_dir": "reports/pdf", "engine": "ghostscript"}}
        with pytest.raises(ConfigValidationError):
            validate_config(cfg)

    def test_kelly_config_defaults_applied(self):
        from scripts.config_validator import AppConfig
        cfg = self._minimal_config()
        app = AppConfig(**cfg)
        assert app.analysis.kelly.win_rate == 0.5
        assert app.analysis.kelly.risk_reward_ratio == 2.0
        assert app.analysis.kelly.half_kelly is False

    def test_kelly_config_custom_values(self):
        from scripts.config_validator import AppConfig
        cfg = self._minimal_config()
        cfg["analysis"] = {"kelly": {"win_rate": 0.65, "risk_reward_ratio": 3.0, "half_kelly": True}}
        app = AppConfig(**cfg)
        assert app.analysis.kelly.win_rate == 0.65
        assert app.analysis.kelly.half_kelly is True

    def test_non_dict_config_raises(self):
        from scripts.config_validator import validate_config
        from errors import ConfigValidationError
        with pytest.raises(ConfigValidationError):
            validate_config("not a dict")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
