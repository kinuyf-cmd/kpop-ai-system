#!/usr/bin/env python3
"""draft化された記事のサムネ再生成→公開復帰のテスト。

背景 (2026-08-31):
  regenerate_thumbnail_wp.py 不在により 126件が draft のまま滞留していた。
  スクリプト復元後、既に止まっている分を遡って救済する必要がある。

安全側の制約:
  - DALL-E は1件ごとに実費が出るため **--apply が無ければ何もしない**。
  - 再生成が成功した記事だけを publish に戻す。失敗したら draft のまま
    (悪いサムネのまま公開してしまうのが最悪)。
  - 日次上限(50)があるので --limit で刻めること。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.recover_thumb_blocked as T  # noqa: E402


def test_dry_runでは再生成もpublishもしない(monkeypatch):
    calls = []
    monkeypatch.setattr(T, "blocked_ids", lambda: [1, 2, 3])
    monkeypatch.setattr(T, "regenerate", lambda pid: calls.append(("regen", pid)) or 0)
    monkeypatch.setattr(T, "set_publish", lambda pid: calls.append(("pub", pid)))
    T.run(apply=False, limit=0)
    assert calls == []


def test_再生成成功した記事だけpublishに戻す(monkeypatch):
    published = []
    monkeypatch.setattr(T, "blocked_ids", lambda: [10, 11])
    monkeypatch.setattr(T, "regenerate", lambda pid: 0 if pid == 10 else 1)
    monkeypatch.setattr(T, "set_publish", lambda pid: published.append(pid))
    T.run(apply=True, limit=0)
    assert published == [10], "失敗した記事をpublishしてはいけない"


def test_limitで件数を絞れる(monkeypatch):
    seen = []
    monkeypatch.setattr(T, "blocked_ids", lambda: [1, 2, 3, 4, 5])
    monkeypatch.setattr(T, "regenerate", lambda pid: seen.append(pid) or 1)
    monkeypatch.setattr(T, "set_publish", lambda pid: None)
    T.run(apply=True, limit=2)
    assert seen == [1, 2]


def test_除外IDはスキップする(monkeypatch):
    """非K-POP等、公開に戻すべきでない記事を明示除外できる。"""
    seen = []
    monkeypatch.setattr(T, "blocked_ids", lambda: [1, 2, 3])
    monkeypatch.setattr(T, "regenerate", lambda pid: seen.append(pid) or 1)
    monkeypatch.setattr(T, "set_publish", lambda pid: None)
    T.run(apply=True, limit=0, exclude={2})
    assert seen == [1, 3]


def test_公開済みと同名のdraftは対象から外す(monkeypatch):
    """復旧作業で重複記事を量産しない。

    実測(2026-08-31): 126件中7件が既存publishと同一タイトルだった。
    両方公開するとカニバリを起こす([[seo-rewrite-over-new-articles-check-existing]])。
    """
    monkeypatch.setattr(T, "_raw_blocked_draft_ids", lambda: [1, 2, 3])
    monkeypatch.setattr(T, "_dup_title_ids", lambda ids: {2})
    assert T.blocked_ids() == [1, 3]
