#!/usr/bin/env python3
"""
ceo_manual_explain.py — 手動実行前最終説明・禁止条件・実行後チェックリスト v1.0
CEO: ミュウツー / オーナー: 人間（閲覧専用）

【役割】
  1. unlock対象の手動実行前説明レーン（ceo_unlock_explain_queue）
  2. apply候補の手動実行前説明レーン（ceo_apply_explain_queue）
  3. 実行禁止条件の可視化（ceo_final_block_queue）
  4. 手動操作後の確認チェックリスト生成（ceo_post_command_checklist_queue）

【制約】
  - unlock / apply / rollback 自動実行禁止
  - config/agent_directives.json 書き込み禁止
  - execution_blocked を自動で false にしない
  - write_scope は queue_only のまま
  - append-only
  - LLM 判断なし
  - duplicate_key 重複防止あり
"""

from __future__ import annotations

import json
import hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"
JST  = timezone(timedelta(hours=9))

# 入力キュー
UNLOCK_EXECUTE_QUEUE_PATH       = LOGS / "ceo_unlock_execute_queue.jsonl"
APPLY_EXECUTE_QUEUE_PATH        = LOGS / "ceo_apply_execute_queue.jsonl"
APPLY_EXECUTE_RESULT_PATH       = LOGS / "ceo_apply_execute_result_queue.jsonl"
INVARIANT_VIOLATION_QUEUE_PATH  = LOGS / "ceo_invariant_violation_queue.jsonl"
STALE_OP_QUEUE_PATH             = LOGS / "ceo_stale_operation_queue.jsonl"
PATCH_PLAN_QUEUE_PATH           = LOGS / "ceo_config_patch_plan_queue.jsonl"

# 出力キュー
UNLOCK_EXPLAIN_QUEUE    = LOGS / "ceo_unlock_explain_queue.jsonl"
UNLOCK_EXPLAIN_HISTORY  = LOGS / "ceo_unlock_explain_history.jsonl"
APPLY_EXPLAIN_QUEUE     = LOGS / "ceo_apply_explain_queue.jsonl"
APPLY_EXPLAIN_HISTORY   = LOGS / "ceo_apply_explain_history.jsonl"
FINAL_BLOCK_QUEUE       = LOGS / "ceo_final_block_queue.jsonl"
FINAL_BLOCK_HISTORY     = LOGS / "ceo_final_block_history.jsonl"
CHECKLIST_QUEUE         = LOGS / "ceo_post_command_checklist_queue.jsonl"
CHECKLIST_HISTORY       = LOGS / "ceo_post_command_checklist_history.jsonl"


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


def _explain_key(prefix: str, dup_key: str) -> str:
    return f"{prefix}|{dup_key}"


# ═══════════════════════════════════════════════════════════════════
# 1. unlock 前説明レーン
# ═══════════════════════════════════════════════════════════════════

