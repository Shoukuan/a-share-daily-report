"""
集成测试 - 主流程稳定性（离线）
"""

import os
import sys
from datetime import date

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
SCRIPTS_DIR = os.path.join(PROJECT_ROOT, "scripts")
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, SCRIPTS_DIR)

from scripts.generate_report import ReportGenerator
from scripts.analyzer import Analyzer

pytestmark = pytest.mark.ci_smoke


def _build_generator():
    config_path = os.path.join(PROJECT_ROOT, "config", "config.yaml")
    return ReportGenerator(config_path=config_path)


class TestIntegration:
    """主流程集成测试（使用 monkeypatch 隔离网络）"""

    def test_morning_report_returns_paths_consistently(self, monkeypatch):
        """早报返回值应包含一致的 output_path/report_path"""
        generator = _build_generator()

        monkeypatch.setattr(generator, "_fetch_morning_data", lambda dt: {"sentiment": {"success": True, "data": {}}})
        monkeypatch.setattr(generator, "_analyze_morning_data", lambda data: {"summary": {"data": {"one_sentence": "ok"}}})
        monkeypatch.setattr(generator.renderer, "render_morning_report", lambda analysis, dt: "# A股日报 - 早报预测版\n")
        monkeypatch.setattr(generator.saver, "save_report_with_pdf", lambda markdown, mode, dt: ("/tmp/morning.md", "/tmp/morning.pdf"))

        result = generator.generate_morning_report("2026-04-01", publish=False)

        assert isinstance(result, dict)
        assert result["output_path"] == "/tmp/morning.md"
        assert result["report_path"] == "/tmp/morning.md"
        assert result["pdf_path"] == "/tmp/morning.pdf"
        assert result["mode"] == "morning"
        assert result["date"] == "2026-04-01"

    def test_evening_report_returns_paths_consistently(self, monkeypatch):
        """晚报返回值应包含一致的 output_path/report_path"""
        generator = _build_generator()

        monkeypatch.setattr(generator, "_fetch_evening_data", lambda dt: {"sentiment": {"success": True, "data": {}}})
        monkeypatch.setattr(generator, "_analyze_evening_data", lambda data, dt=None: {"summary": {"data": {"one_sentence": "ok"}}})
        monkeypatch.setattr(generator.renderer, "render_evening_report", lambda analysis, dt: "# A股日报 - 晚报复盘版\n")
        monkeypatch.setattr(generator.saver, "save_report_with_pdf", lambda markdown, mode, dt: ("/tmp/evening.md", None))

        result = generator.generate_evening_report("2026-04-01", publish=False)

        assert isinstance(result, dict)
        assert result["output_path"] == "/tmp/evening.md"
        assert result["report_path"] == "/tmp/evening.md"
        assert result["mode"] == "evening"
        assert result["date"] == "2026-04-01"

    def test_non_trading_day_uses_previous_trade_day(self, monkeypatch):
        """非交易日应回退到最近交易日（2026-03-29 -> 2026-03-27）"""
        generator = _build_generator()

        captured = {}

        def fake_fetch(dt):
            captured["dt"] = dt
            return {}

        monkeypatch.setattr(generator, "_fetch_morning_data", fake_fetch)
        monkeypatch.setattr(generator, "_analyze_morning_data", lambda data: {})
        monkeypatch.setattr(generator.renderer, "render_morning_report", lambda analysis, dt: "# mock\n")
        monkeypatch.setattr(generator.saver, "save_report_with_pdf", lambda markdown, mode, dt: ("/tmp/nontrade.md", None))

        result = generator.generate_morning_report("2026-03-29", publish=False)

        assert result["date"] == "2026-03-27"
        assert captured["dt"] == date(2026, 3, 27)

    def test_watchlist_loading_current_config(self):
        """自选股配置应与当前 watchlist.yaml 一致（2 只A股）"""
        analyzer = Analyzer({"watchlist": {"path": "config/watchlist.yaml"}})

        assert len(analyzer.watchlist) == 2
        stock_codes = [s["code"] for s in analyzer.watchlist]
        assert "002594.SZ" in stock_codes
        assert "300308.SZ" in stock_codes

    def test_trading_strategy_fallback_without_position(self):
        """当未注入 position 时，策略应能用情绪/资金数据降级生成"""
        analyzer = Analyzer({"watchlist": {"path": "config/watchlist.yaml"}})

        data = {
            "sentiment": {"success": True, "data": {"limit_up_count": 95, "max_consec_up": 4}},
            "money_flow": {"success": True, "data": {"northbound": 2e9}},
            "index_sh": {"success": True, "data": {"change_pct": 1.2}},
        }
        result = analyzer.generate_trading_strategy(data)

        assert result["success"] is True
        assert result["data"]["strategy"] in {"offensive", "neutral", "defensive"}
        assert "logic" in result["data"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
