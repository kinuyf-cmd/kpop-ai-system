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


# ── 2026-10-11: 前週比の実分布から決めた閾値と、手動改稿を守るガード ──────────

def _row(week, delta, abs_, slug="foo"):
    return {"week": week, "slug": slug, "clicks_delta": delta, "clicks_abs": abs_,
            "delta_basis": "prev_week"}


def test_week_totals_sum_all_queries_of_latest_week():
    """1記事が同じ週に複数クエリ行を持つ。最新週の全行を合計する。"""
    rows = [_row("2026-10-02", -9, 1), _row("2026-10-09", -4, 6), _row("2026-10-09", -2, 3)]
    assert rb._latest_week_totals(rows, "foo") == (-6, 15)


def test_week_totals_none_for_unknown_slug():
    assert rb._latest_week_totals([_row("2026-10-09", -6, 1)], "他") == (None, None)


def test_main_article_natural_swing_is_not_harmful():
    """実測: 主力記事が 33→28clk(-5, -15%)。自然な揺れなので差し戻さない。"""
    assert not rb._is_harmful(-5, 33)


def test_small_absolute_drop_is_not_harmful():
    """実測: 5→2clk(-3, -60%)。割合は大きいが絶対数が小さい。"""
    assert not rb._is_harmful(-3, 5)


def test_large_absolute_and_relative_drop_is_harmful():
    assert rb._is_harmful(-8, 20)


def test_missing_delta_is_not_harmful():
    assert not rb._is_harmful(None, None)


def test_modified_after_enrich_blocks_rollback():
    """強化後に手動改稿された記事を古いバックアップで上書きしない。"""
    api = lambda m, p: ({"modified_gmt": "2026-10-11T09:07:00"}, None)
    assert rb._modified_after(1, "2026-10-05T06:45:00+00:00", api)


def test_untouched_since_enrich_allows_rollback():
    api = lambda m, p: ({"modified_gmt": "2026-10-05T06:45:30"}, None)
    assert not rb._modified_after(1, "2026-10-05T06:45:00+00:00", api)


def test_unknown_modified_time_blocks_rollback():
    """更新日時が取れないときは安全側(差し戻さない)。"""
    assert rb._modified_after(1, "2026-10-05T06:45:00+00:00", lambda m, p: (None, "API_FAIL"))