def run_unlock_explain() -> dict:
    """
    unlock_execute_queue の pending レコードごとに
    手動実行前説明を生成して ceo_unlock_explain_queue に記録する。
    """
    already_unlocked = {r.get("duplicate_key", "")
                        for r in _load_jsonl(UNLOCK_EXECUTE_QUEUE_PATH)
                        if r.get("unlock_status") == "unlocked"
                        and r.get("actual_unlocked") is True}
    unlock_recs = [r for r in _load_jsonl(UNLOCK_EXECUTE_QUEUE_PATH)
                   if r.get("unlock_status") == "pending"
                   and r.get("duplicate_key", "") not in already_unlocked]

    existing_explain = {r.get("explain_key", "")
                        for r in _load_jsonl(UNLOCK_EXPLAIN_QUEUE)
                        if r.get("explain_status") in ("pending", "explained")}

    added = 0
    dup   = 0

    for rec in unlock_recs:
        dup_key = rec.get("duplicate_key", "")
        ta      = rec.get("target_agent", "—")
        ekey    = _explain_key("unlock", dup_key)

        if ekey in existing_explain:
            dup += 1
            continue

        existing_explain.add(ekey)

        patch_path   = rec.get("patch_path", "—")
        after_value  = rec.get("after_value", "")
        agent_key    = rec.get("agent_key", "")
        prio         = rec.get("priority", "HIGH")
        prio_score   = rec.get("priority_score", 0.0)
        fb_type      = rec.get("feedback_type", "—")

        # 打つべきコマンド
        next_cmd = f'python3 lib/ceo_unlock_executor.py unlock "{dup_key}"'

        # rollback コマンド（失敗時）
        rollback_cmd = (
            f"python3 lib/ceo_config_executor.py rollback {ta}  "
            f"# unlock失敗時は元のexecution_blocked=trueに戻す"
        )

        # 何から何へ遷移するか
        transitions = [
            "unlock_execute_queue: pending → unlocked",
            "apply_execute_queue: 新規 pending レコード生成",
            "execution_blocked: true → false（unlock実行後に手動確認要）",
        ]

        # なぜ今これが1位なのか
        why_now = (
            f"priority={prio}(score={prio_score:.4f}), feedback_type={fb_type}, "
            f"agent={ta} が再投入→解放判定を通過して unlock_execute 最上位に到達したため"
        )

        explain_rec = {
            "explained_at":        _now_jst(),
            "explain_key":         ekey,
            "duplicate_key":       dup_key,
            "target_agent":        ta,
            "agent_key":           agent_key,
            "priority":            prio,
            "priority_score":      prio_score,
            "patch_path":          patch_path,
            "after_value":         after_value[:200],
            "feedback_type":       fb_type,
            "explain_type":        "unlock_explain",
            "explain_status":      "pending",
            "why_now":             why_now,
            "next_manual_command": next_cmd,
            "rollback_command":    rollback_cmd,
            "expected_next_stage": "apply_ready",
            "current_stage":       "unlock_ready",
            "what_changes":        "; ".join(transitions),
            "execution_blocked":   True,
            "write_scope":         "queue_only",
            "backup_required":     True,
            "source_queue":        "ceo_unlock_execute_queue",
            "ceo_judgment":        "ミュウツーCEO unlock前最終説明",
        }
        _append_jsonl(UNLOCK_EXPLAIN_QUEUE, explain_rec)
        _append_jsonl(UNLOCK_EXPLAIN_HISTORY, {
            "processed_at":  _now_jst(),
            "explain_key":   ekey,
            "target_agent":  ta,
            "duplicate_key": dup_key,
            "status":        "explained",
            "ceo_judgment":  "ミュウツーCEO unlock前最終説明",
        })
        added += 1

    pending = [r for r in _load_jsonl(UNLOCK_EXPLAIN_QUEUE)
               if r.get("explain_status") == "pending"]
    return {"added": added, "dup": dup, "pending": len(pending)}


# ═══════════════════════════════════════════════════════════════════
# 2. apply 前説明レーン
# ═══════════════════════════════════════════════════════════════════

