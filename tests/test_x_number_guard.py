#!/usr/bin/env python3
"""生成本文の数値が元の出来事と矛盾しないかを検査するガードのテスト。

背景 (2026-08-17):
  プロンプトで「原文に無い数字を書くな」「million=100万, billion=10億」と
  指示しても、実測で誤りが残った:
    - 「300 Million Spotify Streams」→「300万回再生」(正しくは3億)
    - 「1.9 Billion Views」→「1.9億再生」(正しくは19億)
  桁違いの数字は誤情報として最も分かりやすく信用を損なうため、
  プロンプトではなくコードで検査して弾く。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.x_persona_voice import _numbers_consistent  # noqa: E402


def test_millionを3億と正しく訳したら通る():
    assert _numbers_consistent("LE SSERAFIM の曲が3億回再生を突破したらしい",
                               "Passes 300 Million Spotify Streams")


def test_millionを300万と誤訳したら弾く():
    assert not _numbers_consistent("LE SSERAFIM の曲が300万回再生を突破したらしい",
                                   "Passes 300 Million Spotify Streams")


def test_billionを19億と正しく訳したら通る():
    assert _numbers_consistent("Dynamite が19億回再生", "Surpasses 1.9 Billion Views")


def test_billionを1_9億と誤訳したら弾く():
    assert not _numbers_consistent("Dynamite が1.9億回再生", "Surpasses 1.9 Billion Views")


def test_原文の数字をそのまま使えば通る():
    assert _numbers_consistent("UKチャートで21週ランクインってすごい",
                               "To Spend 21 Weeks On UK's Official Albums Chart")


def test_原文に無い数字を出したら弾く():
    """「デビューから2年半」のように、出来事に無い数字の創作を検出する。"""
    assert not _numbers_consistent("デビューから2年半でこの噂はびっくり",
                                   "Giselle Sparks Rumors She's Leaving SM Entertainment")


def test_数字を使わなければ通る():
    assert _numbers_consistent("あの噂ほんとにびっくりした",
                               "Giselle Sparks Rumors She's Leaving SM Entertainment")


def test_年号や日付など一般的な数字は許容():
    """「2026年」「8月22日」のような日付表現は誤情報になりにくく、
    出来事の日付表記ゆれで弾きすぎないようにする。"""
    assert _numbers_consistent("8月22日から配信って楽しみ",
                               "aespa、日本初の冠バラエティ番組が8月22日より配信")


def test_元の出来事が無ければ検査しない():
    assert _numbers_consistent("なんでも書ける", "")


# ─── 曲名・作品名の捏造検出 ────────────────────────────────────────────
from lib.x_persona_voice import _titles_consistent  # noqa: E402


def test_出来事にある曲名は使える():
    assert _titles_consistent('「Eve, Psyche and Bluebeard\'s Wife」が3億回再生',
                              'LE SSERAFIM\'s "Eve, Psyche and Bluebeard\'s Wife" Passes 300 Million')


def test_出来事に無い曲名は弾く():
    """「Next Level」のように、記憶から補った別曲の言及を検出する。"""
    assert not _titles_consistent('Giselleの退所報道、「Next Level」の頃が懐かしい',
                                  "Giselle Sparks Rumors She's Leaving SM Entertainment")


def test_曲名を出さなければ通る():
    assert _titles_consistent('Giselleの退所報道、ちょっと驚いた',
                              "Giselle Sparks Rumors She's Leaving SM Entertainment")


def test_番組名も出来事にあれば通る():
    assert _titles_consistent('「Music Core」を欠席したらしい',
                              'Han Sits Out "Music Core" Live Broadcast')


# ─── ハングル残留の検出 ────────────────────────────────────────────────
from lib.x_persona_voice import _has_hangul  # noqa: E402


def test_ハングルが残っていたら弾く():
    """読者は日本語話者。元記事が韓国語でも、本文にハングルを残さない。
    実測で「NCT 런쥔が…「위로와 힐링」について語った」が生成された。"""
    assert _has_hangul("NCT 런쥔がTMEA 2026で「위로와 힐링」について語った")


def test_日本語だけなら通る():
    assert not _has_hangul("NCT 127が10周年で新シリーズを予告した")
