#!/usr/bin/env python3
"""pipeline/angle_article_generator.py のテスト。

背景 (2026-08-18):
  owner方針「しばらくは幅広にいろんな角度から記事を作成し、データを集める」。

  実装の前提として重大な発見があった: 速報検知が24-72h後の深掘り用に
  focus_themes へテーマを注入していたが、**それを消費する
  feature_article_generator は実在しなかった**(コメント上の想定だけ)。
  結果、295件が滞留し「速報の深掘り」以外は1本も出ていなかった。

  本生成器がその消費側を担い、lib/article_angles.py が出す多角度テーマを
  記事にする。どの角度が効いたかを後から集計するため、angle を必ず記録する。
"""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.angle_article_generator import (pick_theme, load_angle_themes,  # noqa: E402
                                              already_covered, DAILY_CAP)


def _theme(key="ost", topic="『恋は飴模様』の主題歌・OST", days_ahead=30):
    return {
        "topic": topic,
        "hint": "テスト用",
        "category_suggest": "音楽",
        "added_at": datetime.now().strftime("%Y-%m-%d"),
        "source": f"angle:{key}",
        "buzz_score": 8.0,
        "expires_at": (datetime.now() + timedelta(days=days_ahead)).strftime("%Y-%m-%d"),
    }


def _write(tmp_path, themes):
    p = tmp_path / "auto_directives.json"
    p.write_text(json.dumps({"focus_themes": themes}, ensure_ascii=False), encoding="utf-8")
    return p


def test_angle由来のテーマだけを拾う(tmp_path):
    """既存の breaking_followup(295件)を巻き込まない。役割が違う。"""
    p = _write(tmp_path, [
        _theme("ost"),
        {"topic": "BTS速報の深掘り: X", "source": "breaking_followup",
         "expires_at": "2099-01-01", "hint": "", "category_suggest": "深掘り",
         "added_at": "2026-08-18", "buzz_score": 12.0},
    ])
    got = load_angle_themes(path=p)
    assert len(got) == 1
    assert got[0]["source"] == "angle:ost"


def test_期限切れのテーマは拾わない(tmp_path):
    p = _write(tmp_path, [_theme("ost", days_ahead=-1)])
    assert load_angle_themes(path=p) == []


def test_既に書いた角度は再度書かない(tmp_path):
    """同じ作品×同じ角度を二重に書かない(カニバリ防止)。"""
    log = tmp_path / "angle_articles.jsonl"
    log.write_text(json.dumps({
        "ts": datetime.now().isoformat(), "topic": "『恋は飴模様』の主題歌・OST",
        "angle": "ost", "status": "publish"}, ensure_ascii=False) + "\n", encoding="utf-8")
    assert already_covered("『恋は飴模様』の主題歌・OST", log_path=log)
    assert not already_covered("『恋は飴模様』のロケ地・聖地巡礼", log_path=log)


def test_失敗した記録は再挑戦を妨げない(tmp_path):
    """status=skip は『書いた』ではない。dedupを汚染すると二度と書けなくなる
    (openai-credit-exhausted-publish-halt と同じ轍)。"""
    log = tmp_path / "angle_articles.jsonl"
    log.write_text(json.dumps({
        "ts": datetime.now().isoformat(), "topic": "『恋は飴模様』の主題歌・OST",
        "angle": "ost", "status": "skip", "reason": "gate_fail"},
        ensure_ascii=False) + "\n", encoding="utf-8")
    assert not already_covered("『恋は飴模様』の主題歌・OST", log_path=log)


def test_角度が偏らないよう選ぶ(tmp_path):
    """探索が目的なので、同じ角度ばかり消費しない。
    直近で書いていない角度を優先する。"""
    p = _write(tmp_path, [_theme("ost", topic="A の主題歌・OST"),
                          _theme("location", topic="B のロケ地・聖地巡礼")])
    log = tmp_path / "angle_articles.jsonl"
    log.write_text("\n".join(json.dumps({
        "ts": datetime.now().isoformat(), "topic": f"過去{i} の主題歌・OST",
        "angle": "ost", "status": "publish"}, ensure_ascii=False)
        for i in range(3)), encoding="utf-8")
    got = pick_theme(path=p, log_path=log)
    assert got and got["source"] == "angle:location", got


def test_出せるテーマが無ければNone(tmp_path):
    p = _write(tmp_path, [])
    assert pick_theme(path=p, log_path=tmp_path / "x.jsonl") is None


def test_日次上限が控えめ():
    """探索フェーズでも量産はしない。品質と可視性のリスクを避ける。"""
    assert 1 <= DAILY_CAP <= 3
