#!/usr/bin/env python3
"""具体つきネタ元(開催中/直近のイベント記事)を供給する。

2026-08-21 実測: トレンド連動でマッチするのはニュース記事で、会場・会期の
構造化情報を持たない(6/6で具体抽出ゼロ)。会場・会期を持つのはポップアップ/
イベント記事の側。具体ゲートを通す投稿を出すには、この側をネタ元にする。
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from lib.x_traffic_picker import is_currently_open, upcoming_window


class TestPeriodParsing:
    """会期文字列から「いま行けるか」を判定する。"""

    def test_open_now(self):
        assert is_currently_open("2026年8月19日（水）～8月30日（日）", today="2026-08-21")

    def test_already_closed(self):
        assert not is_currently_open("2026年7月4日（土）～8月16日（日）", today="2026-08-21")

    def test_not_started_yet(self):
        assert not is_currently_open("2026年8月26日（水）〜9月1日（火）", today="2026-08-21")

    def test_slash_format(self):
        assert is_currently_open("2026/08/15〜2026/08/31", today="2026-08-21")

    def test_unparsable_is_not_open(self):
        assert not is_currently_open("近日公開予定", today="2026-08-21")

    def test_empty_is_not_open(self):
        assert not is_currently_open("", today="2026-08-21")


class TestUpcomingWindow:
    """開始が近いものは「もうすぐ始まる」として使える。"""

    def test_starts_within_window(self):
        assert upcoming_window("2026年8月26日（水）〜9月1日（火）", today="2026-08-21", days=7)

    def test_starts_too_far(self):
        assert not upcoming_window("2026年10月1日（水）〜10月9日（木）", today="2026-08-21", days=7)

    def test_already_open_is_not_upcoming(self):
        assert not upcoming_window("2026年8月19日（水）～8月30日（日）", today="2026-08-21", days=7)


class TestPickEventPost:
    """開催中のイベント記事から、具体を含む投稿を組み立てられること。"""

    def test_builds_post_with_concrete(self, monkeypatch):
        import lib.x_traffic_picker as m
        from lib.x_traffic_picker import has_concrete_info

        body = ("開催概要 \n 会場 「渋谷PARCO」 \n"
                " 開催期間 2026年8月19日（水）～8月30日（日） \n"
                " 営業時間 11:00～21:00 \n 出典: PRTIMES")
        monkeypatch.setattr(m, "search_event_articles", lambda **kw: [
            {"post_id": 1, "title": "TWS ポップアップ", "url": "https://x.test/a",
             "artist": "TWS"}])
        monkeypatch.setattr(m, "fetch_body", lambda pid: body)

        post = m.pick_event_post(today="2026-08-21")
        assert post is not None
        assert has_concrete_info(post["hook"])["ok"], post["hook"]
        assert post["url"] == "https://x.test/a"

    def test_skips_closed_events(self, monkeypatch):
        import lib.x_traffic_picker as m
        body = ("会場 「渋谷PARCO」 \n 開催期間 2026年7月1日（火）～7月10日（木） \n"
                " 営業時間 11:00～21:00")
        monkeypatch.setattr(m, "search_event_articles", lambda **kw: [
            {"post_id": 1, "title": "終わったポップアップ", "url": "https://x.test/a",
             "artist": "TWS"}])
        monkeypatch.setattr(m, "fetch_body", lambda pid: body)
        assert m.pick_event_post(today="2026-08-21") is None

    def test_returns_none_when_no_articles(self, monkeypatch):
        import lib.x_traffic_picker as m
        monkeypatch.setattr(m, "search_event_articles", lambda **kw: [])
        assert m.pick_event_post(today="2026-08-21") is None


class TestOnlyReachableEvents:
    """日本の読者が行けないイベントは出さない(実データで大半が韓国開催だった)。"""

    def test_korean_venue_is_rejected(self, monkeypatch):
        import lib.x_traffic_picker as m
        body = ("開催概要 会場 韓国 중구 開催期間 2026/08/22〜2026/08/23 出典: pops-in")
        monkeypatch.setattr(m, "search_event_articles", lambda **kw: [
            {"post_id": 1, "title": "YENA ENCORE LIVE", "url": "https://x.test/a"}])
        monkeypatch.setattr(m, "fetch_body", lambda pid: body)
        assert m.pick_event_post(today="2026-08-21") is None

    def test_hangul_in_venue_is_rejected(self, monkeypatch):
        import lib.x_traffic_picker as m
        body = "会場 영등포구 開催期間 2026/08/21〜2026/09/02"
        monkeypatch.setattr(m, "search_event_articles", lambda **kw: [
            {"post_id": 1, "title": "ANITEEZ POPUP", "url": "https://x.test/a"}])
        monkeypatch.setattr(m, "fetch_body", lambda pid: body)
        assert m.pick_event_post(today="2026-08-21") is None

    def test_japanese_venue_passes(self, monkeypatch):
        import lib.x_traffic_picker as m
        body = ("会場 「渋谷PARCO」 開催期間 2026年8月19日（水）～8月30日（日） "
                "営業時間 11:00～21:00")
        monkeypatch.setattr(m, "search_event_articles", lambda **kw: [
            {"post_id": 1, "title": "TWS ポップアップ", "url": "https://x.test/a"}])
        monkeypatch.setattr(m, "fetch_body", lambda pid: body)
        assert m.pick_event_post(today="2026-08-21") is not None
