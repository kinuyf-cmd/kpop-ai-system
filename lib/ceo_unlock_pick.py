#!/usr/bin/env python3
"""
ceo_unlock_pick.py — unlock実行前最終1件決定レイヤー v1.0
CEO: ミュウツー / オーナー: 人間（閲覧専用）

【役割】
  unlock_judge_queue / unlock_explain_queue を参照し
  「今打つべき unlock コマンド 1件」を pick する。

【ソート基準（優先順）】
  1. 売上直結AI (x_post, x_post_b, persian, wordpress_post 等)
  2. priority HIGH / CRITICAL
  3. stale 対象でない
  4. latest updated
  5. target_agent 昇順

【制約】
  - 実行禁止（提案のみ）
  - execution_blocked = true のまま
  - stale対象は pick 対象外
  - invariant違反に関与するエージェントは pick 対象外
  - rollback_dispatch 対象エージェントは pick 対象外
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

UNLOCK_JUDGE_QUEUE    = LOGS / "ceo_reinject_unlock_judge_queue.jsonl"
UNLOCK_EXPLAIN_QUEUE  = LOGS / "ceo_unlock_explain_queue.jsonl"
UNLOCK_EXECUTE_QUEUE  = LOGS / "ceo_unlock_execute_queue.jsonl"
STALE_OP_QUEUE        = LOGS / "ceo_stale_operation_queue.jsonl"
INVARIANT_QUEUE       = LOGS / "ceo_invariant_violation_queue.jsonl"
ROLLBACK_DISPATCH_Q   = LOGS / "ceo_rollback_dispatch_queue.jsonl"

PICK_QUEUE   = LOGS / "ceo_unlock_pick_queue.jsonl"
PICK_HISTORY = LOGS / "ceo_unlock_pick_history.jsonl"

# 売上直結AI（優先度最上位）
REVENUE_AGENTS = {"x投稿", "x投稿b", "x_post", "x_post_b", "persian", "ペルシャン",
                  "wordpress_post", "wp投稿"}

PRIORITY_SCORE = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}


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


def _pick_key(dup_key: str) -> str:
    return f"pick|{dup_key}"


def _is_revenue(ta: str) -> bool:
    return ta.lower().replace(" ", "").replace("　", "") in REVENUE_AGENTS


def _pick_score(rec: dict, stale_agents: set, inv_agents: set, rb_agents: set) -> float | None:
    """スコア計算。None = pick 対象外。"""
    ta   = rec.get("target_agent", "")
    prio = rec.get("priority", "LOW")

    # 除外条件
    if ta in stale_agents:
        return None
    if ta in inv_agents:
        return None
    if ta in rb_agents:
        return None

    score = 0.0
    score += 100.0 if _is_revenue(ta) else 0.0
    score += PRIORITY_SCORE.get(prio, 0) * 10.0
    score += float(rec.get("priority_score", 0)) * 5.0
    return score


# ═══════════════════════════════════════════════════════════════════
# メイン pick
# ═══════════════════════════════════════════════════════════════════

def run_unlock_pick() -> dict:
    """
    unlock_judge_queue (judge_status=pending) から最優先1件を pick する。
    """
    judge_recs = [r for r in _load_jsonl(UNLOCK_JUDGE_QUEUE)
                  if r.get("judge_status") == "pending"]

    # 既 unlock 済みの duplicate_key は除外
    already_unlocked = {r.get("duplicate_key", "")
                        for r in _load_jsonl(UNLOCK_EXECUTE_QUEUE)
                        if r.get("unlock_status") == "unlocked"
                        and r.get("actual_unlocked") is True}

    stale_agents = {r.get("target_agent", "")
                    for r in _load_jsonl(STALE_OP_QUEUE)
                    if r.get("status") == "pending"
                    and r.get("duplicate_key", "") not in already_unlocked}
    inv_agents   = {r.get("target_agent", "")
                    for r in _load_jsonl(INVARIANT_QUEUE)
                    if r.get("violation_status") == "pending"}
    rb_agents    = {r.get("target_agent", "")
                    for r in _load_jsonl(ROLLBACK_DISPATCH_Q)
                    if r.get("router_status") == "pending"}

    # 既存 pick record の重複チェック
    existing_picks = {r.get("pick_key", "")
                      for r in _load_jsonl(PICK_QUEUE)
                      if r.get("pick_status") in ("pending", "active")}

    # スコアリング
    candidates = []
    for rec in judge_recs:
        dk = rec.get("duplicate_key", "")
        if dk in already_unlocked:
            continue
        score = _pick_score(rec, stale_agents, inv_agents, rb_agents)
        if score is None:
            continue
        candidates.append((score, rec))

    candidates.sort(key=lambda x: -x[0])

    added = 0
    dup   = 0

    for rank, (score, rec) in enumerate(candidates):
        dk   = rec.get("duplicate_key", "")
        ta   = rec.get("target_agent", "—")
        pkey = _pick_key(dk)

        if pkey in existing_picks:
            dup += 1
            continue

        existing_picks.add(pkey)
        is_top = (rank == 0)

        # explain_queue から why_now 補完
        explain_recs = [e for e in _load_jsonl(UNLOCK_EXPLAIN_QUEUE)
                        if e.get("duplicate_key") == dk]
        explain_top  = explain_recs[-1] if explain_recs else {}

        why_now = explain_top.get("why_now", (
            f"priority={rec.get('priority','—')}(score={rec.get('priority_score',0):.4f}), "
            f"feedback_type={rec.get('feedback_type','—')}, "
            f"rank={rank+1}/{len(candidates)}"
        ))
        what_changes = explain_top.get("what_changes",
            "unlock_execute_queue: pending → unlocked; apply_execute_queue: pending生成")
        rollback_cmd = explain_top.get("rollback_command",
            f"python3 lib/ceo_config_executor.py rollback {ta}  # unlock失敗時rollback")
        cmd = f'python3 lib/ceo_unlock_executor.py unlock "{dk}"'

        expected_effect = (
            f"unlock_status: pending → unlocked / "
            f"apply_execute_queue に pending 生成 / "
            f"execution_blocked: true → false（手動確認後）"
        )

        pick_rec = {
            "picked_at":        _now_jst(),
            "pick_key":         pkey,
            "duplicate_key":    dk,
            "target_agent":     ta,
            "agent_key":        rec.get("agent_key", ""),
            "priority":         rec.get("priority", "—"),
            "priority_score":   rec.get("priority_score", 0),
            "pick_score":       round(score, 4),
            "pick_rank":        rank + 1,
            "is_top":           is_top,
            "is_revenue":       _is_revenue(ta),
            "feedback_type":    rec.get("feedback_type", "—"),
            "patch_path":       rec.get("patch_path", "—"),
            "after_value":      (rec.get("after_value") or "")[:200],
            "command":          cmd,
            "why_now":          why_now[:200],
            "expected_effect":  expected_effect,
            "what_changes":     what_changes[:200],
            "rollback_command": rollback_cmd[:200],
            "pick_status":      "active" if is_top else "pending",
            "is_stale_excluded": ta in stale_agents,
            "execution_blocked": True,
            "write_scope":      "queue_only",
            "source_queue":     "ceo_reinject_unlock_judge_queue",
            "ceo_judgment":     "ミュウツーCEO unlock実行候補",
        }
        _append_jsonl(PICK_QUEUE, pick_rec)
        _append_jsonl(PICK_HISTORY, {
            "processed_at":  _now_jst(),
            "pick_key":      pkey,
            "target_agent":  ta,
            "pick_rank":     rank + 1,
            "pick_score":    round(score, 4),
            "is_top":        is_top,
            "status":        "picked",
            "ceo_judgment":  "ミュウツーCEO unlock実行候補",
        })
        added += 1

    all_picks = _load_jsonl(PICK_QUEUE)
    top1 = next((r for r in reversed(all_picks) if r.get("is_top") and r.get("pick_status") in ("active","pending")), {})

    return {
        "added":         added,
        "dup":           dup,
        "candidates":    len(candidates),
        "top1_agent":    top1.get("target_agent", "—"),
        "top1_command":  top1.get("command", "—"),
        "top1_excluded_by_stale": top1.get("is_stale_excluded", False),
    }


def get_unlock_pick_stats() -> dict:
    recs = _load_jsonl(PICK_QUEUE)
    top1 = next((r for r in reversed(recs) if r.get("is_top") and r.get("pick_status") in ("active","pending")), {})
    return {
        "unlock_pick_target_agent":  top1.get("target_agent", "—"),
        "unlock_pick_command":       top1.get("command", "—"),
        "unlock_pick_why_now":       top1.get("why_now", "—")[:100],
        "unlock_pick_score":         top1.get("pick_score", 0),
        "unlock_pick_is_revenue":    top1.get("is_revenue", False),
        "unlock_pick_rollback_cmd":  top1.get("rollback_command", "—"),
        "unlock_pick_effect":        top1.get("expected_effect", "—"),
        "unlock_pick_total":         len([r for r in recs if r.get("pick_status") in ("active","pending")]),
    }


if __name__ == "__main__":
    import json as _json
    result = run_unlock_pick()
    print(_json.dumps(result, ensure_ascii=False, indent=2))
    print(_json.dumps(get_unlock_pick_stats(), ensure_ascii=False, indent=2))
