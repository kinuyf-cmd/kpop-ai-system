"""表記ガード(lib/notation_guard.py)の回帰テスト。実例は2026-11-18の誤記。"""
from lib.notation_guard import check_notation

ND = {"ペク・ジホン": "백지헌", "キム・スヒョン": "김수현"}


def _types(issues):
    return [i["type"] for i in issues]


def test_hybrid_kanji_katakana_blocks():
    iss = check_notation("ILLIT「体ポハゲッソ」米ビルボードで22位", "<p>新曲「体ポハゲッソ(Remixes)」</p>", name_dict=ND)
    assert _types(iss) == ["kanji_katakana_hybrid"]


def test_normal_quotes_pass():
    body = "<p>「新ジャンル」ではなく「逮捕するよ」「You're Under Arrest」「神曲」「超カワイイ」</p>"
    assert check_notation("ILLIT新曲", body, name_dict=ND) == []


def test_source_title_name_must_use_dict_notation():
    iss = check_notation("fromis_9ペク・ジヘン、夢幻的ビジュアル", "<p>ペク・ジヘンが写真を公開</p>",
                         source_title="프로미스나인 백지헌, 카메라에 담은 몽환 비주얼", name_dict=ND)
    assert "dict_notation_mismatch" in _types(iss)


def test_source_title_name_correct_passes():
    iss = check_notation("fromis_9ペク・ジホン、夢幻的ビジュアル", "<p>ペク・ジホンが写真を公開</p>",
                         source_title="프로미스나인 백지헌, 카메라에 담은 몽환 비주얼", name_dict=ND)
    assert iss == []


def test_one_char_different_person_not_flagged_without_source():
    # 韓国人名は1字違いで普通に別人(実測で誤検知9/9)。元記事に無い限り照合しない
    assert check_notation("キム・ダヒョン出演", "<p>キム・ダヒョンが登場</p>", name_dict=ND) == []


def test_inconsistent_name_in_same_article():
    iss = check_notation("t", "<p>ペク・ジヘンが…</p><p>ペク・ジホンは…</p>", name_dict={})
    assert _types(iss) == ["name_inconsistency"]


def test_gate_blocks_hybrid():
    from lib.pre_publish_gate import BLOCK_TYPES
    assert {"kanji_katakana_hybrid", "dict_notation_mismatch", "name_inconsistency"} <= BLOCK_TYPES
