#!/usr/bin/env python3
"""作品クラスタの成否を、配信日を基準に追跡する。

2026-08-23 実測でわかったこと:
  - 記事公開のタイミング(配信前/後)は成否を分けない
    恋は飴模様(-18日)も鉄槌教師(+17日)も当たっている
  - 分けるのは「作品自体の検索需要」。需要imp>=1000 の作品は平均clk307、
    1000未満は平均clk6 で 47倍差
  - ただし需要は配信後にしか測れない。しかも記事公開直後は配信前なので
    imp が小さく、そこで「外れ」と判断すると誤る
    (恋は飴模様は 7〜13日目 imp69 → 14〜20日目 imp3,417)

したがって必要なのは「事前予測」ではなく「配信日を基準にした正しい評価」。
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from lib.work_cluster_tracker import evaluate_work, VERDICT_TOO_EARLY


class TestTooEarly:
    """配信前・配信直後は判定しない(誤って外れ扱いしないため)。"""

    def test_before_release_is_too_early(self):
        r = evaluate_work("恋は命がけ", imp=92, days_since_release=-3)
        assert r["verdict"] == VERDICT_TOO_EARLY

    def test_within_two_weeks_of_release_is_too_early(self):
        r = evaluate_work("恋は命がけ", imp=92, days_since_release=10)
        assert r["verdict"] == VERDICT_TOO_EARLY

    def test_unknown_release_is_too_early(self):
        r = evaluate_work("なにか", imp=50, days_since_release=None)
        assert r["verdict"] == VERDICT_TOO_EARLY


class TestVerdictAfterEnoughTime:
    def test_high_demand_is_hit(self):
        r = evaluate_work("鉄槌教師", imp=13399, days_since_release=60)
        assert r["verdict"] == "hit"

    def test_low_demand_is_miss(self):
        r = evaluate_work("最後列からの声", imp=128, days_since_release=60)
        assert r["verdict"] == "miss"

    def test_threshold_boundary(self):
        assert evaluate_work("x", imp=1000, days_since_release=60)["verdict"] == "hit"
        assert evaluate_work("x", imp=999, days_since_release=60)["verdict"] == "miss"


class TestReportsReason:
    def test_includes_numbers(self):
        r = evaluate_work("鉄槌教師", imp=13399, days_since_release=60)
        assert "13,399" in r["message"] or "13399" in r["message"]

    def test_too_early_says_why(self):
        r = evaluate_work("恋は命がけ", imp=92, days_since_release=5)
        assert "配信" in r["message"]
