#!/usr/bin/env python3
"""計測バグ由来 pending 提案の却下スクリプトの単体テスト (2026-07-10)。

jsonl は追記専用。既存行の status は書き換わらないため、
「既に rejects_ts で打ち消された提案」を再検出しないことが冪等性の要件。

実行: python3 -m pytest tests/unit/test_reject_stale_proposals.py -v
"""
import json

import tools.reject_stale_proposals as rj


def _write(tmp_path, records):
    p = tmp_path / "proposals.jsonl"
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
                 encoding="utf-8")
    return str(p)


PENDING = {"ts": "2026-07-09T21:30:01+00:00", "status": "pending_owner_review",
           "theme": "unknown", "observed": {"n": 77}}


def test_finds_pending_unknown_proposal(tmp_path):
    """theme='unknown' の pending 提案を拾う。"""
    path = _write(tmp_path, [PENDING])
    assert [d["ts"] for d in rj.find_stale(path)] == [PENDING["ts"]]


def test_ignores_already_rejected_proposal(tmp_path):
    """rejects_ts で打ち消し済みの提案は再検出しない。二重却下を防ぐ。"""
    rejected = {"ts": "2026-07-10T09:00:00+00:00", "status": "rejected",
                "rejects_ts": PENDING["ts"], "theme": "unknown"}
    path = _write(tmp_path, [PENDING, rejected])
    assert rj.find_stale(path) == []


def test_finds_only_the_new_pending_when_old_is_rejected(tmp_path):
    """古い提案が却下済みでも、新しい pending は拾う。"""
    rejected = {"ts": "2026-07-10T09:00:00+00:00", "status": "rejected",
                "rejects_ts": PENDING["ts"], "theme": "unknown"}
    fresh = dict(PENDING, ts="2026-07-10T09:02:31+00:00")
    path = _write(tmp_path, [PENDING, rejected, fresh])
    assert [d["ts"] for d in rj.find_stale(path)] == [fresh["ts"]]


def test_ignores_non_unknown_theme(tmp_path):
    """実 theme の提案は計測バグ由来ではない。人間が判断する。"""
    real = dict(PENDING, theme="movie_anime")
    assert rj.find_stale(_write(tmp_path, [real])) == []


def test_ignores_non_pending_status(tmp_path):
    """承認済み/却下済みの status は対象外。"""
    approved = dict(PENDING, status="approved")
    assert rj.find_stale(_write(tmp_path, [approved])) == []


def test_returns_empty_when_file_missing(tmp_path):
    """ログが無ければ空。初回実行で落ちない。"""
    assert rj.find_stale(str(tmp_path / "nope.jsonl")) == []


def test_skips_broken_lines(tmp_path):
    """壊れた行があっても止まらない。追記専用ログの実運用上ありうる。"""
    p = tmp_path / "proposals.jsonl"
    p.write_text("これはJSONではない\n" + json.dumps(PENDING, ensure_ascii=False) + "\n",
                 encoding="utf-8")
    assert len(rj.find_stale(str(p))) == 1
