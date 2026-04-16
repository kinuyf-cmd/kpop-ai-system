#!/usr/bin/env python3
"""
ceo_safety_invariants.py — 安全不変条件監視 v1.0
CEO: ミュウツー / オーナー: 人間（閲覧専用）

【役割】
  危険な逸脱を検知し invariant_violation_queue / history に記録する。
  dashboard上部・hardening_alerts に反映する。

【監視対象】
  1. execution_blocked が false なのに想定外レーンにいる
  2. write_scope が queue_only / none / config_single_key 以外
  3. backup_required なしで apply_execute_queue に入っている
  4. target_config が config/agent_directives.json 以外
  5. patch_path が agent_directives. で始まらない
  6. after_value が空

【制約】
  - 書き込みは violation_queue / history のみ
  - config への書き込みなし
  - append-only
  - LLM 判断なし
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"
JST  = timezone(timedelta(hours=9))

APPLY_EXECUTE_QUEUE_PATH  = LOGS / "ceo_apply_execute_queue.jsonl"
UNLOCK_EXECUTE_QUEUE_PATH = LOGS / "ceo_unlock_execute_queue.jsonl"
# すべてのキューを対象にする場合は随時追加

INVARIANT_VIOLATION_QUEUE   = LOGS / "ceo_invariant_violation_queue.jsonl"
INVARIANT_VIOLATION_HISTORY = LOGS / "ceo_invariant_violation_history.jsonl"

VALID_WRITE_SCOPES = {"queue_only", "none", "config_single_key"}

# 想定外レーンで execution_blocked=false を許さないキュー
BLOCKED_REQUIRED_QUEUES = [
    ("ceo_reinject_apply_gate_queue.jsonl",   "gate_status"),
    ("ceo_reinject_apply_ready_queue.jsonl",  "ready_status"),
    ("ceo_reinject_apply_unlock_candidate_queue.jsonl", "candidate_status"),
    ("ceo_reinject_unlock_judge_queue.jsonl", "judge_status"),
    ("ceo_unlock_execute_queue.jsonl",        "unlock_status"),
]


def _now_jst() -> str:
    return datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S JST")


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    recs = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    recs.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return recs


def _append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _vkey(queue_name: str, dup_key: str, rule: str) -> str:
    return f"{queue_name}|{dup_key}|{rule}"


# ════════════════════════════════════════════════════════════════════
# 不変条件チェック
# ════════════════════════════════════════════════════════════════════

def scan_invariant_violations() -> dict:
    """
    全対象キューをスキャンし violation を検出・記録する。
    """
    existing = _load_jsonl(INVARIANT_VIOLATION_QUEUE)
    existing_vkeys: set[str] = {
        r.get("violation_key", "") for r in existing
        if r.get("violation_status") == "pending"
    }

    detected = 0

    def _add(queue_name: str, dup_key: str, ta: str, rule: str, detail: str) -> None:
        nonlocal detected
        vk = _vkey(queue_name, dup_key, rule)
        if vk in existing_vkeys:
            return
        existing_vkeys.add(vk)
        rec = {
            "detected_at":     _now_jst(),
            "violation_key":   vk,
            "queue_name":      queue_name,
            "duplicate_key":   dup_key,
            "target_agent":    ta,
            "rule":            rule,
            "detail":          detail,
            "violation_status":"pending",
            "severity":        "HIGH",
            "ceo_judgment":    "ミュウツーCEO安全不変条件違反",
        }
        _append_jsonl(INVARIANT_VIOLATION_QUEUE, rec)
        _append_jsonl(INVARIANT_VIOLATION_HISTORY, {
            "processed_at": _now_jst(),
            "violation_key": vk,
            "rule":          rule,
            "detail":        detail,
            "status":        "detected",
            "ceo_judgment":  "ミュウツーCEO安全不変条件違反",
        })
        detected += 1

    # ── Rule1: apply_execute_queue の各フィールドチェック ──
    for rec in _load_jsonl(APPLY_EXECUTE_QUEUE_PATH):
        if rec.get("apply_execute_status") != "pending":
            continue
        dup_key = rec.get("duplicate_key", "")
        ta      = rec.get("target_agent", "—")
        qname   = "ceo_apply_execute_queue"

        # Rule2: write_scope 不正
        ws = rec.get("write_scope", "")
        if ws not in VALID_WRITE_SCOPES:
            _add(qname, dup_key, ta, "invalid_write_scope",
                 f"write_scope={ws} (有効値: {VALID_WRITE_SCOPES})")

        # Rule3: backup_required なし
        if not rec.get("backup_required", False):
            _add(qname, dup_key, ta, "backup_required_missing",
                 "backup_required=false で apply_execute_queue に登録されている")

        # Rule4: target_config 不正
        tc = rec.get("target_config", "")
        if tc and tc != "config/agent_directives.json":
            _add(qname, dup_key, ta, "invalid_target_config",
                 f"target_config={tc}")

        # Rule5: patch_path 不正
        pp = rec.get("patch_path", "")
        if pp and not pp.startswith("agent_directives."):
            _add(qname, dup_key, ta, "invalid_patch_path",
                 f"patch_path={pp} (agent_directives. で始まらない)")

        # Rule6: after_value 空
        if not (rec.get("after_value") or "").strip():
            _add(qname, dup_key, ta, "empty_after_value",
                 "after_value が空で apply_execute_queue に登録されている")

    # ── Rule1: execution_blocked=false が想定外レーンにある ──
    for rel_name, status_field in BLOCKED_REQUIRED_QUEUES:
        path = LOGS / rel_name
        for rec in _load_jsonl(path):
            # unlock_status=unlocked は execution_blocked=false が正常
            if rel_name == "ceo_unlock_execute_queue.jsonl":
                if rec.get("unlock_status") == "unlocked":
                    continue
            if rec.get("execution_blocked") is False:
                dup_key = rec.get("duplicate_key", "")
                ta      = rec.get("target_agent", "—")
                _add(rel_name, dup_key, ta, "unexpected_unblocked",
                     f"execution_blocked=false が {rel_name} の {status_field}={rec.get(status_field,'?')} レコードに存在")

    pending_total = sum(1 for r in _load_jsonl(INVARIANT_VIOLATION_QUEUE)
                        if r.get("violation_status") == "pending")
    return {
        "detected":      detected,
        "pending_total": pending_total,
    }


def get_invariant_stats() -> dict:
    recs    = _load_jsonl(INVARIANT_VIOLATION_QUEUE)
    pending = [r for r in recs if r.get("violation_status") == "pending"]
    latest  = pending[-1] if pending else {}
    by_rule: dict[str, int] = {}
    for r in pending:
        rule = r.get("rule", "unknown")
        by_rule[rule] = by_rule.get(rule, 0) + 1
    return {
        "invariant_violation_count":   len(pending),
        "invariant_latest_rule":       latest.get("rule", "—"),
        "invariant_latest_agent":      latest.get("target_agent", "—"),
        "invariant_latest_detail":     latest.get("detail", "—"),
        "invariant_by_rule":           by_rule,
        "invariant_is_critical":       len(pending) > 0,
    }


if __name__ == "__main__":
    import json as _json
    result = scan_invariant_violations()
    print(_json.dumps(result, ensure_ascii=False, indent=2))
    print(_json.dumps(get_invariant_stats(), ensure_ascii=False, indent=2))
