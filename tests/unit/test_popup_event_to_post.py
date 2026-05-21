"""N-2 ユニットテスト: lib/popup_event_to_post.py

slugify と esc_sql の SQL インジェクション安全性を検証。
"""
import os
import sys
from pathlib import Path

# /tmp/wp_stg.txt が無い環境でも import できるように先にダミーを作る
_creds = Path("/tmp/wp_stg.txt")
if not _creds.exists():
    _creds.write_text("DB_HOST=localhost\nDB_NAME=test\nDB_USER=test\nDB_PASS=test\n")

from lib.popup_event_to_post import (
    slugify, esc_sql, esc_html,
    _parse_period_dates, _guess_popup_area, _guess_popup_status,
    build_popup_article,
)


class TestSlugify:
    def test_basic_ascii(self):
        s = slugify("BTS Popup Tokyo")
        assert s
        assert all(c.isalnum() or c in "-_" for c in s)

    def test_japanese_title_fallback(self):
        # 日本語のみだと正規表現で英数字が残らず、fallback の hash slug を使う
        s = slugify("ブラックピンク ポップアップ")
        assert s.startswith("popup-") or len(s) > 0

    def test_max_len_enforced(self):
        long_title = "a" * 200
        s = slugify(long_title, max_len=70)
        assert len(s) <= 70

    def test_no_consecutive_dashes(self):
        s = slugify("BTS---POPUP---STORE")
        assert "---" not in s

    def test_trim_leading_trailing_dash(self):
        s = slugify("---BTS POPUP---")
        assert not s.startswith("-")
        assert not s.endswith("-")


class TestEscSql:
    def test_basic_string(self):
        assert esc_sql("hello") == "hello"

    def test_single_quote_escaped(self):
        # SQL インジェクション対策: ' を '' にエスケープ
        assert esc_sql("O'Brien") == "O''Brien"

    def test_backslash_escaped(self):
        assert esc_sql("path\\to") == "path\\\\to"

    def test_none_returns_empty(self):
        assert esc_sql(None) == ""

    def test_combined_quote_backslash(self):
        # 順序が重要: バックスラッシュを先にエスケープしてからクオート
        assert esc_sql("a\\'b") == "a\\\\''b"


class TestParsePeriodDates:
    """タスク#27: 開催期間文字列 → (start, end)。年あり/年なし両形式。"""

    def test_year_full_format(self):
        s, e = _parse_period_dates("2026年01月08日 〜 2026年02月28日")
        assert s == "2026-01-08" and e == "2026-02-28"

    def test_short_md_format_no_year(self):
        # PRTIMES 形式(年なし)。年は実行年で補完される。
        s, e = _parse_period_dates("5/22（金）〜5/24（日） 11:00～19:00")
        assert s.endswith("-05-22") and e.endswith("-05-24")

    def test_unparseable_returns_empty(self):
        # 日付に分解できないものは捏造せず空を返す
        assert _parse_period_dates("2026年4月開催") == ("", "")
        assert _parse_period_dates("") == ("", "")


class TestGuessPopupArea:
    """タスク#27: 会場/住所の日本ロケーションは title の「韓国」より優先。"""

    def test_japanese_venue_overrides_korea_in_title(self):
        # 韓国コスメの渋谷 popup を seoul と誤タグしない
        sig = {
            "title": "韓国最新ビューティーが渋谷に集結！ポップアップ",
            "description_snippet": "韓国コスメ",
            "kbz_info": {"会場": "LAIDOUT SHIBUYA（東京都渋谷区渋谷1-15-12）"},
        }
        assert _guess_popup_area(sig) == "tokyo"

    def test_korean_place_in_venue_is_seoul(self):
        sig = {"title": "聖水のカフェ", "description_snippet": "",
               "kbz_info": {"開催エリア": "聖水", "住所": "ソウル特別市 聖水洞"}}
        assert _guess_popup_area(sig) == "seoul"

    def test_bare_korea_in_title_falls_back_seoul(self):
        # 会場情報が無く title に「韓国」だけ → 従来通り seoul フォールバック
        sig = {"title": "韓国コスメ ポップアップ", "description_snippet": "", "kbz_info": {}}
        assert _guess_popup_area(sig) == "seoul"


class TestPrtimesSlugAscii:
    """タスク#27: PRTIMES popup の slug は releaseId 由来の ASCII(404 回避)。"""

    def test_prtimes_slug_is_ascii(self):
        sig = {
            "type": "popup",
            "title": "韓国最新ビューティー ポップアップ",
            "artist_keyword": "韓国コスメ",
            "source_url": "https://prtimes.jp/main/html/rd/p/000000063.000030872.html",
            "source_media": "PRTIMES",
        }
        _, _, slug = build_popup_article(sig)
        # multibyte が混ざらない(pretty permalink が解決できる)
        assert slug.isascii(), f"slug must be ASCII, got {slug!r}"
        assert "000000063-000030872" in slug


class TestEscHtml:
    def test_amp_escaped(self):
        assert "&amp;" in esc_html("Tom & Jerry")

    def test_lt_gt_escaped(self):
        result = esc_html("<script>")
        assert "<" not in result
        assert "&lt;" in result

    def test_double_quote_escaped(self):
        result = esc_html('say "hi"')
        assert '"' not in result
