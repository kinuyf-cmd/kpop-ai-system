"""速報からの導線(2026-10-14)の回帰テスト。

- 速報タイトルを語の途中・括弧の内側で切らない
- 同じアーティストの定番記事へ案内する(期限切れ・自分自身は出さない)
- タグ名をハングルでなく日本での表記(英字)にする
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lib.unified_publisher import (  # noqa: E402
    _artist_hub_block, _tag_name_for_artist, _truncate_title)


def test_truncate_title_cuts_at_delimiter():
    t = _truncate_title('SEVENTEEN、ATEEZ、IVE、NCT WISH、aespa、そしてILLITが年末授賞式に出演決定へ', 42)
    assert t == 'SEVENTEEN、ATEEZ、IVE、NCT WISH、aespa'


def test_truncate_title_does_not_leave_open_bracket():
    t = _truncate_title('ATEEZ・LE SSERAFIM・RIIZE参加「2026 Kワールドドリームアワーズ」ラインナップ', 42)
    assert '「' not in t and len(t) <= 42


def test_truncate_title_keeps_short_title():
    assert _truncate_title('BTS新曲がSpotify1位', 42) == 'BTS新曲がSpotify1位'


def test_hub_block_for_bts_links_relationship_map():
    h = _artist_hub_block('방탄소년단', today='2026-10-14')
    assert 'bts-relationship-map-2026' in h and 'あわせて読みたい' in h


def test_hub_block_prefers_upcoming_event_and_drops_expired():
    h = _artist_hub_block('ATEEZ', today='2026-10-14')
    assert 'kgma-2026' in h and 'mma-2026' in h
    later = _artist_hub_block('ATEEZ', today='2026-11-20')
    assert 'kgma-2026' not in later and 'aaa-2026' in later


def test_hub_block_skips_self_and_unknown_artist():
    assert 'bts-relationship-map-2026' not in _artist_hub_block('BTS', slug='bts-relationship-map-2026')
    assert _artist_hub_block('임영웅') == ''


def test_tag_name_normalized_to_japanese_notation():
    assert _tag_name_for_artist('방탄소년단') == 'BTS'
    assert _tag_name_for_artist('아이유') == 'IU'
    assert _tag_name_for_artist('BTS') == 'BTS'


def test_tag_name_skips_ambiguous_common_words():
    assert _tag_name_for_artist('있지') == ''
    assert _tag_name_for_artist('화사') == ''
