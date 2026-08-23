#!/usr/bin/env python3
"""チャート更新時に週次まとめ記事を自動生成する。

owner依頼(2026-08-23): 「毎回更新時にチャート内容の記事を作成して下さい」

著作権(citation-rules): 順位・曲名・アーティスト名は事実データで著作物ではないが、
Soompi のチャートを引いている以上、出典明記は必須。自社の解説を主・引用を従にする。
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from lib.chart_article import build_article, build_title, build_slug, week_label

CHART = {
    "url": "https://www.soompi.com/article/1863384wpp/soompis-k-pop-music-chart-2026-august-week-3",
    "title": "Soompi's K-Pop Music Chart 2026, August Week 3 | Soompi",
    "fetched_at": "2026-08-23T04:03:21.839Z",
    "items": [
        {"rank": 1, "song": "REDRED", "artist": "CORTIS", "album": "GREENGREEN"},
        {"rank": 2, "song": "Lemon Tang", "artist": "Hearts2Hearts", "album": "Lemon Tang"},
        {"rank": 3, "song": "Pretty Girl", "artist": "RESCENE", "album": "Pretty Girl"},
    ],
}
PREV = {
    "title": "Soompi's K-Pop Music Chart 2026, August Week 2 | Soompi",
    "items": [
        {"rank": 1, "song": "REDRED", "artist": "CORTIS"},
        {"rank": 5, "song": "Pretty Girl", "artist": "RESCENE"},
        {"rank": 2, "song": "Old Song", "artist": "Someone"},
    ],
}


class TestWeekLabel:
    def test_parses_month_and_week(self):
        assert week_label(CHART["title"]) == "2026年8月 第3週"

    def test_unparsable_returns_empty(self):
        assert week_label("なんらかの別タイトル") == ""


class TestTitle:
    def test_contains_week_and_first_place(self):
        t = build_title(CHART)
        assert "8月" in t and "第3週" in t
        assert "CORTIS" in t or "REDRED" in t

    def test_length_is_seo_reasonable(self):
        assert 20 <= len(build_title(CHART)) <= 60, build_title(CHART)


class TestSlug:
    def test_is_ascii_and_stable(self):
        s = build_slug(CHART)
        assert s.isascii() and " " not in s
        assert s == build_slug(CHART)

    def test_includes_year_month_week(self):
        s = build_slug(CHART)
        assert "2026" in s and "08" in s and "week3" in s


class TestArticle:
    def test_lists_all_ranks(self):
        html = build_article(CHART)
        for it in CHART["items"]:
            assert it["song"] in html and it["artist"] in html

    def test_cites_soompi_with_link(self):
        html = build_article(CHART)
        assert CHART["url"] in html
        assert "Soompi" in html

    def test_has_table(self):
        assert "<table" in build_article(CHART)

    def test_no_lyrics_quoted(self):
        """歌詞は引用不可(citation-rules)。曲名以外の本文引用を持ち込まない。"""
        html = build_article(CHART)
        assert "<blockquote" not in html

    def test_rank_change_is_shown_when_prev_given(self):
        html = build_article(CHART, prev=PREV)
        # Pretty Girl は 5位 → 3位 なので上昇が示される
        assert "↑" in html or "上昇" in html

    def test_new_entry_is_marked(self):
        html = build_article(CHART, prev=PREV)
        # Lemon Tang は前週に無い = NEW
        assert "NEW" in html or "初登場" in html

    def test_works_without_prev(self):
        html = build_article(CHART)
        assert "REDRED" in html and len(html) > 500

    def test_has_faq_schema(self):
        import json, re
        html = build_article(CHART)
        m = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
        assert m and json.loads(m.group(1))["@type"] == "FAQPage"


class TestNoPrevDataDoesNotFakeNewEntries:
    """前週データが無い時に全曲を「初登場」と書かないこと。

    実生成で「前週データが無いため変動を表示していません」と書きながら
    全10曲を初登場扱いする矛盾が出た。
    """

    def test_all_songs_not_marked_new_without_prev(self):
        html = build_article(CHART)
        # FAQ の一般説明に含まれる「初登場曲」は対象外。
        # 曲を名指しで初登場扱いする本文(「今週の初登場は …」)が出ないこと。
        assert "今週の初登場" not in html
        assert "NEW" not in html

    def test_new_entry_still_works_with_prev(self):
        html = build_article(CHART, prev=PREV)
        assert "今週の初登場" in html
