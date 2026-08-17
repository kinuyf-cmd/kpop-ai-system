#!/usr/bin/env python3
"""tools/check_koreaherald_unblock.py のテスト。

守りたい仕様: 「壊れた見出し」と「修理後の正常な見出し」を区別できること。
区別できないと、いつまでも解除できない(正常な行を壊れ扱いする)か、
壊れた行が残っているのに解除可能と誤判定する。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.check_koreaherald_unblock import _looks_broken  # noqa: E402


def test_先頭に一覧の順位番号がある行は壊れている():
    assert _looks_broken("6 Twice’s Jeongyeon leaves JYP after 11 years, joins Varo Entertainment")
    assert _looks_broken("2 JYP terminates contract with Xdinary Heroes' Gunil")
    assert _looks_broken("4 Why was Blackpink's 10th anniversary so hard to pull off?")


def test_サイトUI文言が混ざる行は壊れている():
    assert _looks_broken("BTS’ Jungkook hits 1.2b mark on Spotify with Charlie Puth collab Most Read K-pop")
    assert _looks_broken("Weekender For these musicians, the sounds of Korea go beyond K-pop")
    assert _looks_broken("From the Scene How Olive Young's US store makes K-beauty interactive")


def test_80字で切断された行は壊れている():
    assert _looks_broken(
        "All 7 members participated in NCT127’s fan song NewJeans tops 300m Spotify strea")


def test_修理後の正常な見出しは壊れていない():
    """実HTMLから修理後に取得できた見出し(commit c1b5de0 の実測値)。"""
    for t in [
        "Stray Kids make Billboard history with 9th straight No. 1",
        "Piano-shaped pastries mark Big Bang's 20 years",
        "Katseye follows intuition, embraces freedom in 3rd EP",
        "Stray Kids’ latest EP clocks up 3.28m first-week sales",
        "JYP terminates contract with Xdinary Heroes' Gunil following allegations",
        "Fans revisit old BTS clips after V reveals hearing difficulties",
    ]:
        assert not _looks_broken(t), t


def test_長い正常見出しを壊れ扱いしない():
    """80字近いが句点で終わる/文として完結しているものは正常。"""
    t = "Ex-CN Blue member Lee Jong-hyun halts SNS return after one day following 8-year hiatus"
    assert not _looks_broken(t)


def test_空文字は壊れ扱いしない():
    assert not _looks_broken("")
