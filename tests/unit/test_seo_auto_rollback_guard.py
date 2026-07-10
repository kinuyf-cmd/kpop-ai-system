#!/usr/bin/env python3
"""rollback の delta_basis ガードの単体テスト (2026-07-10)。

背景: clicks_delta の定義が baseline 比 → 前週比 に変わる。
      定義の混ざった行で判断すると、閾値 -3 の重みが変わり過剰に差し戻す。
実行: python3 -m pytest tests/unit/test_seo_auto_rollback_guard.py -v
"""
import lib.seo_auto_rollback as rb


LEGACY = {"week": "2026-07-03", "slug": "foo", "clicks_delta": -14}          # 定義: baseline 比
NEW = {"week": "2026-07-17", "slug": "foo", "clicks_delta": -5,
       "delta_basis": "prev_week", "clicks_abs": 2}


def test_ignores_legacy_rows_without_delta_basis():
    """delta_basis を持たない過去行は評価しない。-14 は baseline 比で意味が違う。"""
    assert rb._latest_clicks_delta([LEGACY], "foo") is None


def test_reads_prev_week_rows():
    """delta_basis == 'prev_week' の行は読む。"""
    assert rb._latest_clicks_delta([NEW], "foo") == -5


def test_picks_latest_prev_week_row():
    """複数あれば week 最新を採る。"""
    older = dict(NEW, week="2026-07-17", clicks_delta=-1)
    newer = dict(NEW, week="2026-07-24", clicks_delta=-9)
    assert rb._latest_clicks_delta([newer, older], "foo") == -9


def test_legacy_and_new_mixed_uses_only_new():
    """混在時は新定義の行のみ。過去行に引きずられない。"""
    assert rb._latest_clicks_delta([LEGACY, NEW], "foo") == -5


def test_returns_none_for_unknown_slug():
    assert rb._latest_clicks_delta([NEW], "他の slug") is None


def test_first_week_all_zero_never_triggers_rollback():
    """移行第1週は全件 clicks_delta=0(prev が無いため)。
    閾値 -3 を下回らないので rollback は発火しない。安全側の想定内挙動。"""
    first_week = [dict(NEW, clicks_delta=0)]
    delta = rb._latest_clicks_delta(first_week, "foo")
    assert delta == 0
    assert delta > rb.ROLLBACK_CLICKS_DELTA_THRESHOLD   # 0 > -3 → スキップされる
