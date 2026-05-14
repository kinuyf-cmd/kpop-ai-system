"""auto-provision foundation の回帰テスト (2026-05-15)。

scope:
  - lib.pending_artist_queue: append/list/mark_resolved/dedup
  - pipeline.missing_artist_scanner: slug normalize
  - tools.approve_pending_artist: artist_master gate
"""
from __future__ import annotations
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, '/home/aiuser/kpop-ai-system')


@pytest.fixture
def tmp_queue(monkeypatch, tmp_path):
    """pending_artist_queue の QUEUE_PATH を tmp に差し替える。"""
    from lib import pending_artist_queue as q
    monkeypatch.setattr(q, 'QUEUE_PATH', tmp_path / 'pending.jsonl')
    return q


# === queue ===

def test_queue_append_basic(tmp_queue):
    assert tmp_queue.append('ATEEZ', 100, 'detected', missing_category=True, missing_profile=True)
    items = tmp_queue.list_pending()
    assert len(items) == 1
    assert items[0]['artist'] == 'ATEEZ'
    assert items[0]['missing_category'] is True
    assert items[0]['status'] == 'pending'


def test_queue_dedup_within_7d(tmp_queue):
    """同名 pending が 7 日以内にあれば再 append しない。"""
    assert tmp_queue.append('MAMAMOO', 100, 'r1', True, True)
    # 2 回目は dedup
    assert tmp_queue.append('MAMAMOO', 101, 'r2', True, True) is False
    items = tmp_queue.list_pending()
    assert len(items) == 1
    assert items[0]['first_seen_post_id'] == 100  # 1 回目が残る


def test_queue_resolved_allows_reappend(tmp_queue):
    """resolved marker 後の同名再 append は OK。"""
    tmp_queue.append('Red Velvet', 100, 'r1', True, True)
    tmp_queue.mark_resolved('Red Velvet', 'created')
    # list_pending は resolved を除外
    assert len(tmp_queue.list_pending()) == 0
    # 再 append は許可
    assert tmp_queue.append('Red Velvet', 200, 'r2', True, True)
    assert len(tmp_queue.list_pending()) == 1


def test_queue_list_dedup_per_artist(tmp_queue):
    """list_pending は artist ごとに最新 entry のみ返す。"""
    tmp_queue.append('A', 1, 'r1', True, True)
    tmp_queue.append('B', 2, 'r2', True, True)
    tmp_queue.mark_resolved('A', 'done')
    # A は resolved、B は pending
    items = tmp_queue.list_pending()
    artists = {e['artist'] for e in items}
    assert artists == {'B'}


# === scanner slug normalize ===

def test_scanner_wp_slug_to_profile_map():
    """frontend SLUG_NORMALIZE と整合 (black-pink/new-jeans/fromis-9/g-idle)。"""
    from pipeline.missing_artist_scanner import _WP_SLUG_TO_PROFILE
    assert _WP_SLUG_TO_PROFILE['black-pink'] == 'blackpink'
    assert _WP_SLUG_TO_PROFILE['new-jeans'] == 'newjeans'
    assert _WP_SLUG_TO_PROFILE['fromis-9'] == 'fromis9'
    assert _WP_SLUG_TO_PROFILE['g-idle'] == 'gidle'


def test_scanner_name_to_slug_handles_specials():
    """name_to_slug は記号付きグループも slug に落とせる。"""
    from pipeline.missing_artist_scanner import name_to_slug
    assert name_to_slug('(G)I-DLE') == 'gidle'
    assert name_to_slug('LE SSERAFIM') == 'le-sserafim'
    assert name_to_slug('MONSTA X') == 'monsta-x'
    assert name_to_slug('fromis_9') == 'fromis9'
    assert name_to_slug('BTS') == 'bts'


# === artist_master gate ===

def test_master_gate_known_artist():
    """ATEEZ は 2026-05-15 に artist_master へ追加済 → gate 通過。"""
    from tools.approve_pending_artist import is_in_master
    assert is_in_master('ATEEZ')
    assert is_in_master('BTS')
    assert is_in_master('aespa')


def test_master_gate_unknown_artist():
    """artist_master 未登録の名前は gate で refuse。"""
    from tools.approve_pending_artist import is_in_master
    assert not is_in_master('Random Unknown Group 12345')
    assert not is_in_master('')


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-v']))
