#!/usr/bin/env python3
"""
ceo_hardening_alerts.py — hardening最優先集約 v1.0
CEO: ミュウツー / オーナー: 人間（閲覧専用）

【役割】
  hardening系4レーンを優先順位付きで集約し、CEOに1件だけ最優先issueを提示する。
  ceo_immediate_action / ceo_confidence の上書き条件も管理する。

【優先順位】
  1位 rollback_candidate pending
  2位 unlock_expiry expired
  3位 post_apply_lock pending
  4位 stale_operation pending
  5位 none

【制約】
  - config/agent_directives.json への書き込みなし
  - LLM 判断なし
  - append-only なし（読み取り専用）
"""

from __future__ import annotations

import json
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"

UNLOCK_EXPIRY_QUEUE_PATH    = LOGS / "ceo_unlock_expiry_queue.jsonl"
POST_APPLY_LOCK_QUEUE_PATH  = LOGS / "ceo_post_apply_lock_queue.jsonl"
ROLLBACK_REQUEST_QUEUE_PATH  = LOGS / "ceo_rollback_request_queue.jsonl"
STALE_OP_QUEUE_PATH          = LOGS / "ceo_stale_operation_queue.jsonl"
INVARIANT_VIOLATION_QUEUE    = LOGS / "ceo_invariant_violation_queue.jsonl"
ROLLBACK_DISPATCH_QUEUE      = LOGS / "ceo_rollback_dispatch_queue.jsonl"

PRIORITY_ORDER = [
    "rollback_candidate",
    "unlock_expiry_expired",
    "post_apply_lock",
    "stale_operation",
    "none",
]


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
# 最優先判定
# ════════════════════════════════════════════════════════════════════

