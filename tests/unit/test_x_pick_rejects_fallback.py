#!/usr/bin/env python3
"""フォールバック(見出しの丸写し)は投稿しない。

build_hook() は LLM が3回とも通らなかったとき、出来事をそのまま短く返す
フォールバックを持つ。これは感想が乗らないので型Aを満たさないが、見出しに
日付が入っていると具体ゲートだけは通ってしまい、bot臭い丸写しが出る
(実生成で確認: 「…（公式）SEVENTEEN バーノン、本日（8/20）入隊…」)。
pick 側で型Aと具体の両方を必須にする。
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from lib.x_traffic_picker import check_hook_structure_type_a, has_concrete_info

HEADLINE_DUMP = (
    "NCT DREAM、メンバー全員がSMと再契約を締結「無限の可能性がさらに輝くよう共に歩む」"
    "（公式）SEVENTEEN バーノン、本日（8/20）入隊…"
)


def test_headline_dump_passes_concrete_but_fails_type_a():
    """具体だけでは足りないことを示す(このケースの再現)。"""
    assert has_concrete_info(HEADLINE_DUMP)["ok"]
    assert not check_hook_structure_type_a(HEADLINE_DUMP)["ok"]


def test_both_gates_reject_headline_dump():
    ok = (check_hook_structure_type_a(HEADLINE_DUMP)["ok"]
          and has_concrete_info(HEADLINE_DUMP)["ok"])
    assert not ok


def test_good_hook_passes_both():
    t = ("ファンミが8/23に生中継されるの、これは見逃せないなぁ…"
         "日本語字幕付きで、11:00〜の回もあるみたい")
    assert check_hook_structure_type_a(t)["ok"]
    assert has_concrete_info(t)["ok"]
