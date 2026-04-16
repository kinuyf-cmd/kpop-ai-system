#!/usr/bin/env python3
"""
ceo_stale_resolver.py — stale解消支援レイヤー v1.0
CEO: ミュウツー / オーナー: 人間（閲覧専用）

【役割】
  stale_cleanup_plan_queue を読んで
  「今すぐ確認」「提案」3分類を作る。実行はしない。

【分類】
  unlock_pending_stale  → resolve_action="review_unlock_candidate"  / priority=HIGH
  apply_pending_stale   → resolve_action="review_apply_candidate"   / priority=HIGH
  postlock_stale        → resolve_action="review_postlock"          / priority=MEDIUM
  orphan                → resolve_action="archive_candidate"        / priority=LOW
  expired_unlock        → resolve_action="check_unlock_expiry"      / priority=HIGH

【制約】
  - archive 実行禁止（提案のみ）
  - config 書き込み禁止
  - execution_blocked 変更禁止
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

STALE_CLEANUP_PLAN_QUEUE = LOGS / "ceo_stale_cleanup_plan_queue.jsonl"
STALE_OP_QUEUE           = LOGS / "ceo_stale_operation_queue.jsonl"
UNLOCK_EXECUTE_QUEUE     = LOGS / "ceo_unlock_execute_queue.jsonl"

RESOLUTION_QUEUE   = LOGS / "ceo_stale_resolution_queue.jsonl"
RESOLUTION_HISTORY = LOGS / "ceo_stale_resolution_history.jsonl"

# category / operation_type → resolve_action mapping
RESOLVE_MAP = {
    "stale_candidate":     ("review_unlock_candidate", "HIGH"),
    "stale_apply_ready":   ("review_apply_candidate",  "HIGH"),
    "stale_postlock":      ("review_postlock",          "MEDIUM"),
    "orphan_queue_record": ("archive_candidate",        "LOW"),
    "expired_unlock":      ("check_unlock_expiry",      "HIGH"),
    "unlock_pending_stale":("review_unlock_candidate",  "HIGH"),
    "apply_pending_stale": ("review_apply_candidate",   "HIGH"),
    "rollback_stale":      ("review_postlock",          "MEDIUM"),
}

COMMAND_MAP = {
    "review_unlock_candidate": "python3 lib/ceo_unlock_executor.py unlock \"{dup_key}\"  # {ta} unlock実行",
    "review_apply_candidate":  "python3 lib/ceo_unlock_executor.py apply  # {ta} apply実行",
    "review_postlock":         "python3 lib/ceo_config_executor.py rollback {ta}  # postlock確認",
    "archive_candidate":       "bash run_agent_monitor.sh  # {ta} orphan確認（自動archiveは禁止）",
    "check_unlock_expiry":     "bash run_agent_monitor.sh  # {ta} unlock期限確認・再unlock検討",
}


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


def _res_key(stale_key: str) -> str:
    return f"resolve|{stale_key}"


# ═══════════════════════════════════════════════════════════════════
# メイン分類
# ═══════════════════════════════════════════════════════════════════

def run_stale_resolver() -> dict:
    """
    stale_cleanup_plan_queue / stale_operation_queue を読んで
    resolve候補を生成する。提案のみ、実行なし。
    """
    # unlock済み duplicate_key（stale除外用）
    already_unlocked = {r.get("duplicate_key", "")
                        for r in _load_jsonl(UNLOCK_EXECUTE_QUEUE)
                        if r.get("unlock_status") == "unlocked"
                        and r.get("actual_unlocked") is True}

    # stale_cleanup_plan_queue から pending を収集
    plan_recs = [r for r in _load_jsonl(STALE_CLEANUP_PLAN_QUEUE)
                 if r.get("plan_status") == "pending"
                 and r.get("duplicate_key", "") not in already_unlocked]
    # stale_operation_queue からも補完（plan がない場合）
    op_recs   = [r for r in _load_jsonl(STALE_OP_QUEUE)
                 if r.get("status") == "pending"
                 and r.get("duplicate_key", "") not in already_unlocked]

    # 既存 resolution の重複チェック
    existing  = {r.get("resolution_key", "")
                 for r in _load_jsonl(RESOLUTION_QUEUE)
                 if r.get("resolution_status") == "pending"}

    added  = 0
    dup    = 0

    def _process(stale_key: str, category: str, op_type: str,
                 ta: str, dup_key: str, stale_min: float, rec_action: str) -> None:
        nonlocal added, dup
        rkey = _res_key(stale_key)
        if rkey in existing:
            dup += 1
            return
        existing.add(rkey)

        resolve_action, priority = RESOLVE_MAP.get(category, RESOLVE_MAP.get(op_type, ("archive_candidate", "LOW")))
        cmd_template = COMMAND_MAP.get(resolve_action, "bash run_agent_monitor.sh")
        try:
            suggested_cmd = cmd_template.format(dup_key=dup_key, ta=ta)
        except Exception:
            suggested_cmd = cmd_template

        res_rec = {
            "resolved_at":        _now_jst(),
            "resolution_key":     rkey,
            "stale_key":          stale_key,
            "stale_type":         category or op_type,
            "target_agent":       ta,
            "duplicate_key":      dup_key,
            "stale_minutes":      stale_min,
            "resolve_action":     resolve_action,
            "resolve_priority":   priority,
            "recommended_action": rec_action,
            "suggested_command":  suggested_cmd,
            "resolution_status":  "pending",
            "execution_blocked":  True,
            "write_scope":        "none",
            "source_queue":       "ceo_stale_cleanup_plan_queue",
            "ceo_judgment":       "ミュウツーCEO stale解消候補",
        }
        _append_jsonl(RESOLUTION_QUEUE, res_rec)
        _append_jsonl(RESOLUTION_HISTORY, {
            "processed_at":    _now_jst(),
            "resolution_key":  rkey,
            "target_agent":    ta,
            "resolve_action":  resolve_action,
            "resolve_priority": priority,
            "status":          "created",
            "ceo_judgment":    "ミュウツーCEO stale解消候補",
        })
        added += 1

    # plan_recs 処理
    processed_keys: set[str] = set()
    for rec in plan_recs:
        sk  = rec.get("stale_key", "")
        cat = rec.get("category", "")
        opt = rec.get("operation_type", "")
        ta  = rec.get("target_agent", "—")
        dk  = rec.get("duplicate_key", "")
        sm  = float(rec.get("stale_minutes", 0))
        ra  = rec.get("recommended_action", "")
        _process(sk, cat, opt, ta, dk, sm, ra)
        processed_keys.add(sk)

    # op_recs で補完（plan に含まれていないもの）
    for rec in op_recs:
        sk  = rec.get("stale_key", "")
        if sk in processed_keys:
            continue
        opt = rec.get("operation_type", "")
        ta  = rec.get("target_agent", "—")
        dk  = rec.get("duplicate_key", "")
        sm  = float(rec.get("stale_minutes", 0))
        ra  = rec.get("recommended_action", "")
        _process(sk, "", opt, ta, dk, sm, ra)

    pending_all = _load_jsonl(RESOLUTION_QUEUE)
    pending     = [r for r in pending_all
                   if r.get("resolution_status") == "pending"
                   and r.get("duplicate_key", "") not in already_unlocked]
    by_priority = {}
    for r in pending:
        p = r.get("resolve_priority", "LOW")
        by_priority[p] = by_priority.get(p, 0) + 1

    return {
        "added":        added,
        "dup":          dup,
        "pending":      len(pending),
        "by_priority":  by_priority,
    }


def get_stale_resolver_stats() -> dict:
    already_unlocked = {r.get("duplicate_key", "")
                        for r in _load_jsonl(UNLOCK_EXECUTE_QUEUE)
                        if r.get("unlock_status") == "unlocked"
                        and r.get("actual_unlocked") is True}
    recs    = _load_jsonl(RESOLUTION_QUEUE)
    pending = [r for r in recs
               if r.get("resolution_status") == "pending"
               and r.get("duplicate_key", "") not in already_unlocked]
    high    = [r for r in pending if r.get("resolve_priority") == "HIGH"]
    top     = high[0] if high else (pending[0] if pending else {})
    return {
        "stale_resolution_pending_count": len(pending),
        "stale_resolution_high_count":    len(high),
        "stale_resolution_top1_action":   top.get("resolve_action", "—"),
        "stale_resolution_top1_agent":    top.get("target_agent", "—"),
        "stale_resolution_top1_command":  top.get("suggested_command", "—"),
    }


if __name__ == "__main__":
    import json as _json
    result = run_stale_resolver()
    print(_json.dumps(result, ensure_ascii=False, indent=2))
    print(_json.dumps(get_stale_resolver_stats(), ensure_ascii=False, indent=2))