def compute_hardening_alert() -> dict:
    """
    hardening系4レーンから最優先 issue を1件返す。

    戻り値:
      {
        hardening_top_issue: str,
        hardening_top_priority: str ("HIGH"|"MEDIUM"|"LOW"|"NONE"),
        hardening_top_target: str,
        hardening_required_action: str,
        hardening_required_command: str,
        hardening_block_count: int,
        hardening_attention_count: int,
        hardening_is_escalated: bool,
        hardening_escalation_reason: str,
        hardening_override_immediate_action: str | None,
        hardening_override_confidence: str | None,
      }
    """
    rollback_recs   = _load_jsonl(ROLLBACK_REQUEST_QUEUE_PATH)
    expiry_recs     = _load_jsonl(UNLOCK_EXPIRY_QUEUE_PATH)
    postlock_recs   = _load_jsonl(POST_APPLY_LOCK_QUEUE_PATH)
    stale_recs      = _load_jsonl(STALE_OP_QUEUE_PATH)
    violation_recs  = _load_jsonl(INVARIANT_VIOLATION_QUEUE)
    dispatch_recs   = _load_jsonl(ROLLBACK_DISPATCH_QUEUE)

    rb_pending       = [r for r in rollback_recs if r.get("rollback_status") == "pending"]
    exp_pending      = [r for r in expiry_recs   if r.get("expiry_status") == "expired"]
    pl_pending       = [r for r in postlock_recs if r.get("status") == "pending"]
    stale_pending    = [r for r in stale_recs    if r.get("status") == "pending"]
    violations       = [r for r in violation_recs if r.get("violation_status") == "pending"]
    dispatch_pending = [r for r in dispatch_recs  if r.get("router_status") == "pending"]

    block_count     = len(rb_pending) + len(violations) + len(dispatch_pending)
    attention_count = len(exp_pending) + len(pl_pending) + len(stale_pending)

    # ── 優先順位に従い top issue を決定 ─────────────────
    if violations:
        top_rec  = violations[-1]
        ta       = top_rec.get("target_agent", "—")
        issue    = "invariant_violation"
        priority = "HIGH"
        action   = f"安全不変条件違反: {top_rec.get('rule','—')} — {top_rec.get('detail','')[:60]}"
        command  = "bash run_agent_monitor.sh  # 違反確認後に手動対応"
        esc_reason = f"不変条件違反 {len(violations)}件 rule={top_rec.get('rule','—')}"
        is_escalated = True
        override_action = action
        override_confidence = "HIGH"

    elif dispatch_pending:
        top_rec  = dispatch_pending[-1]
        ta       = top_rec.get("target_agent", "—")
        issue    = "rollback_dispatch"
        priority = "HIGH"
        action   = f"{ta} 即時rollback確認: {top_rec.get('route_reason','')}"
        command  = top_rec.get("rollback_command", f"python3 lib/ceo_config_executor.py rollback {ta}")
        esc_reason = f"rollback_dispatch pending {len(dispatch_pending)}件"
        is_escalated = True
        override_action = action
        override_confidence = "HIGH"

    elif rb_pending:
        top_rec  = rb_pending[-1]
        ta       = top_rec.get("target_agent", "—")
        issue    = "rollback_candidate"
        priority = "HIGH"
        action   = f"{ta} への直前変更をロールバック候補として確認"
        command  = f"python3 lib/ceo_config_executor.py rollback {ta}"
        esc_reason = f"rollback候補 {len(rb_pending)}件あり — 即時確認が必要"
        is_escalated = True
        override_action = action
        override_confidence = "HIGH"

    elif exp_pending:
        top_rec  = exp_pending[-1]
        ta       = top_rec.get("target_agent", "—")
        issue    = "unlock_expiry_expired"
        priority = "HIGH"
        action   = f"{ta} の unlock 有効期限切れ — 再 unlock が必要"
        command  = "bash run_agent_monitor.sh"
        esc_reason = f"unlock期限切れ {len(exp_pending)}件"
        is_escalated = True
        override_action = action
        override_confidence = "HIGH"

    elif pl_pending:
        top_rec  = pl_pending[-1]
        ta       = top_rec.get("target_agent", "—")
        issue    = "post_apply_lock"
        priority = "MEDIUM"
        action   = f"{ta} の apply後監視 — execution_blocked 再設定を検討"
        command  = "bash run_agent_monitor.sh"
        esc_reason = f"post-apply lock候補 {len(pl_pending)}件"
        is_escalated = False
        override_action = None
        override_confidence = None

    elif stale_pending:
        top_rec  = stale_pending[-1]
        ta       = top_rec.get("target_agent", "—")
        issue    = "stale_operation"
        priority = "MEDIUM"
        action   = f"{ta} の放置操作を確認・処理"
        command  = "bash run_agent_monitor.sh"
        esc_reason = f"stale operation {len(stale_pending)}件"
        is_escalated = False
        override_action = None
        override_confidence = None

    else:
        issue    = "none"
        priority = "NONE"
        ta       = "—"
        action   = "異常なし"
        command  = "bash run_agent_monitor.sh"
        esc_reason = ""
        is_escalated = False
        override_action = None
        override_confidence = None

    return {
        "hardening_top_issue":               issue,
        "hardening_top_priority":            priority,
        "hardening_top_target":              ta,
        "hardening_required_action":         action,
        "hardening_required_command":        command,
        "hardening_block_count":             block_count,
        "hardening_attention_count":         attention_count,
        "hardening_is_escalated":            is_escalated,
        "hardening_escalation_reason":       esc_reason,
        "hardening_override_immediate_action": override_action,
        "hardening_override_confidence":     override_confidence,
        # 各件数（dashboard 用）
        "_rb_count":         len(rb_pending),
        "_exp_count":        len(exp_pending),
        "_pl_count":         len(pl_pending),
        "_stale_count":      len(stale_pending),
        "_violation_count":  len(violations),
        "_dispatch_count":   len(dispatch_pending),
    }


def get_hardening_alert_summary() -> dict:
    """dashboard_summary.json に追加するフィールドのみ返す（_ prefix なし）"""
    r = compute_hardening_alert()
    return {k: v for k, v in r.items() if not k.startswith("_")}


if __name__ == "__main__":
    import json as _json
    result = compute_hardening_alert()
    print(_json.dumps(result, ensure_ascii=False, indent=2))
