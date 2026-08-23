#!/usr/bin/env python3
"""本番に出ている「定期更新されるはずの表示」の鮮度を検査する。

2026-08-23: ミュージックチャートが Playwright ブラウザ消失で8日間停止していたが、
cron は登録済み・非破壊フォールバックで exit 0 のため誰も気づけなかった。
「cronがあるか」でなく「本番の実表示がいつのものか」を見る監査が要る。
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from lib.staleness_audit import evaluate, CHECKS


class TestEvaluate:
    def test_fresh_is_ok(self):
        r = evaluate("chart", age_days=1.0, max_age_days=9)
        assert r["ok"] and r["level"] == "ok"

    def test_over_threshold_is_stale(self):
        r = evaluate("chart", age_days=12.0, max_age_days=9)
        assert not r["ok"] and r["level"] == "stale"

    def test_exactly_at_threshold_is_ok(self):
        assert evaluate("chart", age_days=9.0, max_age_days=9)["ok"]

    def test_unknown_age_is_reported_not_silently_ok(self):
        """取得できなかったものを ok 扱いしない(これが今回の事故の本質)。"""
        r = evaluate("chart", age_days=None, max_age_days=9)
        assert not r["ok"] and r["level"] == "unknown"

    def test_message_contains_name_and_age(self):
        r = evaluate("chart", age_days=12.0, max_age_days=9)
        assert "chart" in r["message"] and "12" in r["message"]


class TestChecksRegistry:
    def test_chart_is_registered(self):
        assert any(c["key"] == "soompi_chart" for c in CHECKS)

    def test_every_check_has_threshold_and_probe(self):
        for c in CHECKS:
            assert c.get("max_age_days") and callable(c.get("probe")), c["key"]

    def test_thresholds_are_reasonable(self):
        """週次更新なら9日程度。0や極端な値を許さない。"""
        for c in CHECKS:
            assert 0 < c["max_age_days"] <= 40, c["key"]


class TestThresholdCatchesRealIncident:
    """2026-08-23 の実事故(週次チャートが8日停止)を検出できること。

    週次更新なので「1週スキップ」= 8日前後で気づけないと意味がない。
    閾値9日では実事故(8日)を見逃していた。
    """

    def _chart_threshold(self):
        return next(c["max_age_days"] for c in CHECKS if c["key"] == "soompi_chart")

    def test_eight_days_is_detected(self):
        assert not evaluate("chart", 8.0, self._chart_threshold())["ok"]

    def test_normal_weekly_cycle_is_ok(self):
        """正常な週次更新(最大7日+取得ラグ)は鳴らさない。"""
        assert evaluate("chart", 7.0, self._chart_threshold())["ok"]
