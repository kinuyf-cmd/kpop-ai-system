"""X投稿に具体情報(日時/数値/固有名詞的事実)が入っているかのゲート。

2026-08-28実測(Phase1以降21投稿):
  曖昧な感想型  9件: 平均imp 248 / 平均eng 1.44
  情報型       12件: 平均imp 465 / 平均eng 1.75
エンゲージ上位は全て「読者が得をする具体情報」だった(生中継の日時と字幕の有無、
ノミネート発表、キャンペーン)。疑問符の有無はエンゲージと無相関(上位5件中4件が疑問符なし)。
"""
import pytest

from lib.x_persona_voice import _lacks_concrete_info


@pytest.mark.parametrize("text", [
    "TWICEの最近のパフォーマンス、なんかもう何回見ても飽きない気がするんだけど、どうなってんだろう。",
    "BLACKPINKの空港ファッション、最近のスタイリングはちょっとカジュアルすぎな気がするけど。",
    "IVEって、最近の曲がどんどん進化してる気がするけど、やっぱり初期のあの感じも恋しいなぁ。",
    "ILLITの新しいパフォーマンス、なんかいつもよりキレがある気がするんだけど。",
    "SEVENTEENのパフォーマンス見るたびに、ほんとに彼らが好きすぎて涙腺ヤバい…",
])
def test_vague_impression_is_rejected(text):
    """中身のない感想文は弾く。"""
    assert _lacks_concrete_info(text) is True


@pytest.mark.parametrize("text", [
    "NCT DREAM 10周年ファンミが8/23に韓国から生中継されます。日本語字幕付き",
    "サマソニ初日、K-POP勢が濃い。BABYMONSTER 14:05〜(MARINE)",
    "BABYMONSTERは今日14:05から配信あり。でもJENNIEは配信タイムテーブルに入ってません",
    "JTBCのドラマ「アパート」が2026年08月15日の最終回で自己最高視聴率7.7%を記録",
    "BTSからBLACKPINK、CORTISまで「2026 MTV VMA」ノミネート発表",
    "グッズ売場=キャッシュレスのみ(現金不可)。飲食=電子マネーのみ",
    "LE SSERAFIMが2ndシングルアルバム「Made My Night」を発表",
])
def test_concrete_info_passes(text):
    """日時・数値・作品名など具体情報があれば通す。"""
    assert _lacks_concrete_info(text) is False
