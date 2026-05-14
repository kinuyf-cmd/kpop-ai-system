"""Pending-artist queue (auto-provision の人間承認 gate)。

publish 済記事に出現する artist で:
  - WP category (parent=26) が無い
  - config/artist_profiles/{slug}.json が無い

を検出して logs/pending_artists.jsonl に append-only で記録する。
tools/approve_pending_artist.py で人間が承認したら、WP category 作成 +
profile_wiki_builder.build_one() を実行 + queue を resolved に marker append。

dedup: 同じ artist の pending entry が 7 日以内にあれば重複 append しない。
"""
from __future__ import annotations
import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

JST = timezone(timedelta(hours=9))
QUEUE_PATH = Path('/home/aiuser/kpop-ai-system/logs/pending_artists.jsonl')


def _load_entries() -> list[dict]:
    if not QUEUE_PATH.exists():
        return []
    out = []
    with open(QUEUE_PATH, encoding='utf-8') as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out


def append(artist_name: str, source_post_id: int, reason: str,
           missing_category: bool = False, missing_profile: bool = False) -> bool:
    """artist を queue に追加。同名 pending が 7 日以内にあれば skip し False を返す。"""
    QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    cutoff = datetime.now(JST) - timedelta(days=7)
    name_norm = artist_name.strip().lower()

    # 同名 active pending を探す
    for e in reversed(_load_entries()):
        if e.get('artist', '').strip().lower() != name_norm:
            continue
        if e.get('status') == 'resolved':
            # resolved 後の再 queue は OK
            break
        try:
            ts = datetime.fromisoformat(e['ts'])
        except Exception:
            continue
        if ts >= cutoff:
            return False  # 既に queued
        break

    entry = {
        'artist': artist_name,
        'first_seen_post_id': int(source_post_id),
        'reason': reason,
        'missing_category': bool(missing_category),
        'missing_profile': bool(missing_profile),
        'ts': datetime.now(JST).isoformat(timespec='seconds'),
        'status': 'pending',
    }
    with open(QUEUE_PATH, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    return True


def list_pending() -> list[dict]:
    """resolved されていない pending entries (latest entry per artist)。"""
    by_artist: dict[str, dict] = {}
    for e in _load_entries():
        name = e.get('artist', '').strip().lower()
        if not name:
            continue
        by_artist[name] = e  # 後勝ち: 最新 entry が active state
    return [e for e in by_artist.values() if e.get('status') == 'pending']


def mark_resolved(artist_name: str, note: str) -> None:
    """resolved marker を append。"""
    entry = {
        'artist': artist_name,
        'status': 'resolved',
        'note': note,
        'ts': datetime.now(JST).isoformat(timespec='seconds'),
    }
    QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(QUEUE_PATH, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')
