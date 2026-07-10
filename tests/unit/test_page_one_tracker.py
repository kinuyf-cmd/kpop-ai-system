#!/usr/bin/env python3
"""page_one_tracker 計測ロジックの単体テスト (2026-07-10)。

背景: tracker が slug を空固定・theme を破棄・clicks_delta が時間経過を測っていた。
設計: docs/superpowers/specs/2026-07-10-page-one-tracker-measurement-fix-design.md

テストは GSC API を叩かない。実測7行を写した固定フィクスチャを純関数に渡す。
GSC の28日窓は毎週スライドするため、ライブ値をアサートすると時間経過で勝手に壊れる。

実行: python3 -m pytest tests/unit/test_page_one_tracker.py -v
"""
import lib.page_one_tracker as t


def test_slug_of_strips_fragment():
    """GSC が返すアンカー付き URL からフラグメントを除去する。"""
    url = "https://www.kpopjournal.tokyo/swf3-osaka-ojo-gang-members/#kpop-h-0"
    assert t._slug_of(url) == "swf3-osaka-ojo-gang-members"


def test_slug_of_strips_query_string():
    """クエリ文字列を除去する。"""
    url = "https://www.kpopjournal.tokyo/swf3-osaka-ojo-gang-members/?utm_source=x"
    assert t._slug_of(url) == "swf3-osaka-ojo-gang-members"


def test_slug_of_handles_no_trailing_slash():
    """末尾スラッシュの有無どちらでも同じ slug を返す。"""
    assert t._slug_of("https://www.kpopjournal.tokyo/foo-bar") == "foo-bar"
    assert t._slug_of("https://www.kpopjournal.tokyo/foo-bar/") == "foo-bar"


def test_slug_of_returns_empty_for_external_domain():
    """外部ドメインは空文字。rollback が誤って他サイトの記事を差し戻さないため。"""
    assert t._slug_of("https://soompi.com/article/123") == ""


def test_slug_of_returns_empty_for_home_page():
    """トップページは記事ではないので空文字。"""
    assert t._slug_of("https://www.kpopjournal.tokyo/") == ""


# ojogang メンバー の GSC 実測7行を写したフィクスチャ。
# 本文 URL 1行(imp=92) + #kpop-h-0..6 のアンカー6行(各 imp=2)。
# imp 合計 104。加重平均 5.79 / 単純平均 9.74。
# position は GSC 表示値(小数2桁)。この定義がそのまま期待値を決める。
ROWS = [
    {"position": 5.18, "impressions": 92},
    *({"position": 10.50, "impressions": 2} for _ in range(6)),
]


def test_weighted_position_is_impression_weighted():
    """imp 加重平均。単純平均 9.74 に引きずられないこと。"""
    assert round(t._weighted_position(ROWS), 2) == 5.79


def test_weighted_position_differs_from_naive_mean():
    """単純平均との差を明示。この差こそが欠陥2の被害額。"""
    naive = sum(r["position"] for r in ROWS) / len(ROWS)
    assert round(naive, 2) == 9.74
    assert round(t._weighted_position(ROWS), 2) != round(naive, 2)


def test_weighted_position_falls_back_on_zero_impressions():
    """imp 合計 0 ならゼロ除算。単純平均にフォールバックする。"""
    rows = [{"position": 4.0, "impressions": 0}, {"position": 6.0, "impressions": 0}]
    assert t._weighted_position(rows) == 5.0


def test_weighted_position_empty_rows_returns_zero():
    """空行なら 0.0。呼び出し側は rows 非空を保証するが念のため。"""
    assert t._weighted_position([]) == 0.0


def _row(page_url, imp):
    """GSC query×page 応答の行を作る。keys = [query, page]。"""
    return {"keys": ["ojogang メンバー", page_url], "impressions": imp}


# 実測7行を GSC 応答形式で写したもの。全て同一 slug に集約され imp 104 になる。
SLUG_ROWS = [
    _row("https://www.kpopjournal.tokyo/swf3-osaka-ojo-gang-members/", 92),
    *(_row(f"https://www.kpopjournal.tokyo/swf3-osaka-ojo-gang-members/#kpop-h-{i}", 2)
      for i in range(6)),
]


def test_pick_slug_aggregates_fragments():
    """フラグメント別行を同一 slug に集約して選ぶ。"""
    assert t._pick_slug(SLUG_ROWS) == "swf3-osaka-ojo-gang-members"


def test_pick_slug_prefers_highest_aggregate_impressions():
    """集約 imp が最大の slug を選ぶ。行数ではなく imp 合計で決める。"""
    rows = [
        _row("https://www.kpopjournal.tokyo/loser/", 10),
        _row("https://www.kpopjournal.tokyo/loser/#kpop-h-0", 10),
        _row("https://www.kpopjournal.tokyo/winner/", 30),
    ]
    assert t._pick_slug(rows) == "winner"


def test_pick_slug_tie_break_is_deterministic():
    """imp 同数なら slug の辞書順で安定化。実行ごとに揺れると rollback 突合が壊れる。"""
    rows = [
        _row("https://www.kpopjournal.tokyo/zebra/", 50),
        _row("https://www.kpopjournal.tokyo/alpha/", 50),
    ]
    assert t._pick_slug(rows) == "alpha"
    # 入力順を反転しても同じ結果
    assert t._pick_slug(list(reversed(rows))) == "alpha"


def test_pick_slug_ignores_external_domains():
    """外部ドメイン行は slug 候補にしない。"""
    rows = [
        _row("https://soompi.com/article/123", 999),
        _row("https://www.kpopjournal.tokyo/mine/", 5),
    ]
    assert t._pick_slug(rows) == "mine"


def test_pick_slug_returns_empty_when_no_internal_page():
    """自サイト行が1つも無ければ空文字。theme は queue 由来なので生き残る。"""
    assert t._pick_slug([_row("https://soompi.com/a/1", 10)]) == ""
