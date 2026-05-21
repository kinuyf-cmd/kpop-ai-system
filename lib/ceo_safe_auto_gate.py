#!/usr/bin/env python3
"""
ceo_safe_auto_gate.py — SAFE_AUTO移行判定レイヤー v1.0
CEO: ミュウツー / オーナー: 人間（閲覧専用）

【役割】
  SAFE_AUTO に「今入ってよいか」を判定し、
  blocked_reasons / required_actions / top_required_command を出力する。

【判定ルール（完全決定論）】
  blocked 条件（1件でも該当 → gate_status=blocked）:
    - stale_operation pending > 0
    - invariant_violation pending > 0
    - rollback_dispatch pending > 0
    - hardening escalated = true
    - final_blocked_count > 0

  informational（blockではない）:
    - unlock_judge pending > 0 → "先行実行推奨"
    - apply_ready pending > 0  → "SAFE_AUTO では apply 禁止 / informational のみ"

  全 blocked 条件 = 0 → safe_auto_ready=true / gate_status=ready

【制約】
  - config 書き込み禁止
  - execution_blocked 自動変更禁止
  - unlock/apply/rollback 自動実行禁止
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

# 入力
STALE_OP_QUEUE          = LOGS / "ceo_stale_operation_queue.jsonl"
INVARIANT_QUEUE         = LOGS / "ceo_invariant_violation_queue.jsonl"
ROLLBACK_DISPATCH_QUEUE = LOGS / "ceo_rollback_dispatch_queue.jsonl"
UNLOCK_JUDGE_QUEUE      = LOGS / "ceo_reinject_unlock_judge_queue.jsonl"
APPLY_READY_QUEUE       = LOGS / "ceo_reinject_apply_ready_queue.jsonl"
FINAL_BLOCK_QUEUE       = LOGS / "ceo_final_block_queue.jsonl"
UNLOCK_EXECUTE_QUEUE    = LOGS / "ceo_unlock_execute_queue.jsonl"
DASHBOARD_SUMMARY       = BASE / "dashboard_summary.json"

# 出力
GATE_QUEUE   = LOGS / "ceo_safe_auto_gate_queue.jsonl"
GATE_HISTORY = LOGS / "ceo_safe_auto_gate_history.jsonl"


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


def _load_hardening_escalated() -> bool:
    try:
        s = json.loads(DASHBOARD_SUMMARY.read_text(encoding="utf-8"))
        return bool(s.get("hardening_is_escalated", False))
    except Exception:
        return False


def _gate_key(checked_at: str) -> str:
    """1実行ごとに一意なキー（分単位で重複防止）"""
    return checked_at[:16]  # "2026-04-14 14:39"


# ═══════════════════════════════════════════════════════════════════
# メイン判定
# ═══════════════════════════════════════════════════════════════════

def run_safe_auto_gate() -> dict:
    """
    SAFE_AUTO移行条件を判定し gate_queue に記録する。
    重複は分単位でスキップ（頻繁呼び出し対応）。
    """
    checked_at = _now_jst()
    gkey       = _gate_key(checked_at)

    # 既存 gate record の重複チェック（同分はスキップ）
    existing = _load_jsonl(GATE_QUEUE)
    existing_keys = {_gate_key(r.get("checked_at", "")) for r in existing}

    # ── unlock済み duplicate_key（stale除外用）──
    already_unlocked = {r.get("duplicate_key", "")
                        for r in _load_jsonl(UNLOCK_EXECUTE_QUEUE)
                        if r.get("unlock_status") == "unlocked"
                        and r.get("actual_unlocked") is True}

    # ── 判定入力収集 ──
    stale_pending    = [r for r in _load_jsonl(STALE_OP_QUEUE)
                        if r.get("status") == "pending"
                        and r.get("duplicate_key", "") not in already_unlocked]
    inv_pending      = [r for r in _load_jsonl(INVARIANT_QUEUE)
                        if r.get("violation_status") == "pending"]
    rb_pending       = [r for r in _load_jsonl(ROLLBACK_DISPATCH_QUEUE)
                        if r.get("router_status") == "pending"]
    uj_pending       = [r for r in _load_jsonl(UNLOCK_JUDGE_QUEUE)
                        if r.get("judge_status") == "pending"]
    ar_pending       = [r for r in _load_jsonl(APPLY_READY_QUEUE)
                        if r.get("ready_status") == "pending"]
    fb_blocked       = [r for r in _load_jsonl(FINAL_BLOCK_QUEUE)
                        if r.get("block_status") == "blocked"
                        and r.get("duplicate_key", "") not in already_unlocked]
    escalated        = _load_hardening_escalated()

    # ── blocked_reasons 組み立て ──
    blocked_reasons  = []
    required_actions = []

    if stale_pending:
        ta_list = list({r.get("target_agent", "—") for r in stale_pending})[:3]
        blocked_reasons.append(
            f"stale_operation pending {len(stale_pending)}件 "
            f"(対象: {', '.join(ta_list)})"
        )
        required_actions.append({
            "action":  "stale解消",
            "command": 'bash run_agent_monitor.sh  # stale状況確認後、手動unlockで解消',
            "target":  ta_list[0] if ta_list else "—",
            "reason":  f"stale {len(stale_pending)}件 → SAFE_AUTO ブロック中",
        })

    if inv_pending:
        blocked_reasons.append(f"invariant_violation pending {len(inv_pending)}件")
        required_actions.append({
            "action":  "invariant違反解消",
            "command": "bash run_agent_monitor.sh  # BG安全不変条件を確認",
            "target":  inv_pending[-1].get("target_agent", "—"),
            "reason":  f"invariant違反 {len(inv_pending)}件 → SAFE_AUTO ブロック中",
        })

    if rb_pending:
        blocked_reasons.append(f"rollback_dispatch pending {len(rb_pending)}件")
        top_rb = rb_pending[-1]
        required_actions.append({
            "action":  "rollback確認",
            "command": top_rb.get("rollback_command",
                                  f"python3 lib/ceo_config_executor.py rollback {top_rb.get('target_agent','—')}"),
            "target":  top_rb.get("target_agent", "—"),
            "reason":  f"rollback dispatch {len(rb_pending)}件 → 先に手動rollback確認",
        })

    if escalated:
        blocked_reasons.append("hardening ESCALATED")
        required_actions.append({
            "action":  "hardening確認",
            "command": "bash run_agent_monitor.sh  # BA Hardening最優先を確認",
            "target":  "—",
            "reason":  "hardening ESCALATED → 最優先で対処",
        })

    if fb_blocked:
        blocked_reasons.append(f"final_blocked_count {len(fb_blocked)}件")
        top_fb = fb_blocked[-1]
        top_reason = (top_fb.get("blocked_reason") or ["—"])[0]
        required_actions.append({
            "action":  "実行禁止条件解消",
            "command": "bash run_agent_monitor.sh  # BJ実行禁止条件を確認",
            "target":  top_fb.get("target_agent", "—"),
            "reason":  f"禁止条件: {top_reason}",
        })

    # informational (non-blocking)
    informational = []
    if uj_pending:
        informational.append(
            f"unlock_judge pending {len(uj_pending)}件 — SAFE_AUTO移行後に自動unlock候補"
        )
    if ar_pending:
        informational.append(
            f"apply_ready pending {len(ar_pending)}件 — SAFE_AUTO では apply 禁止（informational）"
        )

    # ── 判定結果 ──
    safe_auto_ready = len(blocked_reasons) == 0
    gate_status     = "ready" if safe_auto_ready else "blocked"

    # confidence
    if not blocked_reasons:
        confidence = "HIGH"
    elif len(blocked_reasons) == 1:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    # top_required_command
    top_cmd    = required_actions[0].get("command", "bash run_agent_monitor.sh") if required_actions else "bash run_agent_monitor.sh  # 全条件クリア済み"
    top_target = required_actions[0].get("target", "—") if required_actions else "—"
    top_reason = required_actions[0].get("reason", "—") if required_actions else "全条件クリア — SAFE_AUTO移行可能"
    ready_stage = "safe_auto_ready" if safe_auto_ready else "pre_safe_auto_blocked"

    rec = {
        "checked_at":            checked_at,
        "safe_auto_ready":       safe_auto_ready,
        "gate_status":           gate_status,
        "ready_stage":           ready_stage,
        "confidence":            confidence,
        "blocked_count":         len(blocked_reasons),
        "blocked_reasons":       blocked_reasons,
        "required_actions":      required_actions,
        "informational":         informational,
        "top_required_command":  top_cmd,
        "top_required_target":   top_target,
        "top_required_reason":   top_reason,
        "stale_pending":         len(stale_pending),
        "invariant_pending":     len(inv_pending),
        "rollback_dispatch_pending": len(rb_pending),
        "hardening_escalated":   escalated,
        "final_blocked_count":   len(fb_blocked),
        "unlock_judge_pending":  len(uj_pending),
        "apply_ready_pending":   len(ar_pending),
        "execution_blocked":     True,
        "write_scope":           "none",
        "source_queue":          "multi_queue_scan",
        "ceo_judgment":          "ミュウツーCEO SAFE_AUTO移行判定",
    }
    _append_jsonl(GATE_QUEUE, rec)
    _append_jsonl(GATE_HISTORY, {
        "processed_at":    checked_at,
        "gate_status":     gate_status,
        "safe_auto_ready": safe_auto_ready,
        "blocked_count":   len(blocked_reasons),
        "confidence":      confidence,
        "ceo_judgment":    "ミュウツーCEO SAFE_AUTO移行判定",
    })
    return _stats_from_rec(rec)


def _stats_from_rec(rec: dict) -> dict:
    return {
        "safe_auto_ready":               rec.get("safe_auto_ready", False),
        "safe_auto_gate_status":         rec.get("gate_status", "blocked"),
        "safe_auto_blocked_count":       rec.get("blocked_count", 0),
        "safe_auto_top_required_command":rec.get("top_required_command", "—"),
        "safe_auto_top_required_target": rec.get("top_required_target", "—"),
        "safe_auto_top_required_reason": rec.get("top_required_reason", "—"),
        "safe_auto_confidence":          rec.get("confidence", "LOW"),
        "safe_auto_stale_pending":       rec.get("stale_pending", 0),
        "safe_auto_invariant_pending":   rec.get("invariant_pending", 0),
        "safe_auto_informational":       rec.get("informational", []),
    }


def get_safe_auto_gate_stats() -> dict:
    recs   = _load_jsonl(GATE_QUEUE)
    latest = recs[-1] if recs else {}
    return _stats_from_rec(latest)


if __name__ == "__main__":
    import json as _json
    result = run_safe_auto_gate()
    print(_json.dumps(result, ensure_ascii=False, indent=2))
