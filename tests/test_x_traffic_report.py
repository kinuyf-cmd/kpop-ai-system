#!/usr/bin/env python3
"""tools/x_traffic_report.py のテスト(GA4 を叩かない純ロジック部分)。

守りたい仕様:
  - X 由来の判定に t.co / x.com / twitter.com を含める
  - 自社投稿URLの抽出が、投稿ログのテキストから正しくパスを取れる
    (自社投稿由来と他者シェアを切り分けるための土台。ベースライン実測では
     37セッション中36件が他者シェアで、合計値だけ見ると施策効果を誤認する)
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.x_traffic_report import X_SOURCES, LAG_DAYS, posted_urls  # noqa: E402


def test_X由来の判定にtcoを含む():
    assert "t.co" in X_SOURCES
    assert "x.com" in X_SOURCES
    assert "twitter.com" in X_SOURCES


def test_GA4の確定待ちを3日取る():
    """GA4 は確定に24〜48h。『昨日』を見ると途中値を掴む
    (memory: ga4-must-wait-for-data-finalization)。"""
    assert LAG_DAYS >= 2


def test_投稿ログからURLパスを抽出する(tmp_path, monkeypatch):
    log = tmp_path / "logs"
    log.mkdir()
    (log / "x_posts.jsonl").write_text("\n".join([
        json.dumps({"ts": "2026-08-17T12:00", "status": "ok",
                    "text": "本文だけ URLなし"}, ensure_ascii=False),
        json.dumps({"ts": "2026-08-17T12:01", "status": "ok",
                    "text": "続き\nhttps://www.kpopjournal.tokyo/skz-billboard/"},
                   ensure_ascii=False),
    ]), encoding="utf-8")
    import tools.x_traffic_report as m
    monkeypatch.setattr(m, "BASE", tmp_path)
    got = m.posted_urls()
    assert "/skz-billboard" in got


def test_投稿ログが無くても落ちない(tmp_path, monkeypatch):
    import tools.x_traffic_report as m
    monkeypatch.setattr(m, "BASE", tmp_path)
    assert m.posted_urls() == set()
