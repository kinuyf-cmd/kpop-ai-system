#!/usr/bin/env python3
"""lib/article_angles.py のテスト — 探索フェーズ用の多角度テーマ生成。

背景 (2026-08-18 実測):
  owner方針「しばらくは幅広にいろんな角度から記事を作成し、データを集める」。

  現状を測ると角度が1つしかなかった:
    - config/auto_directives.json の focus_themes 295件が**全て**
      source='breaking_followup' / category_suggest='深掘り'
    - 直近14日の公開223本の切り口分類でも、OST/ロケ地/文化解説/相関図は**0本**
    - つまり「速報の深掘り」だけを回しており、探索になっていない

  一方、切り口別のCTR実測(28d)では明確な差がある:
    主題歌/OST  CTR 8.33%(imp156・記事が少ないだけ)
    相関図      CTR 1.59%(imp9001・競合多数)
    声優/吹替   CTR 1.78%(imp5730・実写韓ドラマは特に弱い 1.34%)
    ロケ地      pos13〜44 = **記事が無くて拾えていない**
  データを集めるには、まず角度を出し分ける必要がある。

  聖地巡礼(ロケ地)は owner 指摘のとおり**放映後に効く**ため、配信直後ではなく
  期間を空けて投入する。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.article_angles import (ANGLES, build_angle_themes,  # noqa: E402
                                pick_angles_for)


def test_角度が複数定義されている():
    """探索フェーズなので、1つの型に偏らせない。"""
    assert len(ANGLES) >= 6


def test_OSTとロケ地と文化の角度がある():
    keys = {a["key"] for a in ANGLES}
    assert {"ost", "location", "culture"} <= keys


def test_角度ごとにcategory_suggestが異なる():
    """全部『深掘り』になっていた現状の再発防止。"""
    cats = {a["category_suggest"] for a in ANGLES}
    assert len(cats) >= 4


def test_ドラマ作品には作品向けの角度が出る():
    got = pick_angles_for(title="『恋は飴模様』Netflixで配信開始", artist="", is_drama=True)
    keys = {a["key"] for a in got}
    assert "ost" in keys


def test_ロケ地は放映直後には出さない():
    """owner指摘: 聖地巡礼は放映後に効いてくる。配信直後に出しても早すぎる。"""
    now = pick_angles_for(title="『恋は飴模様』本日配信開始", artist="", is_drama=True,
                          days_since_release=0)
    later = pick_angles_for(title="『恋は飴模様』", artist="", is_drama=True,
                            days_since_release=30)
    assert "location" not in {a["key"] for a in now}
    assert "location" in {a["key"] for a in later}


def test_アーティスト単体にはドラマ向け角度を出さない():
    got = pick_angles_for(title="BTS ジミン、ソロ曲を発表", artist="BTS", is_drama=False)
    keys = {a["key"] for a in got}
    assert "location" not in keys


def test_テーマがfocus_themesの形式で返る():
    themes = build_angle_themes(title="『恋は飴模様』配信開始", artist="チョン・ヘイン",
                                is_drama=True, days_since_release=30)
    assert themes
    for t in themes:
        for k in ("topic", "hint", "category_suggest", "added_at",
                  "source", "buzz_score", "expires_at"):
            assert k in t, k
        # 探索由来と分かるようにする(既存のbreaking_followupと区別)
        assert t["source"].startswith("angle:")


def test_同じ作品で角度ごとに別テーマになる():
    themes = build_angle_themes(title="『恋は飴模様』配信開始", artist="",
                                is_drama=True, days_since_release=30)
    topics = [t["topic"] for t in themes]
    assert len(topics) == len(set(topics))


def test_期限は角度ごとの寿命に従う():
    """速報の深掘りは3日で腐るが、OSTやロケ地は腐らない。"""
    themes = build_angle_themes(title="『恋は飴模様』", artist="",
                                is_drama=True, days_since_release=30)
    by = {t["source"]: t for t in themes}
    loc = by.get("angle:location")
    assert loc and loc["expires_at"] > loc["added_at"]


def test_作品名だけを抜き出す():
    """『恋は飴模様』Netflixで配信開始 → 『恋は飴模様』。
    ニュース見出しをそのまま使うと「配信開始の主題歌・OST」と冗長になる。"""
    themes = build_angle_themes(title="『恋は飴模様』Netflixで配信開始", artist="",
                                is_drama=True)
    assert any(t["topic"] == "『恋は飴模様』の主題歌・OST" for t in themes), \
        [t["topic"] for t in themes]


def test_鉤括弧が無い見出しでも短く整える():
    themes = build_angle_themes(title="鉄槌教師、Netflixで全10話配信スタート", artist="",
                                is_drama=True)
    topics = [t["topic"] for t in themes]
    assert all(len(t) <= 30 for t in topics), topics
