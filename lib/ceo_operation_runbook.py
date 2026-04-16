#!/usr/bin/env python3
"""
ceo_operation_runbook.py — 本番運用手順ガイド v1.0
CEO: ミュウツー / オーナー: 人間（閲覧専用）

【役割】
  unlock → apply → 観測 → rollback の状態機械を決定論で管理し、
  次に打つべきコマンドを常に1本生成する。

【制約】
  - config/agent_directives.json への書き込みなし
  - execution_blocked を自動で false にしない
  - apply を自動実行しない
  - LLM 判断なし
  - append-only
"""

from __future__ import annotations

import json
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"

UNLOCK_EXECUTE_QUEUE_PATH  = LOGS / "ceo_unlock_execute_queue.jsonl"
APPLY_EXECUTE_QUEUE_PATH   = LOGS / "ceo_apply_execute_queue.jsonl"
APPLY_EXECUTE_RESULT_PATH  = LOGS / "ceo_apply_execute_result_queue.jsonl"
POST_APPLY_LOCK_QUEUE_PATH = LOGS / "ceo_post_apply_lock_queue.jsonl"
ROLLBACK_REQUEST_QUEUE_PATH= LOGS / "ceo_rollback_request_queue.jsonl"
STALE_OP_QUEUE_PATH        = LOGS / "ceo_stale_operation_queue.jsonl"
UNLOCK_EXPIRY_QUEUE_PATH   = LOGS / "ceo_unlock_expiry_queue.jsonl"
ROLLBACK_DISPATCH_QUEUE    = LOGS / "ceo_rollback_dispatch_queue.jsonl"
INVARIANT_VIOLATION_QUEUE  = LOGS / "ceo_invariant_violation_queue.jsonl"


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


# ════════════════════════════════════════════════════════════════════
# 状態機械: stage 決定
# ════════════════════════════════════════════════════════════════════

STAGES = {
    "unlock_ready":      "unlock_ready",
    "apply_ready":       "apply_ready",
    "observe_post_apply":"observe_post_apply",
    "rollback_ready":    "rollback_ready",
    "monitor_only":      "monitor_only",
}


def compute_operation_stage() -> dict:
    """
    現在のキュー状態から運用 stage を決定し、next_required_command 等を返す。

    戻り値:
      {
        current_operation_stage: str,
        next_required_command: str,
        next_required_target: str,
        rollback_command: str,
        operation_block_reason: str,
        operation_confidence: "HIGH"|"MEDIUM"|"LOW",
        top_unlock_candidate: dict,
        top_rollback_candidate: dict,
      }
    """
    unlock_recs    = _load_jsonl(UNLOCK_EXECUTE_QUEUE_PATH)
    apply_recs     = _load_jsonl(APPLY_EXECUTE_QUEUE_PATH)
    apply_results  = _load_jsonl(APPLY_EXECUTE_RESULT_PATH)
    post_lock_recs = _load_jsonl(POST_APPLY_LOCK_QUEUE_PATH)
    rollback_recs  = _load_jsonl(ROLLBACK_REQUEST_QUEUE_PATH)
    stale_recs     = _load_jsonl(STALE_OP_QUEUE_PATH)
    expiry_recs    = _load_jsonl(UNLOCK_EXPIRY_QUEUE_PATH)

    # ── 状態集計 ─────────────────────────────────────────
    unlock_pending   = [r for r in unlock_recs if r.get("unlock_status") == "pending"]
    unlocked         = [r for r in unlock_recs if r.get("unlock_status") == "unlocked"
                        and r.get("actual_unlocked") is True]
    apply_pending    = [r for r in apply_recs   if r.get("apply_execute_status") == "pending"]
    applied_results  = [r for r in apply_results if r.get("result_status") == "applied"]
    postlock_pending = [r for r in post_lock_recs if r.get("status") == "pending"]
    rollback_pending = [r for r in rollback_recs  if r.get("rollback_status") == "pending"]
    stale_pending    = [r for r in stale_recs      if r.get("status") == "pending"]
    expired          = [r for r in expiry_recs     if r.get("expiry_status") == "expired"]

    # ── rollback候補: 最新pending ─────────────────────────
    top_rollback = rollback_pending[-1] if rollback_pending else {}
    rb_agent = top_rollback.get("target_agent", "")
    rollback_command = (
        f"python3 lib/ceo_config_executor.py rollback {rb_agent}"
        if rb_agent else ""
    )

    # ── unlock候補トップ ─────────────────────────────────
    sorted_unlock = sorted(
        unlock_pending,
        key=lambda r: (-float(r.get("priority_score", 0)), r.get("target_agent", ""))
    )
    top_unlock = sorted_unlock[0] if sorted_unlock else {}
    ul_agent   = top_unlock.get("target_agent", "")
    ul_dup_key = top_unlock.get("duplicate_key", "<duplicate_key>")

    # ── stage 決定（優先順位） ───────────────────────────
    if rollback_pending:
        stage       = "rollback_ready"
        next_cmd    = f"python3 lib/ceo_config_executor.py rollback {rb_agent}"
        next_target = rb_agent
        block_reason= f"rollback候補 {len(rollback_pending)}件あり"
        confidence  = "HIGH"

    elif unlock_pending and not unlocked and not apply_pending:
        stage       = "unlock_ready"
        next_cmd    = f"python3 lib/ceo_unlock_executor.py unlock {ul_dup_key}"
        next_target = ul_agent
        block_reason= "unlock候補あり / apply未実行"
        confidence  = "HIGH"

    elif (unlocked or apply_pending) and apply_pending:
        stage       = "apply_ready"
        top_apply   = apply_pending[0] if apply_pending else {}
        next_cmd    = "python3 lib/ceo_unlock_executor.py apply"
        next_target = top_apply.get("target_agent", "")
        block_reason= f"apply実行待ち {len(apply_pending)}件"
        confidence  = "HIGH"

    elif applied_results and postlock_pending:
        stage       = "observe_post_apply"
        next_cmd    = "bash run_agent_monitor.sh"
        next_target = postlock_pending[-1].get("target_agent", "")
        block_reason= f"apply完了 / post-apply監視 {len(postlock_pending)}件"
        confidence  = "MEDIUM"

    elif stale_pending or expired:
        stage       = "monitor_only"
        next_cmd    = "bash run_agent_monitor.sh"
        next_target = (stale_pending[-1].get("target_agent", "") if stale_pending
                       else expired[-1].get("target_agent", ""))
        block_reason= (
            f"stale operation {len(stale_pending)}件" if stale_pending
            else f"unlock期限切れ {len(expired)}件"
        )
        confidence  = "MEDIUM"

    else:
        stage       = "monitor_only"
        next_cmd    = "bash run_agent_monitor.sh"
        next_target = ""
        block_reason= "unlock候補なし / 処理待ちなし"
        confidence  = "LOW"

    return {
        "current_operation_stage":  stage,
        "next_required_command":    next_cmd,
        "next_required_target":     next_target,
        "rollback_command":         rollback_command,
        "operation_block_reason":   block_reason,
        "operation_confidence":     confidence,
        "top_unlock_candidate":     top_unlock,
        "top_rollback_candidate":   top_rollback,
    }


