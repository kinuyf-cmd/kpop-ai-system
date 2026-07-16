"""agent_monitor の時鮮度フィルタ単体テスト(2026-07-16)

parse_gardevoir / parse_audit_feedback が ts を見ずに全期間を集計していたため、
更新の止まった凍結ログ(gardevoir_hook.jsonl=2026-04, audit_feedback.jsonl=2026-05)を
「現在の HARD_FAIL 多発 / タイトル汚染多発」として誤報し続けていた。
直近 N 日以内のレコードだけを集計することを検証する。
"""
import json
from datetime import datetime, timezone, timedelta
from lib import agent_monitor


def _write(path, records):
    with open(path, "w") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def test_gardevoir_ignores_stale_records(tmp_path, monkeypatch):
    """N 日より古い HARD_FAIL は集計されない。"""
    monkeypatch.setattr(agent_monitor, "LOGS", tmp_path)
    now = datetime.now(timezone.utc)
    old = (now - timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
    recent = (now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    _write(tmp_path / "gardevoir_hook.jsonl", [
        {"ts": old, "verdict": "HARD_FAIL", "title": "古い失敗1", "score": 40},
        {"ts": old, "verdict": "HARD_FAIL", "title": "古い失敗2", "score": 38},
        {"ts": recent, "verdict": "HARD_FAIL", "title": "最近の失敗", "score": 42},
        {"ts": recent, "verdict": "PASS", "title": "最近の合格", "score": 90},
    ])
    data = agent_monitor.parse_gardevoir_jsonl()
    # 90日前の2件は除外、直近の1件のみ
    assert data["fail"] == 1, f"凍結古ログの HARD_FAIL が集計されている: {data['fail']}"
    assert "最近の失敗" in data["hard_fail_titles"]
    assert "古い失敗1" not in data["hard_fail_titles"]


def test_audit_feedback_ignores_stale_records(tmp_path, monkeypatch):
    """N 日より古いタイトル汚染フィードバックは集計されない。"""
    monkeypatch.setattr(agent_monitor, "LOGS", tmp_path)
    now = datetime.now(timezone.utc)
    old = (now - timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%S.%f")
    recent = (now - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S.%f")
    _write(tmp_path / "audit_feedback.jsonl", [
        {"ts": old, "post_id": 2555, "title": "AI応答混入した古い記事"},
        {"ts": recent, "post_id": 9001, "title": "最近のフィードバック"},
    ])
    data = agent_monitor.parse_audit_feedback()
    ids = [d.get("post_id") for d in data]
    assert 2555 not in ids, f"凍結古ログ(post_id=2555)が集計されている: {ids}"
    assert 9001 in ids


def test_gardevoir_all_stale_yields_zero(tmp_path, monkeypatch):
    """全レコードが古い(凍結ログ)なら fail=0 になり誤報しない。"""
    monkeypatch.setattr(agent_monitor, "LOGS", tmp_path)
    old = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
    _write(tmp_path / "gardevoir_hook.jsonl", [
        {"ts": old, "verdict": "HARD_FAIL", "title": f"古い{i}", "score": 40}
        for i in range(32)
    ])
    data = agent_monitor.parse_gardevoir_jsonl()
    assert data["fail"] == 0, f"凍結ログ32件が誤報されている: {data['fail']}"