def run_apply_explain() -> dict:
    """
    apply_execute_queue の pending レコードごとに
    apply前説明を生成して ceo_apply_explain_queue に記録する。
    """
    already_applied = {r.get("duplicate_key", "")
                       for r in _load_jsonl(APPLY_EXECUTE_RESULT_PATH)
                       if r.get("result_status") == "applied"}
    apply_recs = [r for r in _load_jsonl(APPLY_EXECUTE_QUEUE_PATH)
                  if (r.get("apply_execute_status") == "pending"
                      or r.get("apply_status") == "pending")
                  and r.get("duplicate_key", "") not in already_applied]

    # patch_plan からバックアップ・diff 情報を補完
    patch_plans = {r.get("duplicate_key", ""): r
                   for r in _load_jsonl(PATCH_PLAN_QUEUE_PATH)}

    existing_explain = {r.get("explain_key", "")
                        for r in _load_jsonl(APPLY_EXPLAIN_QUEUE)
                        if r.get("explain_status") in ("pending", "explained")}

    added = 0
    dup   = 0

    for rec in apply_recs:
        dup_key = rec.get("duplicate_key", "")
        ta      = rec.get("target_agent", "—")
        ekey    = _explain_key("apply", dup_key)

        if ekey in existing_explain:
            dup += 1
            continue

        existing_explain.add(ekey)

        patch_path    = rec.get("patch_path", "—")
        after_value   = (rec.get("after_value") or "")
        target_config = rec.get("target_config", "config/agent_directives.json")
        write_scope   = rec.get("write_scope", "config_single_key")
        backup_req    = rec.get("backup_required", True)
        patch_plan    = patch_plans.get(dup_key, {})
        backup_path   = patch_plan.get("backup_path", f"backups/agent_directives/{ta}.json")
        diff_path     = patch_plan.get("diff_path", f"backups/agent_directives/{ta}_diff.json")
        patch_mode    = patch_plan.get("patch_mode", "single_key")

        next_cmd = f'python3 lib/ceo_unlock_executor.py apply  # {ta} apply実行'
        rollback_cmd = (
            f"python3 lib/ceo_config_executor.py rollback {ta}  "
            f"# apply失敗時は backup_path から復元"
        )

        explain_rec = {
            "explained_at":        _now_jst(),
            "explain_key":         ekey,
            "duplicate_key":       dup_key,
            "target_agent":        ta,
            "patch_path":          patch_path,
            "after_value":         after_value[:200],
            "target_config":       target_config,
            "write_scope":         write_scope,
            "backup_required":     backup_req,
            "backup_path":         backup_path,
            "diff_path":           diff_path,
            "patch_mode":          patch_mode,
            "explain_type":        "apply_explain",
            "explain_status":      "pending",
            "next_manual_command": next_cmd,
            "rollback_command":    rollback_cmd,
            "expected_next_stage": "applied → post_apply_judge",
            "current_stage":       "apply_ready",
            "execution_blocked":   True,
            "source_queue":        "ceo_apply_execute_queue",
            "ceo_judgment":        "ミュウツーCEO apply前最終説明",
        }
        _append_jsonl(APPLY_EXPLAIN_QUEUE, explain_rec)
        _append_jsonl(APPLY_EXPLAIN_HISTORY, {
            "processed_at":  _now_jst(),
            "explain_key":   ekey,
            "target_agent":  ta,
            "duplicate_key": dup_key,
            "status":        "explained",
            "ceo_judgment":  "ミュウツーCEO apply前最終説明",
        })
        added += 1

    pending = [r for r in _load_jsonl(APPLY_EXPLAIN_QUEUE)
               if r.get("explain_status") == "pending"]
    return {"added": added, "dup": dup, "pending": len(pending)}


# ═══════════════════════════════════════════════════════════════════
# 3. 実行禁止条件可視化
# ═══════════════════════════════════════════════════════════════════

_VALID_WRITE_SCOPES  = {"queue_only", "none", "config_single_key"}
_VALID_TARGET_CONFIG = "config/agent_directives.json"


def _check_blocked_reasons(rec: dict, has_invariant: bool, is_stale: bool) -> list[str]:
    reasons = []
    if rec.get("execution_blocked", True):
        reasons.append("execution_blocked=true (unlock未実行)")
    ws = rec.get("write_scope", "")
    if ws not in _VALID_WRITE_SCOPES:
        reasons.append(f"write_scope={ws} (不正値)")
    if not rec.get("backup_required", False):
        reasons.append("backup_required=false (バックアップ設定なし)")
    tc = rec.get("target_config", "")
    if tc and tc != _VALID_TARGET_CONFIG:
        reasons.append(f"target_config={tc} (config/agent_directives.json以外)")
    pp = rec.get("patch_path", "")
    if pp and not pp.startswith("agent_directives."):
        reasons.append(f"patch_path={pp} (agent_directives.で始まらない)")
    av = (rec.get("after_value") or "").strip()
    if not av:
        reasons.append("after_value 空 (値が未定義)")
    ta = rec.get("target_agent", "")
    if not ta or ta == "—":
        reasons.append("target_agent 不正 (空またはダッシュ)")
    ne = rec.get("next_executor", "")
    if ne and "ceo_config_executor" not in ne and "ceo_unlock_executor" not in ne:
        reasons.append(f"next_executor={ne} (不正なexecutor名)")
    if has_invariant:
        reasons.append("安全不変条件違反あり (invariant_violation pending)")
    if is_stale:
        reasons.append("stale状態 (unlock_pending_stale)")
    return reasons


