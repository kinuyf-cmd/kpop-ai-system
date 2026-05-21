"""
ceo_reinject_gate.py — 再投入前安全ゲート + patch_ready 振り分け
フェーズ1: reinject_limited_return_queue → reinject_gate_queue
フェーズ2: reinject_gate_queue → reinject_patch_ready_queue

実行・config書込・patch_plan書き戻し・WP変更は一切しない。
判定・振り分け・可視化のみ。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"

LIMITED_RETURN_QUEUE_PATH  = LOGS / "ceo_reinject_limited_return_queue.jsonl"
GATE_QUEUE_PATH            = LOGS / "ceo_reinject_gate_queue.jsonl"
GATE_HISTORY_PATH          = LOGS / "ceo_reinject_gate_history.jsonl"
PATCH_READY_QUEUE_PATH     = LOGS / "ceo_reinject_patch_ready_queue.jsonl"
PATCH_READY_HISTORY_PATH   = LOGS / "ceo_reinject_patch_ready_history.jsonl"

_REVENUE_AGENTS    = {"バタフリー", "サーナイト", "カイリュー", "WP投稿", "アルセウス", "X投稿B"}
_ALLOWED_FB_TYPES  = {"keep", "minor_adjust", "urgent_fix"}
_ALLOWED_LABELS    = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
_DISPATCH_LABELS   = {"CRITICAL", "HIGH", "MEDIUM"}


# ────────────────────────────────────────────
# ユーティリティ
# ────────────────────────────────────────────

def _now_jst() -> str:
    jst = timezone(timedelta(hours=9))
    return datetime.now(jst).strftime("%Y-%m-%d %H:%M:%S JST")


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


# ────────────────────────────────────────────
# フェーズ1: limited_return → gate
# ────────────────────────────────────────────

def _run_gate_checks(rec: dict) -> tuple[bool, str, dict]:
    """ゲート判定。(passed, reason, checks_dict) を返す"""
    checks = {
        "execution_blocked_true":  rec.get("execution_blocked") is True,
        "write_scope_none":        rec.get("write_scope") == "none",
        "target_agent_known":      bool(rec.get("target_agent", "").strip()),
        "feedback_type_allowed":   rec.get("feedback_type", "") in _ALLOWED_FB_TYPES,
        "priority_label_allowed":  rec.get("reinject_priority_label", "") in _ALLOWED_LABELS,
    }

    reasons = []
    if not checks["execution_blocked_true"]:
        reasons.append("execution_blocked が true でない")
    if not checks["write_scope_none"]:
        reasons.append("write_scope が 'none' でない")
    if not checks["target_agent_known"]:
        reasons.append("target_agent が空")
    if not checks["feedback_type_allowed"]:
        reasons.append(f"feedback_type '{rec.get('feedback_type','')}' が不正")
    if not checks["priority_label_allowed"]:
        reasons.append(f"reinject_priority_label '{rec.get('reinject_priority_label','')}' が不正")

    passed = all(checks.values())
    reason = " / ".join(reasons) if reasons else ""
    return passed, reason, checks


def build_gate_queue() -> dict:
    """reinject_limited_return_queue → reinject_gate_queue"""
    return_recs    = _load_jsonl(LIMITED_RETURN_QUEUE_PATH)
    existing_gate  = _load_jsonl(GATE_QUEUE_PATH)

    existing_dup_keys: set[str] = {
        r.get("duplicate_key", "")
        for r in existing_gate
        if r.get("gate_status") in ("pending", "blocked", "archived")
    }

    # 対象: return_status=pending + return_ready=True + 対象ラベル
    candidates = [
        r for r in return_recs
        if r.get("return_status") == "pending"
        and r.get("return_ready") is True
        and r.get("reinject_priority_label") in _DISPATCH_LABELS
    ]

    # ソート: reinject_order asc → score desc
    candidates.sort(key=lambda r: (
        int(r.get("reinject_order", 999)),
        -float(r.get("reinject_priority_score", 0)),
    ))

    promoted = 0
    blocked  = 0
    dup_count = 0

    for rec in candidates:
        dup_key = rec.get("duplicate_key", "")
        passed, reason, checks = _run_gate_checks(rec)

        gate_rec = {
            "gated_at":                _now_jst(),
            "source_returned_at":      rec.get("returned_at", ""),
            "target_agent":            rec.get("target_agent", ""),
            "feedback_type":           rec.get("feedback_type", ""),
            "reinject_priority_score": rec.get("reinject_priority_score", 0.0),
            "reinject_priority_label": rec.get("reinject_priority_label", ""),
            "reinject_order":          rec.get("reinject_order", 0),
            "proposed_reinject_action": rec.get("proposed_reinject_action", ""),
            "next_improvement_hint":   rec.get("next_improvement_hint", ""),
            "gate_checks":             checks,
            "gate_passed":             passed,
            "gate_reason":             reason,
            "gate_status":             "pending" if passed else "blocked",
            "execution_blocked":       True,
            "write_scope":             "none",
            "gated_from":              "ceo_reinject_limited_return_queue",
            "duplicate_key":           dup_key,
            "ceo_judgment":            "ミュウツーCEO再投入ゲート判定",
        }

        if dup_key in existing_dup_keys:
            dup_count += 1
            _append_jsonl(GATE_HISTORY_PATH, {
                **gate_rec,
                "gate_status": "gate_duplicate",
                "reason": f"同一 duplicate_key が既に存在: {dup_key}",
            })
            continue

        existing_dup_keys.add(dup_key)
        _append_jsonl(GATE_QUEUE_PATH, gate_rec)
        if passed:
            promoted += 1
        else:
            blocked += 1

    pending_total = sum(
        1 for r in _load_jsonl(GATE_QUEUE_PATH)
        if r.get("gate_status") == "pending"
    )

    return {"promoted": promoted, "blocked": blocked, "dup": dup_count, "pending": pending_total}


# ────────────────────────────────────────────
# フェーズ2: gate → patch_ready
# ────────────────────────────────────────────

def build_patch_ready_queue() -> dict:
    """reinject_gate_queue → reinject_patch_ready_queue（実書き戻しなし）"""
    gate_recs     = _load_jsonl(GATE_QUEUE_PATH)
    existing_pr   = _load_jsonl(PATCH_READY_QUEUE_PATH)

    existing_dup_keys: set[str] = {
        r.get("duplicate_key", "")
        for r in existing_pr
        if r.get("patch_ready_status") in ("pending", "archived")
    }

    def _qualifies(r: dict) -> bool:
        if r.get("gate_status") != "pending":
            return False
        if not r.get("gate_passed", False):
            return False
        lbl   = r.get("reinject_priority_label", "")
        agent = r.get("target_agent", "")
        if lbl in ("CRITICAL", "HIGH"):
            return True
        if lbl == "MEDIUM" and agent in _REVENUE_AGENTS:
            return True
        return False

    candidates = [r for r in gate_recs if _qualifies(r)]

    candidates.sort(key=lambda r: (
        int(r.get("reinject_order", 999)),
        -float(r.get("reinject_priority_score", 0)),
    ))

    promoted  = 0
    dup_count = 0

    for rec in candidates:
        dup_key = rec.get("duplicate_key", "")

        pr_rec = {
            "readied_at":              _now_jst(),
            "source_gated_at":         rec.get("gated_at", ""),
            "target_agent":            rec.get("target_agent", ""),
            "feedback_type":           rec.get("feedback_type", ""),
            "reinject_priority_score": rec.get("reinject_priority_score", 0.0),
            "reinject_priority_label": rec.get("reinject_priority_label", ""),
            "reinject_order":          rec.get("reinject_order", 0),
            "proposed_reinject_action": rec.get("proposed_reinject_action", ""),
            "next_improvement_hint":   rec.get("next_improvement_hint", ""),
            "patch_ready":             True,
            "patch_target_lane":       "ceo_config_patch_plan_queue",
            "patch_ready_status":      "pending",
            "execution_blocked":       True,
            "write_scope":             "none",
            "readied_from":            "ceo_reinject_gate_queue",
            "duplicate_key":           dup_key,
            "ceo_judgment":            "ミュウツーCEO再投入パッチ接続候補",
        }

        if dup_key in existing_dup_keys:
            dup_count += 1
            _append_jsonl(PATCH_READY_HISTORY_PATH, {
                **pr_rec,
                "patch_ready_status": "patch_ready_duplicate",
                "reason": f"同一 duplicate_key が既に pending/archived に存在: {dup_key}",
            })
            continue

        existing_dup_keys.add(dup_key)
        _append_jsonl(PATCH_READY_QUEUE_PATH, pr_rec)
        promoted += 1

    pending_total = sum(
        1 for r in _load_jsonl(PATCH_READY_QUEUE_PATH)
        if r.get("patch_ready_status") == "pending"
    )

    return {"promoted": promoted, "dup": dup_count, "pending": pending_total}


# ────────────────────────────────────────────
# 統計
# ────────────────────────────────────────────

def get_reinject_gate_stats() -> dict:
    recs     = _load_jsonl(GATE_QUEUE_PATH)
    pending  = [r for r in recs if r.get("gate_status") == "pending"]
    blocked  = [r for r in recs if r.get("gate_status") == "blocked"]

    sorted_p = sorted(pending, key=lambda r: (int(r.get("reinject_order", 999)), -float(r.get("reinject_priority_score", 0))))
    top1     = sorted_p[0]      if sorted_p else {}
    latest   = (pending or recs)[-1] if (pending or recs) else {}

    return {
        "reinject_gate_pending_count": len(pending),
        "reinject_gate_blocked_count": len(blocked),
        "reinject_gate_latest_agent":  latest.get("target_agent", "—"),
        "reinject_gate_latest_status": latest.get("gate_status", "—"),
        "reinject_gate_top1_agent":    top1.get("target_agent", "—"),
        "reinject_gate_top1_score":    top1.get("reinject_priority_score", 0.0),
    }


def get_reinject_patch_ready_stats() -> dict:
    recs    = [r for r in _load_jsonl(PATCH_READY_QUEUE_PATH) if r.get("patch_ready_status") == "pending"]
    counts  = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for r in recs:
        lbl = r.get("reinject_priority_label", "LOW")
        counts[lbl] = counts.get(lbl, 0) + 1

    sorted_r = sorted(recs, key=lambda r: (int(r.get("reinject_order", 999)), -float(r.get("reinject_priority_score", 0))))
    top1     = sorted_r[0] if sorted_r else {}
    latest   = recs[-1]    if recs     else {}

    return {
        "reinject_patch_ready_pending_count": len(recs),
        "reinject_patch_ready_high_count":    counts.get("HIGH", 0) + counts.get("CRITICAL", 0),
        "reinject_patch_ready_medium_count":  counts.get("MEDIUM", 0),
        "reinject_patch_ready_latest_agent":  latest.get("target_agent", "—"),
        "reinject_patch_ready_latest_label":  latest.get("reinject_priority_label", "—"),
        "reinject_patch_ready_top1_agent":    top1.get("target_agent", "—"),
        "reinject_patch_ready_top1_score":    top1.get("reinject_priority_score", 0.0),
    }


# ────────────────────────────────────────────
# 統合実行
# ────────────────────────────────────────────

def run_reinject_gate_cycle() -> dict:
    gate_result  = build_gate_queue()
    pr_result    = build_patch_ready_queue()
    return {"gate": gate_result, "patch_ready": pr_result}