def get_operation_summary() -> dict:
    """dashboard_summary.json に追加するフィールドを返す"""
    result = compute_operation_stage()
    return {
        "current_operation_stage":   result["current_operation_stage"],
        "next_required_command":     result["next_required_command"],
        "next_required_target":      result["next_required_target"],
        "rollback_command":          result["rollback_command"],
        "operation_block_reason":    result["operation_block_reason"],
        "operation_confidence":      result["operation_confidence"],
    }


# ════════════════════════════════════════════════════════════════════
# Phase 24: one-command summary (今打つべき1コマンドに絞る)
# ════════════════════════════════════════════════════════════════════

def compute_next_command_summary(hardening_summary: dict | None = None) -> dict:
    """
    operation_runbook と hardening_alerts を統合し、
    今打つべき1コマンドを優先順位で決定する。

    優先順位:
      1. rollback_dispatch pending (dispatch_count > 0)
      2. invariant_violation pending
      3. unlock_ready pending
      4. apply_ready pending
      5. post_apply_lock pending
      6. stale cleanup
      7. monitor only

    hardening が ESCALATED の場合は必ず上書き。
    """
    unlock_recs     = _load_jsonl(UNLOCK_EXECUTE_QUEUE_PATH)
    apply_recs      = _load_jsonl(APPLY_EXECUTE_QUEUE_PATH)
    post_lock_recs  = _load_jsonl(POST_APPLY_LOCK_QUEUE_PATH)
    rollback_recs   = _load_jsonl(ROLLBACK_REQUEST_QUEUE_PATH)
    stale_recs      = _load_jsonl(STALE_OP_QUEUE_PATH)
    dispatch_recs   = _load_jsonl(ROLLBACK_DISPATCH_QUEUE)
    violation_recs  = _load_jsonl(INVARIANT_VIOLATION_QUEUE)

    unlock_pending    = [r for r in unlock_recs    if r.get("unlock_status") == "pending"]
    apply_pending     = [r for r in apply_recs     if r.get("apply_execute_status") == "pending"]
    postlock_pending  = [r for r in post_lock_recs if r.get("status") == "pending"]
    rollback_pending  = [r for r in rollback_recs  if r.get("rollback_status") == "pending"]
    stale_pending     = [r for r in stale_recs     if r.get("status") == "pending"]
    dispatch_pending  = [r for r in dispatch_recs  if r.get("router_status") == "pending"]
    violations        = [r for r in violation_recs if r.get("violation_status") == "pending"]

    # hardening escalated 上書き条件チェック
    if hardening_summary and hardening_summary.get("hardening_is_escalated"):
        ha_cmd    = hardening_summary.get("hardening_required_command", "bash run_agent_monitor.sh")
        ha_target = hardening_summary.get("hardening_top_target", "—")
        ha_reason = hardening_summary.get("hardening_escalation_reason", "")
        return {
            "ceo_next_command":  ha_cmd,
            "ceo_next_target":   ha_target,
            "ceo_next_reason":   f"[HARDENING ESCALATED] {ha_reason}",
            "ceo_next_priority": "HIGH",
            "ceo_next_stage":    "hardening_escalated",
        }

    if violations:
        v = violations[-1]
        ta = v.get("target_agent", "—")
        return {
            "ceo_next_command":  "bash run_agent_monitor.sh  # 不変条件違反を手動確認",
            "ceo_next_target":   ta,
            "ceo_next_reason":   f"不変条件違反 {len(violations)}件: {v.get('rule','—')}",
            "ceo_next_priority": "HIGH",
            "ceo_next_stage":    "invariant_violation",
        }

    if dispatch_pending:
        d = dispatch_pending[-1]
        ta = d.get("target_agent", "—")
        return {
            "ceo_next_command":  d.get("rollback_command", f"python3 lib/ceo_config_executor.py rollback {ta}"),
            "ceo_next_target":   ta,
            "ceo_next_reason":   f"rollback dispatch pending {len(dispatch_pending)}件: {d.get('route_reason','')}",
            "ceo_next_priority": "HIGH",
            "ceo_next_stage":    "rollback_dispatch",
        }

    if rollback_pending:
        r = rollback_pending[-1]
        ta = r.get("target_agent", "—")
        return {
            "ceo_next_command":  f"python3 lib/ceo_config_executor.py rollback {ta}",
            "ceo_next_target":   ta,
            "ceo_next_reason":   f"rollback候補 {len(rollback_pending)}件",
            "ceo_next_priority": "HIGH",
            "ceo_next_stage":    "rollback_ready",
        }

    if unlock_pending:
        sorted_ul = sorted(unlock_pending,
                           key=lambda r: (-float(r.get("priority_score", 0)), r.get("target_agent", "")))
        ul = sorted_ul[0]
        ta = ul.get("target_agent", "—")
        dup_key = ul.get("duplicate_key", "<dup_key>")
        return {
            "ceo_next_command":  f"python3 lib/ceo_unlock_executor.py unlock {dup_key}",
            "ceo_next_target":   ta,
            "ceo_next_reason":   f"unlock候補 {len(unlock_pending)}件",
            "ceo_next_priority": "HIGH",
            "ceo_next_stage":    "unlock_ready",
        }

    if apply_pending:
        ap = apply_pending[0]
        ta = ap.get("target_agent", "—")
        return {
            "ceo_next_command":  "python3 lib/ceo_unlock_executor.py apply",
            "ceo_next_target":   ta,
            "ceo_next_reason":   f"apply待ち {len(apply_pending)}件",
            "ceo_next_priority": "HIGH",
            "ceo_next_stage":    "apply_ready",
        }

    if postlock_pending:
        pl = postlock_pending[-1]
        ta = pl.get("target_agent", "—")
        return {
            "ceo_next_command":  "bash run_agent_monitor.sh",
            "ceo_next_target":   ta,
            "ceo_next_reason":   f"post-apply監視 {len(postlock_pending)}件",
            "ceo_next_priority": "MEDIUM",
            "ceo_next_stage":    "observe_post_apply",
        }

    if stale_pending:
        st = stale_pending[-1]
        ta = st.get("target_agent", "—")
        return {
            "ceo_next_command":  "bash run_agent_monitor.sh",
            "ceo_next_target":   ta,
            "ceo_next_reason":   f"stale操作 {len(stale_pending)}件",
            "ceo_next_priority": "MEDIUM",
            "ceo_next_stage":    "stale_cleanup",
        }

    return {
        "ceo_next_command":  "bash run_agent_monitor.sh",
        "ceo_next_target":   "—",
        "ceo_next_reason":   "異常なし / 通常監視",
        "ceo_next_priority": "LOW",
        "ceo_next_stage":    "monitor_only",
    }


if __name__ == "__main__":
    import json as _json
    result = compute_operation_stage()
    print(_json.dumps(result, ensure_ascii=False, indent=2))