def run_final_block_check() -> dict:
    """
    unlock_execute_queue / apply_execute_queue の各 pending レコードについて
    blocked_reason を列挙し ceo_final_block_queue に記録する。
    """
    # unlock済み duplicate_key（pending扱い除外用）
    already_unlocked = {r.get("duplicate_key", "")
                        for r in _load_jsonl(UNLOCK_EXECUTE_QUEUE_PATH)
                        if r.get("unlock_status") == "unlocked"
                        and r.get("actual_unlocked") is True}

    already_applied = {r.get("duplicate_key", "")
                       for r in _load_jsonl(APPLY_EXECUTE_RESULT_PATH)
                       if r.get("result_status") == "applied"}

    unlock_recs = [r for r in _load_jsonl(UNLOCK_EXECUTE_QUEUE_PATH)
                   if r.get("unlock_status") == "pending"
                   and r.get("duplicate_key", "") not in already_unlocked]
    apply_recs  = [r for r in _load_jsonl(APPLY_EXECUTE_QUEUE_PATH)
                   if (r.get("apply_execute_status") == "pending"
                       or r.get("apply_status") == "pending")
                   and r.get("duplicate_key", "") not in already_applied]

    invariant_agents = {r.get("target_agent", "")
                        for r in _load_jsonl(INVARIANT_VIOLATION_QUEUE_PATH)
                        if r.get("violation_status") == "pending"}
    stale_agents     = {r.get("target_agent", "")
                        for r in _load_jsonl(STALE_OP_QUEUE_PATH)
                        if r.get("status") == "pending"
                        and r.get("operation_type") == "unlock_pending_stale"
                        and r.get("duplicate_key", "") not in already_unlocked}

    existing = {r.get("block_key", "")
                for r in _load_jsonl(FINAL_BLOCK_QUEUE)
                if r.get("block_status") in ("blocked", "ready")}

    added_blocked = 0
    added_ready   = 0
    dup           = 0

    def _process(rec: dict, rec_type: str) -> None:
        nonlocal added_blocked, added_ready, dup
        dup_key = rec.get("duplicate_key", "")
        ta      = rec.get("target_agent", "—")
        bkey    = f"{rec_type}|{dup_key}"

        if bkey in existing:
            dup += 1
            return

        existing.add(bkey)
        has_inv  = ta in invariant_agents
        is_stale = ta in stale_agents

        reasons = _check_blocked_reasons(rec, has_inv, is_stale)
        status  = "blocked" if reasons else "ready"

        block_rec = {
            "checked_at":      _now_jst(),
            "block_key":       bkey,
            "duplicate_key":   dup_key,
            "target_agent":    ta,
            "check_type":      rec_type,
            "block_status":    status,
            "blocked_reason":  reasons,
            "blocked_count":   len(reasons),
            "execution_blocked": rec.get("execution_blocked", True),
            "write_scope":     rec.get("write_scope", "—"),
            "backup_required": rec.get("backup_required", False),
            "patch_path":      rec.get("patch_path", "—"),
            "after_value":     (rec.get("after_value") or "")[:80],
            "source_queue":    f"ceo_{rec_type}_execute_queue",
            "ceo_judgment":    "ミュウツーCEO実行禁止条件確認",
        }
        _append_jsonl(FINAL_BLOCK_QUEUE, block_rec)
        _append_jsonl(FINAL_BLOCK_HISTORY, {
            "processed_at":  _now_jst(),
            "block_key":     bkey,
            "target_agent":  ta,
            "block_status":  status,
            "blocked_count": len(reasons),
            "status":        "checked",
            "ceo_judgment":  "ミュウツーCEO実行禁止条件確認",
        })
        if status == "blocked":
            added_blocked += 1
        else:
            added_ready += 1

    for rec in unlock_recs:
        _process(rec, "unlock")
    for rec in apply_recs:
        _process(rec, "apply")

    all_recs       = _load_jsonl(FINAL_BLOCK_QUEUE)
    total_blocked  = sum(1 for r in all_recs if r.get("block_status") == "blocked")
    total_ready    = sum(1 for r in all_recs if r.get("block_status") == "ready")
    latest_blocked = next((r for r in reversed(all_recs)
                           if r.get("block_status") == "blocked"), {})
    return {
        "added_blocked":    added_blocked,
        "added_ready":      added_ready,
        "dup":              dup,
        "total_blocked":    total_blocked,
        "total_ready":      total_ready,
        "latest_block_reason": latest_blocked.get("blocked_reason", []),
    }


# ═══════════════════════════════════════════════════════════════════
# 4. 手動操作後チェックリスト
# ═══════════════════════════════════════════════════════════════════

