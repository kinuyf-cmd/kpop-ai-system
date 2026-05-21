"""
ceo_reinject_apply_gate.py — apply解放ゲート + apply候補レーン + 最終解放候補レーン
フェーズ1: ceo_config_patch_plan_queue(reinject_commit) → reinject_apply_gate_queue
フェーズ2: reinject_apply_gate_queue → reinject_apply_ready_queue
フェーズ3: reinject_apply_ready_queue → reinject_apply_unlock_candidate_queue

config/agent_directives.json 本体は変更しない。
execution_blocked は true のまま。apply実行しない。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"

PATCH_PLAN_QUEUE_PATH    = LOGS / "ceo_config_patch_plan_queue.jsonl"
APPLY_GATE_QUEUE_PATH    = LOGS / "ceo_reinject_apply_gate_queue.jsonl"
APPLY_GATE_HISTORY_PATH  = LOGS / "ceo_reinject_apply_gate_history.jsonl"
APPLY_READY_QUEUE_PATH   = LOGS / "ceo_reinject_apply_ready_queue.jsonl"
APPLY_READY_HISTORY_PATH = LOGS / "ceo_reinject_apply_ready_history.jsonl"
UNLOCK_CANDIDATE_QUEUE_PATH   = LOGS / "ceo_reinject_apply_unlock_candidate_queue.jsonl"
UNLOCK_CANDIDATE_HISTORY_PATH = LOGS / "ceo_reinject_apply_unlock_candidate_history.jsonl"
UNLOCK_JUDGE_QUEUE_PATH       = LOGS / "ceo_reinject_unlock_judge_queue.jsonl"
UNLOCK_JUDGE_HISTORY_PATH     = LOGS / "ceo_reinject_unlock_judge_history.jsonl"


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


def _make_dup_key(rec: dict) -> str:
    agent  = rec.get("target_agent", "")
    ftype  = rec.get("feedback_type", "") or rec.get("improvement_type", "")
    hint   = (rec.get("after_value", "") or "").strip()
    return f"{agent}|{ftype}|{hint[:80]}"


# ────────────────────────────────────────────
# フェーズ1: patch_plan → apply_gate
# ────────────────────────────────────────────

def _run_gate_checks(rec: dict) -> tuple[bool, str, dict]:
    checks = {
        "source_reinject_commit":  rec.get("source") == "reinject_commit",
        "plan_status_pending":     rec.get("plan_status") == "pending",
        "execution_blocked_true":  rec.get("execution_blocked") is True,
        "write_scope_queue_only":  rec.get("write_scope") == "queue_only",
        "patch_path_valid":        bool((rec.get("patch_path") or "").strip()),
        "agent_key_present":       bool((rec.get("agent_key") or "").strip()),
    }
    reasons = []
    if not checks["source_reinject_commit"]:
        reasons.append("source が reinject_commit でない")
    if not checks["plan_status_pending"]:
        reasons.append("plan_status が pending でない")
    if not checks["execution_blocked_true"]:
        reasons.append("execution_blocked が true でない")
    if not checks["write_scope_queue_only"]:
        reasons.append("write_scope が queue_only でない")
    if not checks["patch_path_valid"]:
        reasons.append("patch_path が空")
    if not checks["agent_key_present"]:
        reasons.append("agent_key が空")

    passed = all(checks.values())
    reason = " / ".join(reasons) if reasons else ""
    return passed, reason, checks


def build_apply_gate_queue() -> dict:
    """patch_plan_queue の reinject_commit レコード → apply_gate_queue"""
    patch_recs   = _load_jsonl(PATCH_PLAN_QUEUE_PATH)
    existing_gate = _load_jsonl(APPLY_GATE_QUEUE_PATH)

    existing_dup_keys: set[str] = {
        r.get("duplicate_key", "")
        for r in existing_gate
        if r.get("gate_status") in ("pending", "blocked", "archived")
    }

    # 対象: source=reinject_commit + plan_status=pending
    candidates = [
        r for r in patch_recs
        if r.get("source") == "reinject_commit"
        and r.get("plan_status") == "pending"
    ]

    # ソート: priority_score desc
    candidates.sort(key=lambda r: -float(r.get("priority_score", 0)))

    promoted  = 0
    blocked_n = 0
    dup_count = 0

    for rec in candidates:
        dup_key = _make_dup_key(rec)
        passed, reason, checks = _run_gate_checks(rec)

        gate_rec = {
            "gated_at":          _now_jst(),
            "source_queued_at":  rec.get("planned_at", ""),
            "target_agent":      rec.get("target_agent", ""),
            "feedback_type":     rec.get("feedback_type", "") or rec.get("improvement_type", ""),
            "priority":          rec.get("priority", ""),
            "priority_score":    rec.get("priority_score", 0.0),
            "patch_path":        rec.get("patch_path", ""),
            "agent_key":         rec.get("agent_key", ""),
            "after_value":       rec.get("after_value", ""),
            "diff_preview":      rec.get("diff_preview", ""),
            "gate_checks":       checks,
            "gate_passed":       passed,
            "gate_reason":       reason,
            "gate_status":       "pending" if passed else "blocked",
            "execution_blocked": True,
            "write_scope":       "queue_only",
            "gated_from":        "ceo_config_patch_plan_queue",
            "duplicate_key":     dup_key,
            "ceo_judgment":      "ミュウツーCEO apply解放ゲート",
        }

        if dup_key in existing_dup_keys:
            dup_count += 1
            _append_jsonl(APPLY_GATE_HISTORY_PATH, {
                **gate_rec,
                "gate_status": "gate_duplicate",
                "reason": f"同一 duplicate_key が gate_queue に存在: {dup_key}",
            })
            continue

        existing_dup_keys.add(dup_key)
        _append_jsonl(APPLY_GATE_QUEUE_PATH, gate_rec)
        if passed:
            promoted += 1
        else:
            blocked_n += 1

    pending_total = sum(
        1 for r in _load_jsonl(APPLY_GATE_QUEUE_PATH)
        if r.get("gate_status") == "pending"
    )
    return {"promoted": promoted, "blocked": blocked_n, "dup": dup_count, "pending": pending_total}


# ────────────────────────────────────────────
# フェーズ2: apply_gate → apply_ready
# ────────────────────────────────────────────

def build_apply_ready_queue() -> dict:
    """apply_gate_queue の通過候補 → apply_ready_queue"""
    gate_recs    = _load_jsonl(APPLY_GATE_QUEUE_PATH)
    existing_rdy = _load_jsonl(APPLY_READY_QUEUE_PATH)

    existing_dup_keys: set[str] = {
        r.get("duplicate_key", "")
        for r in existing_rdy
        if r.get("apply_ready_status") in ("pending", "archived")
    }

    def _qualifies(r: dict) -> bool:
        if r.get("gate_status") != "pending":
            return False
        if not r.get("gate_passed", False):
            return False
        if r.get("priority", "") not in ("HIGH", "MEDIUM"):
            return False
        if not str(r.get("patch_path", "")).startswith("agent_directives."):
            return False
        if not (r.get("target_agent") or "").strip():
            return False
        return True

    candidates = [r for r in gate_recs if _qualifies(r)]
    candidates.sort(key=lambda r: -float(r.get("priority_score", 0)))

    promoted  = 0
    dup_count = 0

    for rec in candidates:
        dup_key = rec.get("duplicate_key", "")

        ready_rec = {
            "readied_at":        _now_jst(),
            "source_gated_at":   rec.get("gated_at", ""),
            "target_agent":      rec.get("target_agent", ""),
            "feedback_type":     rec.get("feedback_type", ""),
            "priority":          rec.get("priority", ""),
            "priority_score":    rec.get("priority_score", 0.0),
            "patch_path":        rec.get("patch_path", ""),
            "agent_key":         rec.get("agent_key", ""),
            "after_value":       rec.get("after_value", ""),
            "diff_preview":      rec.get("diff_preview", ""),
            "apply_ready":       True,
            "apply_ready_status": "pending",
            "next_executor":     "ceo_config_executor.py",
            "next_condition":    "execution_blocked を false にした時のみ apply 可",
            "execution_blocked": True,
            "write_scope":       "queue_only",
            "readied_from":      "ceo_reinject_apply_gate_queue",
            "duplicate_key":     dup_key,
            "ceo_judgment":      "ミュウツーCEO apply候補",
        }

        if dup_key in existing_dup_keys:
            dup_count += 1
            _append_jsonl(APPLY_READY_HISTORY_PATH, {
                **ready_rec,
                "apply_ready_status": "apply_ready_duplicate",
                "reason": f"同一 duplicate_key が ready_queue に pending/archived で存在: {dup_key}",
            })
            continue

        existing_dup_keys.add(dup_key)
        _append_jsonl(APPLY_READY_QUEUE_PATH, ready_rec)
        promoted += 1

    pending_total = sum(
        1 for r in _load_jsonl(APPLY_READY_QUEUE_PATH)
        if r.get("apply_ready_status") == "pending"
    )
    return {"promoted": promoted, "dup": dup_count, "pending": pending_total}


# ────────────────────────────────────────────
# 統計
# ────────────────────────────────────────────

def get_reinject_apply_gate_stats() -> dict:
    recs    = _load_jsonl(APPLY_GATE_QUEUE_PATH)
    pending = [r for r in recs if r.get("gate_status") == "pending"]
    blocked = [r for r in recs if r.get("gate_status") == "blocked"]

    sorted_p = sorted(pending, key=lambda r: -float(r.get("priority_score", 0)))
    top1   = sorted_p[0]           if sorted_p           else {}
    latest = (pending or blocked or recs)[-1] if recs    else {}

    return {
        "reinject_apply_gate_pending_count": len(pending),
        "reinject_apply_gate_blocked_count": len(blocked),
        "reinject_apply_gate_latest_agent":  latest.get("target_agent", "—"),
        "reinject_apply_gate_latest_status": latest.get("gate_status", "—"),
        "reinject_apply_gate_top1_agent":    top1.get("target_agent", "—"),
        "reinject_apply_gate_top1_score":    top1.get("priority_score", 0.0),
    }


def get_reinject_apply_ready_stats() -> dict:
    recs   = [r for r in _load_jsonl(APPLY_READY_QUEUE_PATH) if r.get("apply_ready_status") == "pending"]
    counts = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for r in recs:
        p = r.get("priority", "LOW")
        counts[p] = counts.get(p, 0) + 1

    sorted_r = sorted(recs, key=lambda r: -float(r.get("priority_score", 0)))
    top1   = sorted_r[0] if sorted_r else {}
    latest = recs[-1]    if recs     else {}

    return {
        "reinject_apply_ready_pending_count": len(recs),
        "reinject_apply_ready_high_count":    counts.get("HIGH", 0),
        "reinject_apply_ready_medium_count":  counts.get("MEDIUM", 0),
        "reinject_apply_ready_latest_agent":  latest.get("target_agent", "—"),
        "reinject_apply_ready_latest_priority": latest.get("priority", "—"),
        "reinject_apply_ready_top1_agent":    top1.get("target_agent", "—"),
        "reinject_apply_ready_top1_score":    top1.get("priority_score", 0.0),
    }


# ────────────────────────────────────────────
# 統合実行
# ────────────────────────────────────────────

def run_reinject_apply_gate_cycle() -> dict:
    gate_result  = build_apply_gate_queue()
    ready_result = build_apply_ready_queue()
    return {"gate": gate_result, "ready": ready_result}


# ────────────────────────────────────────────
# フェーズ3: apply_ready → unlock_candidate
# ────────────────────────────────────────────

def _make_unlock_dup_key(rec: dict) -> str:
    agent = rec.get("target_agent", "")
    ftype = rec.get("feedback_type", "")
    hint  = (rec.get("next_improvement_hint", "") or "").strip()
    if hint:
        return f"{agent}|{ftype}|{hint[:80]}"
    action = (rec.get("proposed_reinject_action", "") or "").strip()
    if action:
        return f"{agent}|{ftype}|{action[:80]}"
    after  = (rec.get("after_value", "") or "").strip()
    return f"{agent}|{ftype}|{after[:80]}"


def promote_to_apply_unlock_candidate() -> dict:
    """apply_ready_queue(pending) → unlock_candidate_queue
    通過条件:
      - priority in {HIGH, CRITICAL}
      - execution_blocked == true
      - write_scope == "queue_only"
      - next_executor == "ceo_config_executor.py" (空なら補完して同値扱い)
      - target_agent 非空
      - patch_path 存在かつ "agent_directives." で始まる
      - after_value 非空
    execution_blocked は true のまま。config本体変更しない。
    """
    ready_recs   = _load_jsonl(APPLY_READY_QUEUE_PATH)
    existing_uc  = _load_jsonl(UNLOCK_CANDIDATE_QUEUE_PATH)

    existing_dup_keys: set[str] = {
        r.get("duplicate_key", "")
        for r in existing_uc
        if r.get("unlock_candidate_status") in ("pending", "archived")
    }

    candidates = [r for r in ready_recs if r.get("apply_ready_status") == "pending"]
    candidates.sort(key=lambda r: -float(r.get("priority_score", 0)))

    promoted  = 0
    blocked_n = 0
    dup_count = 0

    for rec in candidates:
        dup_key    = _make_unlock_dup_key(rec)
        ta         = (rec.get("target_agent") or "").strip()
        ppath      = (rec.get("patch_path") or "").strip()
        after_v    = (rec.get("after_value") or "").strip()
        priority   = rec.get("priority", "")
        ex_blocked = rec.get("execution_blocked")
        wscope     = rec.get("write_scope", "")
        nexec_raw  = (rec.get("next_executor") or "").strip()
        nexec      = nexec_raw if nexec_raw else "ceo_config_executor.py"

        # 通過チェック
        skip_reason = None
        skip_status = None
        if priority not in ("HIGH", "CRITICAL"):
            skip_reason = f"priority={priority} (HIGH/CRITICAL でない)"
            skip_status = "blocked_not_high_priority"
        elif ex_blocked is not True:
            skip_reason = f"execution_blocked={ex_blocked} (true でない)"
            skip_status = "blocked_execution_not_locked"
        elif wscope != "queue_only":
            skip_reason = f"write_scope={wscope} (queue_only でない)"
            skip_status = "blocked_invalid_scope"
        elif not ta:
            skip_reason = "target_agent が空"
            skip_status = "blocked_missing_target_agent"
        elif not ppath:
            skip_reason = "patch_path が空"
            skip_status = "blocked_missing_patch_path"
        elif not ppath.startswith("agent_directives."):
            skip_reason = f"patch_path={ppath} (agent_directives. で始まらない)"
            skip_status = "blocked_invalid_patch_path"
        elif not after_v:
            skip_reason = "after_value が空"
            skip_status = "blocked_missing_after_value"

        hist_base = {
            "processed_at": _now_jst(),
            "duplicate_key": dup_key,
            "target_agent": ta,
            "source_queue": "ceo_reinject_apply_ready_queue",
            "ceo_judgment": "ミュウツーCEO最終解放候補",
        }

        if skip_reason:
            blocked_n += 1
            _append_jsonl(UNLOCK_CANDIDATE_HISTORY_PATH, {
                **hist_base,
                "status": skip_status,
                "reason": skip_reason,
            })
            continue

        if dup_key in existing_dup_keys:
            dup_count += 1
            _append_jsonl(UNLOCK_CANDIDATE_HISTORY_PATH, {
                **hist_base,
                "status": "unlock_candidate_duplicate",
                "reason": f"同一 duplicate_key が unlock_candidate_queue に pending/archived で存在: {dup_key}",
            })
            continue

        existing_dup_keys.add(dup_key)

        uc_rec = {
            "unlocked_at":             _now_jst(),
            "source_apply_ready_at":   rec.get("readied_at", ""),
            "target_agent":            ta,
            "feedback_type":           rec.get("feedback_type", ""),
            "priority":                priority,
            "priority_score":          rec.get("priority_score", 0.0),
            "patch_path":              ppath,
            "after_value":             after_v,
            "next_executor":           nexec,
            "execution_blocked":       True,
            "write_scope":             "queue_only",
            "unlock_candidate_ready":  True,
            "unlock_candidate_status": "pending",
            "unlock_target":           "execution_blocked_toggle_only",
            "duplicate_key":           dup_key,
            "source_queue":            "ceo_reinject_apply_ready_queue",
            "ceo_judgment":            "ミュウツーCEO最終解放候補",
        }
        _append_jsonl(UNLOCK_CANDIDATE_QUEUE_PATH, uc_rec)
        _append_jsonl(UNLOCK_CANDIDATE_HISTORY_PATH, {
            **hist_base,
            "status": "promoted",
            "reason": "",
        })
        promoted += 1

    pending_total = sum(
        1 for r in _load_jsonl(UNLOCK_CANDIDATE_QUEUE_PATH)
        if r.get("unlock_candidate_status") == "pending"
    )
    return {"promoted": promoted, "blocked": blocked_n, "dup": dup_count, "pending": pending_total}


def get_apply_unlock_candidate_stats() -> dict:
    recs     = _load_jsonl(UNLOCK_CANDIDATE_QUEUE_PATH)
    pending  = [r for r in recs if r.get("unlock_candidate_status") == "pending"]
    blocked  = [r for r in _load_jsonl(UNLOCK_CANDIDATE_HISTORY_PATH)
                if r.get("status", "").startswith("blocked_")]

    high_count     = sum(1 for r in pending if r.get("priority") == "HIGH")
    critical_count = sum(1 for r in pending if r.get("priority") == "CRITICAL")

    sorted_p = sorted(pending, key=lambda r: (-float(r.get("priority_score", 0)), r.get("target_agent", "")))
    top1   = sorted_p[0] if sorted_p else {}
    latest = pending[-1] if pending else {}

    return {
        "apply_unlock_candidate_pending_count":  len(pending),
        "apply_unlock_candidate_high_count":     high_count,
        "apply_unlock_candidate_critical_count": critical_count,
        "apply_unlock_candidate_latest_agent":   latest.get("target_agent", "—"),
        "apply_unlock_candidate_latest_priority": latest.get("priority", "—"),
        "apply_unlock_candidate_latest_status":  latest.get("unlock_candidate_status", "—"),
        "apply_unlock_candidate_top1_agent":     top1.get("target_agent", "—"),
        "apply_unlock_candidate_top1_score":     top1.get("priority_score", 0.0),
        "apply_unlock_candidate_blocked_count":  len(blocked),
    }


def run_reinject_unlock_candidate_cycle() -> dict:
    return promote_to_apply_unlock_candidate()


# ────────────────────────────────────────────
# フェーズ4: unlock_candidate → unlock_judge
# ────────────────────────────────────────────

def _judge_unlock_candidate(rec: dict) -> tuple[bool, str, str]:
    """通過チェック。戻り値: (passed, skip_status, skip_reason)"""
    priority   = rec.get("priority", "")
    ex_blocked = rec.get("execution_blocked")
    wscope     = rec.get("write_scope", "")
    uc_ready   = rec.get("unlock_candidate_ready")
    ul_target  = rec.get("unlock_target", "")
    nexec      = (rec.get("next_executor") or "").strip()
    ta         = (rec.get("target_agent") or "").strip()
    ppath      = (rec.get("patch_path") or "").strip()
    after_v    = (rec.get("after_value") or "").strip()

    if priority not in ("HIGH", "CRITICAL"):
        return False, "blocked_not_high_priority", f"priority={priority} (HIGH/CRITICAL でない)"
    if ex_blocked is not True:
        return False, "blocked_execution_not_locked", f"execution_blocked={ex_blocked} (true でない)"
    if wscope != "queue_only":
        return False, "blocked_invalid_scope", f"write_scope={wscope} (queue_only でない)"
    if ul_target != "execution_blocked_toggle_only":
        return False, "blocked_invalid_unlock_target", f"unlock_target={ul_target}"
    if nexec != "ceo_config_executor.py":
        return False, "blocked_invalid_next_executor", f"next_executor={nexec or '(空)'}"
    if not ta:
        return False, "blocked_missing_target_agent", "target_agent が空"
    if not ppath.startswith("agent_directives."):
        return False, "blocked_invalid_patch_path", f"patch_path={ppath or '(空)'} (agent_directives. で始まらない)"
    if len(after_v) < 20:
        return False, "blocked_after_value_too_short", f"after_value が20文字未満 (現在{len(after_v)}文字)"
    return True, "", ""


def promote_to_unlock_judge() -> dict:
    """unlock_candidate_queue(pending) → unlock_judge_queue
    判定ルールを全て満たす候補のみ昇格。execution_blocked は true のまま。
    """
    candidate_recs = _load_jsonl(UNLOCK_CANDIDATE_QUEUE_PATH)
    existing_judge = _load_jsonl(UNLOCK_JUDGE_QUEUE_PATH)

    existing_dup_keys: set[str] = {
        r.get("duplicate_key", "")
        for r in existing_judge
        if r.get("judge_status") in ("pending", "archived")
    }

    candidates = [r for r in candidate_recs if r.get("unlock_candidate_status") == "pending"]
    candidates.sort(key=lambda r: (-float(r.get("priority_score", 0)), r.get("target_agent", "")))

    promoted  = 0
    blocked_n = 0
    dup_count = 0

    for rec in candidates:
        dup_key = _make_unlock_dup_key(rec)
        passed, skip_status, skip_reason = _judge_unlock_candidate(rec)

        ta = (rec.get("target_agent") or "").strip()
        hist_base = {
            "processed_at": _now_jst(),
            "target_agent": ta,
            "duplicate_key": dup_key,
            "source_queue": "ceo_reinject_apply_unlock_candidate_queue",
            "ceo_judgment": "ミュウツーCEO最終解放判定",
        }

        if not passed:
            blocked_n += 1
            _append_jsonl(UNLOCK_JUDGE_HISTORY_PATH, {
                **hist_base,
                "status": skip_status,
                "reason": skip_reason,
            })
            continue

        if dup_key in existing_dup_keys:
            dup_count += 1
            _append_jsonl(UNLOCK_JUDGE_HISTORY_PATH, {
                **hist_base,
                "status": "unlock_judge_duplicate",
                "reason": f"同一 duplicate_key が unlock_judge_queue に pending/archived で存在: {dup_key}",
            })
            continue

        existing_dup_keys.add(dup_key)

        nexec    = (rec.get("next_executor") or "ceo_config_executor.py").strip()
        priority = rec.get("priority", "")
        ppath    = (rec.get("patch_path") or "").strip()
        after_v  = (rec.get("after_value") or "").strip()

        judge_reason = (
            f"priority={priority} / execution_blocked=true / write_scope=queue_only / "
            f"patch_path valid / after_value {len(after_v)}文字 / "
            f"next_executor={nexec} / unlock_target=execution_blocked_toggle_only"
        )

        judge_rec = {
            "judged_at":              _now_jst(),
            "source_unlocked_at":     rec.get("unlocked_at", ""),
            "target_agent":           ta,
            "feedback_type":          rec.get("feedback_type", ""),
            "priority":               priority,
            "priority_score":         rec.get("priority_score", 0.0),
            "patch_path":             ppath,
            "after_value":            after_v,
            "next_executor":          nexec,
            "execution_blocked":      True,
            "write_scope":            "queue_only",
            "unlock_candidate_ready": True,
            "judge_ready":            True,
            "judge_status":           "pending",
            "judge_result":           "unlockable_if_unblocked",
            "judge_reason":           judge_reason,
            "unlock_target":          "execution_blocked_toggle_only",
            "duplicate_key":          dup_key,
            "source_queue":           "ceo_reinject_apply_unlock_candidate_queue",
            "ceo_judgment":           "ミュウツーCEO最終解放判定",
        }
        _append_jsonl(UNLOCK_JUDGE_QUEUE_PATH, judge_rec)
        _append_jsonl(UNLOCK_JUDGE_HISTORY_PATH, {
            **hist_base,
            "status": "promoted",
            "reason": judge_reason,
        })
        promoted += 1

    pending_total = sum(
        1 for r in _load_jsonl(UNLOCK_JUDGE_QUEUE_PATH)
        if r.get("judge_status") == "pending"
    )
    return {"promoted": promoted, "blocked": blocked_n, "dup": dup_count, "pending": pending_total}


def get_unlock_judge_stats() -> dict:
    recs     = _load_jsonl(UNLOCK_JUDGE_QUEUE_PATH)
    pending  = [r for r in recs if r.get("judge_status") == "pending"]
    hist     = _load_jsonl(UNLOCK_JUDGE_HISTORY_PATH)
    blocked  = [r for r in hist if (r.get("status") or "").startswith("blocked_")]

    critical_count = sum(1 for r in pending if r.get("priority") == "CRITICAL")
    high_count     = sum(1 for r in pending if r.get("priority") == "HIGH")

    sorted_p = sorted(pending, key=lambda r: (-float(r.get("priority_score", 0)), r.get("target_agent", "")))
    top1   = sorted_p[0] if sorted_p else {}
    latest = pending[-1] if pending else {}

    return {
        "unlock_judge_pending_count":   len(pending),
        "unlock_judge_critical_count":  critical_count,
        "unlock_judge_high_count":      high_count,
        "unlock_judge_blocked_count":   len(blocked),
        "unlock_judge_latest_agent":    latest.get("target_agent", "—"),
        "unlock_judge_latest_priority": latest.get("priority", "—"),
        "unlock_judge_latest_status":   latest.get("judge_status", "—"),
        "unlock_judge_top1_agent":      top1.get("target_agent", "—"),
        "unlock_judge_top1_score":      top1.get("priority_score", 0.0),
    }


def run_reinject_unlock_judge_cycle() -> dict:
    return promote_to_unlock_judge()
