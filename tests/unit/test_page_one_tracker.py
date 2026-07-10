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
