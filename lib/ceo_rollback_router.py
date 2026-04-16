#!/usr/bin/env python3
"""
ceo_rollback_router.py — rollback振り分けルーター v1.0
CEO: ミュウツー / オーナー: 人間（閲覧専用）

【役割】
  post_apply_judge_queue の rollback_recommended を
  rollback_dispatch_queue（即時確認）と rollback_watch_queue（様子見）に振り分ける。

【振り分け条件（完全決定論）】
  dispatch 対象:
    - 売上直結AI（x_post系, wordpress_post系）
    - performance_delta <= -0.10 以下の深刻悪化
    - hard_fail 増加が確認された場合
  watch 対象:
    - 上記以外の rollback_recommended

【制約】
  - rollback 自動実行禁止
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

POST_APPLY_JUDGE_QUEUE    = LOGS / "ceo_post_apply_judge_queue.jsonl"
ROLLBACK_DISPATCH_QUEUE   = LOGS / "ceo_rollback_dispatch_queue.jsonl"
ROLLBACK_DISPATCH_HISTORY = LOGS / "ceo_rollback_dispatch_history.jsonl"
ROLLBACK_WATCH_QUEUE      = LOGS / "ceo_rollback_watch_queue.jsonl"
ROLLBACK_WATCH_HISTORY    = LOGS / "ceo_rollback_watch_history.jsonl"

# 売上直結エージェント（即時 dispatch 対象）
REVENUE_CRITICAL_AGENTS = {
    "x_post", "x_post_b", "wordpress_post", "persian",
    "x投稿", "x投稿b", "wp投稿",
}

DEGRADE_DISPATCH_THRESHOLD = -0.10  # delta がこれ以下なら dispatch


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


def _is_dispatch(rec: dict) -> tuple[bool, str]:
    """True → dispatch対象, str → 理由"""
    ta    = (rec.get("target_agent", "") or "").lower().replace(" ", "").replace("　", "")
    delta = float(rec.get("performance_delta", 0))
    verdict = rec.get("verdict", "")

    if ta in {a.lower() for a in REVENUE_CRITICAL_AGENTS}:
        return True, f"売上直結AI({ta}) rollback確認が必要"
    if delta <= DEGRADE_DISPATCH_THRESHOLD:
        return True, f"深刻悪化(delta={delta:+.3f})"
    if "hard_fail" in rec.get("judge_reason", "").lower():
        return True, "hard_fail増加確認"
    if verdict in ("critical", "degraded") and delta < -0.03:
        return True, f"critical/degraded(delta={delta:+.3f})"
    return False, "軽微悪化 — 様子見"


# ════════════════════════════════════════════════════════════════════
# メイン振り分け
# ════════════════════════════════════════════════════════════════════

def run_rollback_router() -> dict:
    """
    post_apply_judge_queue の rollback_recommended を dispatch / watch に振り分ける。
    """
    judge_recs = [r for r in _load_jsonl(POST_APPLY_JUDGE_QUEUE)
                  if r.get("judge_label") == "rollback_recommended"]

    existing_dispatch = {r.get("duplicate_key", "")
                         for r in _load_jsonl(ROLLBACK_DISPATCH_QUEUE)
                         if r.get("router_status") in ("pending", "dispatched")}
    existing_watch    = {r.get("duplicate_key", "")
                         for r in _load_jsonl(ROLLBACK_WATCH_QUEUE)
                         if r.get("router_status") in ("pending", "watching")}

    dispatched = 0
    watched    = 0
    dup_count  = 0

    for rec in judge_recs:
        dup_key = rec.get("duplicate_key", "")
        ta      = rec.get("target_agent", "—")

        if dup_key in existing_dispatch or dup_key in existing_watch:
            dup_count += 1
            continue

        is_disp, reason = _is_dispatch(rec)
        rb_cmd = f"python3 lib/ceo_config_executor.py rollback {ta}"

        base_rec = {
            "routed_at":      _now_jst(),
            "target_agent":   ta,
            "duplicate_key":  dup_key,
            "agent_key":      rec.get("agent_key", ""),
            "patch_path":     rec.get("patch_path", ""),
            "backup_path":    rec.get("backup_path", ""),
            "config_hash":    rec.get("config_hash", ""),
            "judge_label":    "rollback_recommended",
            "judge_reason":   rec.get("judge_reason", ""),
            "performance_delta": rec.get("performance_delta", 0),
            "route_reason":   reason,
            "rollback_command": rb_cmd,
            "source_queue":   "ceo_post_apply_judge_queue",
            "ceo_judgment":   "ミュウツーCEO rollback振り分け",
        }

        if is_disp:
            existing_dispatch.add(dup_key)
            _append_jsonl(ROLLBACK_DISPATCH_QUEUE, {
                **base_rec,
                "router_status": "pending",
                "dispatch_priority": "HIGH",
            })
            _append_jsonl(ROLLBACK_DISPATCH_HISTORY, {
                "processed_at": _now_jst(),
                "target_agent": ta,
                "duplicate_key": dup_key,
                "status": "dispatched",
                "reason": reason,
                "rollback_command": rb_cmd,
                "ceo_judgment": "ミュウツーCEO rollback振り分け",
            })
            dispatched += 1
        else:
            existing_watch.add(dup_key)
            _append_jsonl(ROLLBACK_WATCH_QUEUE, {
                **base_rec,
                "router_status": "pending",
                "watch_priority": "MEDIUM",
            })
            _append_jsonl(ROLLBACK_WATCH_HISTORY, {
                "processed_at": _now_jst(),
                "target_agent": ta,
                "duplicate_key": dup_key,
                "status": "watching",
                "reason": reason,
                "ceo_judgment": "ミュウツーCEO rollback振り分け",
            })
            watched += 1

    dispatch_pending = sum(1 for r in _load_jsonl(ROLLBACK_DISPATCH_QUEUE)
                           if r.get("router_status") == "pending")
    watch_pending    = sum(1 for r in _load_jsonl(ROLLBACK_WATCH_QUEUE)
                           if r.get("router_status") == "pending")
    return {
        "dispatched": dispatched,
        "watched":    watched,
        "dup":        dup_count,
        "dispatch_pending": dispatch_pending,
        "watch_pending":    watch_pending,
    }


def get_rollback_router_stats() -> dict:
    dispatch_recs = _load_jsonl(ROLLBACK_DISPATCH_QUEUE)
    watch_recs    = _load_jsonl(ROLLBACK_WATCH_QUEUE)
    dp = [r for r in dispatch_recs if r.get("router_status") == "pending"]
    wp = [r for r in watch_recs    if r.get("router_status") == "pending"]
    top_d = dp[-1] if dp else {}
    top_w = wp[-1] if wp else {}
    return {
        "rollback_dispatch_pending": len(dp),
        "rollback_watch_pending":    len(wp),
        "rollback_dispatch_latest_agent":  top_d.get("target_agent", "—"),
        "rollback_dispatch_latest_reason": top_d.get("route_reason", "—"),
        "rollback_dispatch_latest_cmd":    top_d.get("rollback_command", "—"),
        "rollback_watch_latest_agent":     top_w.get("target_agent", "—"),
    }


if __name__ == "__main__":
    import json as _json
    result = run_rollback_router()
    print(_json.dumps(result, ensure_ascii=False, indent=2))
    print(_json.dumps(get_rollback_router_stats(), ensure_ascii=False, indent=2))
