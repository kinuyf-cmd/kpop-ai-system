"""find_duplicate_published の単体テスト(2026-06-16)
公開済み記事との重複判定を生成前/生成後で共有する抽出関数。
"""
import json
from unittest.mock import patch, MagicMock
from lib.pre_publish_gate import find_duplicate_published


def _fake_resp(payload):
    """urlopen のコンテキストマネージャ戻り値を模す。"""
    m = MagicMock()
    m.read.return_value = json.dumps(payload).encode()
    m.__enter__.return_value = m
    m.__exit__.return_value = False
    return m


def test_returns_dup_when_proper_nouns_overlap():
    existing = [{"id": 999, "title": {"rendered": "aespa Winter 新ビジュアル公開"}}]
    with patch("urllib.request.urlopen", return_value=_fake_resp(existing)):
        dup = find_duplicate_published(["aespa", "Winter", "ビジュアル"])
    assert dup is not None
    assert dup["id"] == 999


def test_returns_none_when_no_overlap():
    existing = [{"id": 1, "title": {"rendered": "BTS ジョングク 入隊"}}]
    with patch("urllib.request.urlopen", return_value=_fake_resp(existing)):
        dup = find_duplicate_published(["IVE", "ウォニョン"])
    assert dup is None


def test_returns_none_on_api_error():
    with patch("urllib.request.urlopen", side_effect=OSError("boom")):
        dup = find_duplicate_published(["aespa", "Winter"])
    assert dup is None


def test_returns_none_on_empty_keywords():
    with patch("urllib.request.urlopen", return_value=_fake_resp([])):
        dup = find_duplicate_published([])
    assert dup is None
