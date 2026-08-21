#!/usr/bin/env python3
"""記事本文から「読者が行動を変えられる具体」を抜き出す。

背景(2026-08-21): ネタ元(trend_signals)の見出しは具体を 1/24 しか含まず、
具体ゲートだけを足すと自動投稿が 0% になって止まる。
一方で自社記事の本文(特にポップアップ/イベント)には会場・会期・営業時間が
揃っている。だから「弾く」だけでなく「載せる」側を用意する。
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from lib.x_traffic_picker import extract_concrete_facts

POPUP_BODY = (
    "K-POP のポップアップ・期間限定イベント情報。開催地・期間・営業時間などの詳細は"
    "下記の開催情報をご確認ください。\n 開催概要 \n 会場 「D’PARTMENT」（ディパートメント） \n"
    " 開催期間 2026年7月4日（土）～8月16日（日） \n 営業時間 11:00～20:00 "
    "※営業時間は変更になる場合があります。\n 出典: PRTIMES"
)


class TestExtract:
    def test_picks_venue(self):
        f = extract_concrete_facts(POPUP_BODY)
        assert any("D’PARTMENT" in v for v in f.get("venue", []))

    def test_picks_period(self):
        f = extract_concrete_facts(POPUP_BODY)
        assert f.get("period")

    def test_picks_hours(self):
        f = extract_concrete_facts(POPUP_BODY)
        assert any("11:00" in h for h in f.get("hours", []))

    def test_empty_body_returns_empty(self):
        assert extract_concrete_facts("") == {}

    def test_body_without_facts_returns_empty(self):
        assert extract_concrete_facts("新曲がとても良かったです。とても感動しました。") == {}


class TestRendersIntoConcreteLine:
    """抜いた具体は、そのまま本文に足せば具体ゲートを通る形になること。"""

    def test_line_passes_concrete_gate(self):
        from lib.x_traffic_picker import concrete_line, has_concrete_info
        line = concrete_line(extract_concrete_facts(POPUP_BODY))
        assert line
        assert has_concrete_info(line)["ok"]

    def test_line_is_short_enough_for_x(self):
        from lib.x_traffic_picker import concrete_line
        line = concrete_line(extract_concrete_facts(POPUP_BODY))
        assert len(line) <= 80, line

    def test_no_facts_gives_empty_line(self):
        from lib.x_traffic_picker import concrete_line
        assert concrete_line({}) == ""


class TestRejectsUselessVenues:
    """実データで出た誤抽出。会場として役に立たない値は拾わない。"""

    def test_country_alone_is_not_a_venue(self):
        f = extract_concrete_facts("会場 韓国 \n 開催期間 2026/08/08〜2026/08/20")
        assert "韓国" not in f.get("venue", [])

    def test_sentence_fragment_is_not_a_venue(self):
        """『〜の場所でもあります。』のような散文はラベルではない。"""
        f = extract_concrete_facts("ソウルで人気の場所でもあります。行ってみたいですね。")
        assert not f.get("venue")

    def test_real_venue_still_extracted(self):
        f = extract_concrete_facts("会場 伊勢丹新宿店メンズ館1階 \n 営業時間 10:00 ～ 20:00")
        assert any("伊勢丹" in v for v in f.get("venue", []))
