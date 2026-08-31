#!/usr/bin/env python3
"""tools/regenerate_thumbnail_wp.py のテスト。

背景 (2026-08-31 発見):
  post_publish_enricher はサムネ品質違反(dark_bg 等)を検出すると
  `tools/regenerate_thumbnail_wp.py <post_id>` を subprocess で呼び、
  失敗したら記事を **draft 化**する。
  ところが **このスクリプトは存在しなかった**(VPS事故で消失したまま)。
  呼び出しは必ず FileNotFoundError で失敗するため、再生成は 100% 失敗し、
  **126件が機械的に非公開にされていた**(122件が dark_bg)。
  日次13本публ公開に対し1〜3本、公開数の約15%の損失。

呼び出し側との契約(ここを壊すと再び静かに draft 化される):
  - 引数は post_id ひとつ
  - 成功時に stdout へ `featured_media: OK` を出す
    (enricher はこの**文字列一致**で成否を判定している)
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.regenerate_thumbnail_wp as R  # noqa: E402


def test_呼び出し側が期待する成功文字列を出す(capsys, monkeypatch):
    """enricher は 'featured_media: OK' を文字列一致で見ている。"""
    monkeypatch.setattr(R, "fetch_post", lambda pid: {"title": "IVEの新曲", "id": pid})
    monkeypatch.setattr(R, "generate", lambda title, out: True)
    monkeypatch.setattr(R, "upload_and_attach", lambda pid, path, alt: 999)
    rc = R.regenerate(18833)
    assert rc == 0
    assert "featured_media: OK" in capsys.readouterr().out


def test_生成失敗時は成功文字列を出さない(capsys, monkeypatch):
    """ここで誤って OK を出すと、悪いサムネのまま公開されてしまう。"""
    monkeypatch.setattr(R, "fetch_post", lambda pid: {"title": "x", "id": pid})
    monkeypatch.setattr(R, "generate", lambda title, out: False)
    rc = R.regenerate(1)
    out = capsys.readouterr().out
    assert rc != 0
    assert "featured_media: OK" not in out


def test_アップロード失敗時も成功文字列を出さない(capsys, monkeypatch):
    monkeypatch.setattr(R, "fetch_post", lambda pid: {"title": "x", "id": pid})
    monkeypatch.setattr(R, "generate", lambda title, out: True)
    monkeypatch.setattr(R, "upload_and_attach", lambda pid, path, alt: None)
    rc = R.regenerate(1)
    assert rc != 0
    assert "featured_media: OK" not in capsys.readouterr().out


def test_記事が取れない場合は失敗として扱う(capsys, monkeypatch):
    monkeypatch.setattr(R, "fetch_post", lambda pid: None)
    rc = R.regenerate(1)
    assert rc != 0
    assert "featured_media: OK" not in capsys.readouterr().out


def test_プロンプトに記事タイトルが入る():
    p = R.build_prompt("IVEガウルが新曲を発表")
    assert "IVEガウルが新曲を発表" in p


def test_プロンプトは明るい画を要求する():
    """再生成の理由の97%が dark_bg。暗い画を作り直しても弾かれるだけ。"""
    p = R.build_prompt("x").lower()
    assert "bright" in p or "well-lit" in p


def test_プロンプトは文字入りを禁じる():
    """text_band 違反の再発を防ぐ。"""
    p = R.build_prompt("x").lower()
    assert "no text" in p


def test_既知グループ名をヒントとして拾う():
    assert R.artist_hint("BLACKPINKの新曲がヒット") == "BLACKPINK"
    assert R.artist_hint("誰も知らない話") is None


def test_CLIは引数なしなら異常終了する():
    with pytest.raises(SystemExit):
        R.main([])