_UNLOCK_CHECKLIST = [
    {
        "order": 1,
        "item":  "unlock_execute_queue で unlock_status が unlocked に変わったか確認",
        "check_file":  "logs/ceo_unlock_execute_queue.jsonl",
        "check_field": "unlock_status",
        "expected":    "unlocked",
    },
    {
        "order": 2,
        "item":  "apply_execute_queue に新規 pending レコードが生成されたか確認",
        "check_file":  "logs/ceo_apply_execute_queue.jsonl",
        "check_field": "apply_execute_status",
        "expected":    "pending",
    },
    {
        "order": 3,
        "item":  "unlock_expiry_queue に期限管理レコードが入ったか確認",
        "check_file":  "logs/ceo_unlock_expiry_queue.jsonl",
        "check_field": "expiry_status",
        "expected":    "watching",
    },
    {
        "order": 4,
        "item":  "safety_invariants で execution_blocked=false による違反が出ていないか確認",
        "check_file":  "logs/ceo_invariant_violation_queue.jsonl",
        "check_field": "violation_status",
        "expected":    "なし（pending=0）",
    },
    {
        "order": 5,
        "item":  "run_agent_monitor.sh を再実行して stage が apply_ready に遷移したか確認",
        "check_file":  "dashboard_summary.json",
        "check_field": "current_operation_stage",
        "expected":    "apply_ready",
    },
]

_APPLY_CHECKLIST = [
    {
        "order": 1,
        "item":  "apply_execute_result_queue で result_status=applied になったか確認",
        "check_file":  "logs/ceo_apply_execute_result_queue.jsonl",
        "check_field": "result_status",
        "expected":    "applied",
    },
    {
        "order": 2,
        "item":  "post_apply_judge_queue に judge_label が入ったか確認",
        "check_file":  "logs/ceo_post_apply_judge_queue.jsonl",
        "check_field": "judge_label",
        "expected":    "keep_monitoring または re_adjust_minor",
    },
    {
        "order": 3,
        "item":  "rollback_dispatch_queue に pending が増えていないか確認（増えていたら要対応）",
        "check_file":  "logs/ceo_rollback_dispatch_queue.jsonl",
        "check_field": "router_status",
        "expected":    "pending=0 が理想",
    },
    {
        "order": 4,
        "item":  "performance_evaluation_queue に verdict=improved が入ったか確認",
        "check_file":  "logs/ceo_performance_evaluation_queue.jsonl",
        "check_field": "verdict",
        "expected":    "improved",
    },
    {
        "order": 5,
        "item":  "backups/agent_directives/ にバックアップファイルが作成されたか確認",
        "check_file":  "backups/agent_directives/",
        "check_field": "ファイル存在",
        "expected":    "対象エージェントのJSONファイルあり",
    },
]


