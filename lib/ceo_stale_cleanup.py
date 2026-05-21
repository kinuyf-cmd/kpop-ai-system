#!/usr/bin/env python3
"""
ceo_stale_cleanup.py — stale operation 整理計画 v1.0
CEO: ミュウツー / オーナー: 人間（閲覧専用）

【役割】
  stale_operation_queue を種類別に分類し、cleanup 提案を生成する。
  実際の cleanup は実行しない。候補提案と件数のみ。

【分類】
  - expired_unlock:    unlock期限切れ
  - stale_apply_ready: apply_execute 放置
  - stale_postlock:    post_apply_lock 放置
  - stale_candidate:   unlock_pending 放置
  - orphan_queue_record: 上記以外

【制約】
  - cleanup 自動実行禁止
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

STALE_OP_QUEUE_PATH         = LOGS / "ceo_stale_operation_queue.jsonl"
UNLOCK_EXECUTE_QUEUE        = LOGS / "ceo_unlock_execute_queue.jsonl"
STALE_CLEANUP_PLAN_QUEUE    = LOGS / "ceo_stale_cleanup_plan_queue.jsonl"
STALE_CLEANUP_PLAN_HISTORY  = LOGS / "ceo_stale_cleanup_plan_history.jsonl"

# stale_operation_queue の operation_type → cleanup category マッピング
OP_TYPE_TO_CATEGORY = {
    "unlock_expired":       "expired_unlock",
    "unlock_pending_stale": "stale_candidate",
    "apply_stale":          "stale_apply_ready",
    "rollback_stale":       "stale_postlock",
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


# ════════════════════════════════════════════════════════════════════
# 分類・計画生成
# ════════════════════════════════════════════════════════════════════

def run_stale_cleanup_plan() -> dict:
    """
    stale_operation_queue を分類し cleanup_plan_queue に生成する。
    """
    already_unlocked = {r.get("duplicate_key", "")
                        for r in _load_jsonl(UNLOCK_EXECUTE_QUEUE)
                        if r.get("unlock_status") == "unlocked"
                        and r.get("actual_unlocked") is True}

    stale_recs = [r for r in _load_jsonl(STALE_OP_QUEUE_PATH)
                  if r.get("status") == "pending"
                  and r.get("duplicate_key", "") not in already_unlocked]

    existing = {r.get("stale_key", "") for r in _load_jsonl(STALE_CLEANUP_PLAN_QUEUE)
                if r.get("plan_status") == "pending"}

    categories: dict[str, list[dict]] = {
        "expired_unlock":      [],
        "stale_apply_ready":   [],
        "stale_postlock":      [],
        "stale_candidate":     [],
        "orphan_queue_record": [],
    }

    added = 0
    dup   = 0

    for rec in stale_recs:
        stale_key = rec.get("stale_key", "")
        if stale_key in existing:
            dup += 1
            continue

        op_type  = rec.get("operation_type", "")
        category = OP_TYPE_TO_CATEGORY.get(op_type, "orphan_queue_record")
        ta       = rec.get("target_agent", "—")

        categories[category].append(rec)
        existing.add(stale_key)

        # cleanup推奨アクション
        if category == "expired_unlock":
            action = f"python3 lib/ceo_unlock_executor.py unlock <new_key>  # {ta} 再unlock"
        elif category == "stale_apply_ready":
            action = f"python3 lib/ceo_unlock_executor.py apply  # {ta} apply実行"
        elif category == "stale_postlock":
            action = f"python3 lib/ceo_config_executor.py rollback {ta}  # rollback確認"
        elif category == "stale_candidate":
            action = f"python3 lib/ceo_unlock_executor.py unlock <dup_key>  # {ta} unlock"
        else:
            action = f"bash run_agent_monitor.sh  # {ta} 状態確認"

        plan_rec = {
            "planned_at":   _now_jst(),
            "stale_key":    stale_key,
            "category":     category,
            "operation_type": op_type,
            "target_agent": ta,
            "duplicate_key": rec.get("duplicate_key", ""),
            "stale_minutes": rec.get("stale_minutes", 0),
            "recommended_action": rec.get("recommended_action", ""),
            "cleanup_command": action,
            "plan_status":  "pending",
            "source_queue": "ceo_stale_operation_queue",
            "ceo_judgment": "ミュウツーCEO cleanup計画",
        }
        _append_jsonl(STALE_CLEANUP_PLAN_QUEUE, plan_rec)
        _append_jsonl(STALE_CLEANUP_PLAN_HISTORY, {
            "processed_at": _now_jst(),
            "stale_key":    stale_key,
            "category":     category,
            "status":       "planned",
            "ceo_judgment": "ミュウツーCEO cleanup計画",
        })
        added += 1

    plan_recs = _load_jsonl(STALE_CLEANUP_PLAN_QUEUE)
    by_cat = {}
    for cat in categories:
        by_cat[cat] = sum(1 for r in plan_recs
                          if r.get("category") == cat and r.get("plan_status") == "pending")

    return {
        "added":    added,
        "dup":      dup,
        "by_category": by_cat,
        "total_pending": sum(1 for r in plan_recs if r.get("plan_status") == "pending"),
    }


def get_stale_cleanup_stats() -> dict:
    already_unlocked = {r.get("duplicate_key", "")
                        for r in _load_jsonl(UNLOCK_EXECUTE_QUEUE)
                        if r.get("unlock_status") == "unlocked"
                        and r.get("actual_unlocked") is True}
    plan_recs = _load_jsonl(STALE_CLEANUP_PLAN_QUEUE)
    pending   = [r for r in plan_recs
                 if r.get("plan_status") == "pending"
                 and r.get("duplicate_key", "") not in already_unlocked]
    latest    = pending[-1] if pending else {}
    by_cat    = {}
    for r in pending:
        cat = r.get("category", "unknown")
        by_cat[cat] = by_cat.get(cat, 0) + 1
    return {
        "stale_cleanup_pending_count":  len(pending),
        "stale_cleanup_latest_agent":   latest.get("target_agent", "—"),
        "stale_cleanup_latest_category": latest.get("category", "—"),
        "stale_cleanup_latest_command": latest.get("cleanup_command", "—"),
        "stale_cleanup_by_category":    by_cat,
    }


if __name__ == "__main__":
    import json as _json
    result = run_stale_cleanup_plan()
    print(_json.dumps(result, ensure_ascii=False, indent=2))
    print(_json.dumps(get_stale_cleanup_stats(), ensure_ascii=False, indent=2))
