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


def test_returns_dup_on_overlap_rate_branch():
    """固有名詞でない漢字語が2語一致 かつ overlap率>40% の分岐を検証。"""
    existing = [{"id": 42, "title": {"rendered": "活動 休止 を発表"}}]
    # new_kw=3語中2語(漢字)が一致 → proper_overlap=0 だが overlap=2, rate=2/3>0.4
    with patch("urllib.request.urlopen", return_value=_fake_resp(existing)):
        dup = find_duplicate_published(["活動", "休止", "ダンス"])
    assert dup is not None
    assert dup["id"] == 42


def test_returns_none_on_api_error():
    with patch("urllib.request.urlopen", side_effect=OSError("boom")):
        dup = find_duplicate_published(["aespa", "Winter"])
    assert dup is None


def test_returns_none_on_empty_keywords():
    with patch("urllib.request.urlopen", return_value=_fake_resp([])):
        dup = find_duplicate_published([])
    assert dup is None


def test_returns_dup_when_hangul_proper_nouns_overlap():
    """既存タイトルがハングル固有名詞を含む場合も重複検出できる。

    速報ソースは韓国語タイトルが多く、既存記事側もハングル表記のことがある。
    キーワード抽出正規表現がハングル(가-힣)を対象外にしていると、
    ハングル固有名詞が overlap に載らず、生成前 dedup をすり抜ける
    (公開率低下の実測根因)。"""
    existing = [{"id": 8187, "title": {"rendered": "레드벨벳 컴백 확정"}}]
    with patch("urllib.request.urlopen", return_value=_fake_resp(existing)):
        dup = find_duplicate_published(["레드벨벳", "컴백"])
    assert dup is not None
    assert dup["id"] == 8187