def run_post_command_checklist() -> dict:
    """
    unlock_execute_queue / apply_execute_queue の状態に応じて
    実行後チェックリストを生成する。
    """
    already_unlocked_cl = {r.get("duplicate_key", "")
                           for r in _load_jsonl(UNLOCK_EXECUTE_QUEUE_PATH)
                           if r.get("unlock_status") == "unlocked"
                           and r.get("actual_unlocked") is True}
    already_applied_cl  = {r.get("duplicate_key", "")
                           for r in _load_jsonl(APPLY_EXECUTE_RESULT_PATH)
                           if r.get("result_status") == "applied"}
    unlock_recs = [r for r in _load_jsonl(UNLOCK_EXECUTE_QUEUE_PATH)
                   if r.get("unlock_status") == "pending"
                   and r.get("duplicate_key", "") not in already_unlocked_cl]
    apply_recs  = [r for r in _load_jsonl(APPLY_EXECUTE_QUEUE_PATH)
                   if (r.get("apply_execute_status") == "pending"
                       or r.get("apply_status") == "pending")
                   and r.get("duplicate_key", "") not in already_applied_cl]

    existing = {r.get("checklist_key", "")
                for r in _load_jsonl(CHECKLIST_QUEUE)
                if r.get("checklist_status") == "active"}

    added = 0
    dup   = 0

    def _add_checklist(dup_key: str, ta: str, stage: str, items: list[dict]) -> None:
        nonlocal added, dup
        ckey = f"checklist_{stage}|{dup_key}"
        if ckey in existing:
            dup += 1
            return
        existing.add(ckey)
        rec = {
            "created_at":       _now_jst(),
            "checklist_key":    ckey,
            "duplicate_key":    dup_key,
            "target_agent":     ta,
            "stage":            stage,
            "checklist_status": "active",
            "item_count":       len(items),
            "items":            items,
            "execution_blocked": True,
            "write_scope":      "queue_only",
            "source_queue":     f"ceo_{stage}_execute_queue",
            "ceo_judgment":     "ミュウツーCEO実行後確認チェックリスト",
        }
        _append_jsonl(CHECKLIST_QUEUE, rec)
        _append_jsonl(CHECKLIST_HISTORY, {
            "processed_at":  _now_jst(),
            "checklist_key": ckey,
            "target_agent":  ta,
            "stage":         stage,
            "item_count":    len(items),
            "status":        "created",
            "ceo_judgment":  "ミュウツーCEO実行後確認チェックリスト",
        })
        added += 1

    for rec in unlock_recs:
        _add_checklist(rec.get("duplicate_key", ""), rec.get("target_agent", "—"),
                       "unlock", _UNLOCK_CHECKLIST)
    for rec in apply_recs:
        _add_checklist(rec.get("duplicate_key", ""), rec.get("target_agent", "—"),
                       "apply", _APPLY_CHECKLIST)

    pending = [r for r in _load_jsonl(CHECKLIST_QUEUE)
               if r.get("checklist_status") == "active"]
    return {"added": added, "dup": dup, "pending": len(pending)}


# ═══════════════════════════════════════════════════════════════════
# stats 関数群
# ═══════════════════════════════════════════════════════════════════

def get_unlock_explain_stats() -> dict:
    recs    = _load_jsonl(UNLOCK_EXPLAIN_QUEUE)
    pending = [r for r in recs if r.get("explain_status") == "pending"]
    latest  = pending[-1] if pending else {}
    return {
        "unlock_explain_pending_count": len(pending),
        "unlock_explain_latest_agent":  latest.get("target_agent", "—"),
        "unlock_explain_latest_why":    latest.get("why_now", "—")[:100],
        "unlock_explain_next_command":  latest.get("next_manual_command", "—"),
        "unlock_explain_rollback_cmd":  latest.get("rollback_command", "—"),
        "unlock_explain_next_stage":    latest.get("expected_next_stage", "—"),
    }


def get_apply_explain_stats() -> dict:
    recs    = _load_jsonl(APPLY_EXPLAIN_QUEUE)
    pending = [r for r in recs if r.get("explain_status") == "pending"]
    latest  = pending[-1] if pending else {}
    return {
        "apply_explain_pending_count":  len(pending),
        "apply_explain_latest_agent":   latest.get("target_agent", "—"),
        "apply_explain_patch_path":     latest.get("patch_path", "—"),
        "apply_explain_after_value":    (latest.get("after_value") or "—")[:80],
        "apply_explain_next_command":   latest.get("next_manual_command", "—"),
        "apply_explain_rollback_cmd":   latest.get("rollback_command", "—"),
        "apply_explain_backup_path":    latest.get("backup_path", "—"),
    }


def get_final_block_stats() -> dict:
    recs    = _load_jsonl(FINAL_BLOCK_QUEUE)
    blocked = [r for r in recs if r.get("block_status") == "blocked"]
    ready   = [r for r in recs if r.get("block_status") == "ready"]
    latest_b = next((r for r in reversed(recs) if r.get("block_status") == "blocked"), {})
    reasons  = latest_b.get("blocked_reason", [])
    return {
        "final_blocked_count":          len(blocked),
        "final_ready_count":            len(ready),
        "final_blocked_latest_agent":   latest_b.get("target_agent", "—"),
        "latest_final_block_reason":    reasons[0] if reasons else "—",
        "final_blocked_reason_count":   len(reasons),
    }


def get_checklist_stats() -> dict:
    recs    = _load_jsonl(CHECKLIST_QUEUE)
    pending = [r for r in recs if r.get("checklist_status") == "active"]
    latest  = pending[-1] if pending else {}
    items   = latest.get("items", [])
    top1    = items[0].get("item", "—") if items else "—"
    return {
        "post_command_checklist_count": len(pending),
        "post_command_checklist_latest_agent": latest.get("target_agent", "—"),
        "post_command_checklist_stage": latest.get("stage", "—"),
        "post_command_checklist_top1":  top1,
        "post_command_checklist_items": len(items),
    }


