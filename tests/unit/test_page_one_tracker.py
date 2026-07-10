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