# ═══════════════════════════════════════════════════════════════════
# 統合 next_manual_command サマリー
# ═══════════════════════════════════════════════════════════════════

def compute_next_manual_summary(dashboard_summary: dict | None = None) -> dict:
    """
    unlock_explain / apply_explain / final_block から
    dashboard_summary に追加する next_manual_* フィールドを生成する。
    """
    ds = dashboard_summary or {}

    # unlock説明から引っ張る
    unlock_pending = [r for r in _load_jsonl(UNLOCK_EXPLAIN_QUEUE)
                      if r.get("explain_status") == "pending"]
    apply_pending  = [r for r in _load_jsonl(APPLY_EXPLAIN_QUEUE)
                      if r.get("explain_status") == "pending"]
    blocked_recs   = [r for r in _load_jsonl(FINAL_BLOCK_QUEUE)
                      if r.get("block_status") == "blocked"]

    # 優先: apply > unlock > なし
    if apply_pending:
        top = apply_pending[-1]
        cmd_type = "apply"
        cmd      = top.get("next_manual_command", "—")
        ta       = top.get("target_agent", "—")
        why      = (f"apply_execute_queue にpending {len(apply_pending)}件。"
                    f"patch_path={top.get('patch_path','—')} を target_config に書き込む準備完了。")
        after    = top.get("expected_next_stage", "applied → post_apply_judge")
        rb_cmd   = top.get("rollback_command", "—")
    elif unlock_pending:
        top = unlock_pending[-1]
        cmd_type = "unlock"
        cmd      = top.get("next_manual_command", "—")
        ta       = top.get("target_agent", "—")
        why      = top.get("why_now", "—")
        after    = top.get("what_changes", "—")
        rb_cmd   = top.get("rollback_command", "—")
    else:
        cmd_type = "monitor_only"
        cmd      = "bash run_agent_monitor.sh  # 現在手動実行候補なし"
        ta       = "—"
        why      = "unlock / apply pending なし"
        after    = "変化なし"
        rb_cmd   = "—"

    return {
        "next_manual_command":         cmd,
        "next_manual_command_type":    cmd_type,
        "next_manual_target_agent":    ta,
        "next_manual_why_now":         why[:200],
        "next_manual_after_effect":    after[:200],
        "next_manual_rollback_command": rb_cmd[:200],
        "unlock_explain_pending_count": len(unlock_pending),
        "apply_explain_pending_count":  len(apply_pending),
        "final_blocked_count":          len(blocked_recs),
        "final_ready_count": sum(1 for r in _load_jsonl(FINAL_BLOCK_QUEUE)
                                 if r.get("block_status") == "ready"),
        "latest_final_block_reason": (blocked_recs[-1].get("blocked_reason", ["—"])[0]
                                      if blocked_recs else "—"),
    }


# ═══════════════════════════════════════════════════════════════════
# まとめて実行
# ═══════════════════════════════════════════════════════════════════

def run_all_manual_explain() -> dict:
    """全フェーズをまとめて実行して集計結果を返す。"""
    r1 = run_unlock_explain()
    r2 = run_apply_explain()
    r3 = run_final_block_check()
    r4 = run_post_command_checklist()
    return {
        "unlock_explain":  r1,
        "apply_explain":   r2,
        "final_block":     r3,
        "checklist":       r4,
    }


if __name__ == "__main__":
    import json as _json
    result = run_all_manual_explain()
    print(_json.dumps(result, ensure_ascii=False, indent=2))
    print("--- stats ---")
    print(_json.dumps(get_unlock_explain_stats(), ensure_ascii=False, indent=2))
    print(_json.dumps(get_apply_explain_stats(),  ensure_ascii=False, indent=2))
    print(_json.dumps(get_final_block_stats(),    ensure_ascii=False, indent=2))
    print(_json.dumps(get_checklist_stats(),      ensure_ascii=False, indent=2))
    print(_json.dumps(compute_next_manual_summary(), ensure_ascii=False, indent=2))
