#!/usr/bin/env python3
"""
ceo_lifecycle_trace.py — duplicate_key ライフサイクルトレース v1.0
CEO: ミュウツー / オーナー: 人間（閲覧専用）

【役割】
  duplicate_key がどのレーンまで到達したかを一覧でトレースする。
  最新20件程度。読み取り専用（書き込みなし）。

【対象レーン（順序）】
  improvement → ready → simulation → ranked → packet → dispatch →
  stub → dry_run → candidate → limited → gate → patch_plan →
  apply_queue → apply_result → reinject_priority → reinject_dispatch →
  reinject_gate → patch_ready → reserve → commit →
  apply_gate → apply_ready → unlock_candidate → unlock_judge →
  unlock_execute → apply_execute → apply_result_exec →
  post_apply_judge → rollback_dispatch / rollback_watch

【制約】
  - 書き込みなし（reads only）
  - LLM 判断なし
"""

from __future__ import annotations

import json
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"

# (label, path, dup_key_field, status_field)
LANE_DEFS: list[tuple[str, str, str, str]] = [
    ("improvement",       "logs/ceo_improvement_queue.jsonl",                        "duplicate_key", "status"),
    ("ready",             "logs/ceo_ready_queue.jsonl",                               "duplicate_key", "ready_status"),
    ("simulation",        "logs/ceo_execution_simulation.jsonl",                      "duplicate_key", "simulation_status"),
    ("ranked",            "logs/ceo_execution_ranked_queue.jsonl",                    "duplicate_key", "rank_status"),
    ("packet",            "logs/ceo_execution_packet_queue.jsonl",                    "duplicate_key", "packet_status"),
    ("dispatch",          "logs/ceo_execution_dispatch_request_queue.jsonl",          "duplicate_key", "dispatch_status"),
    ("stub",              "logs/ceo_execution_executor_stub_queue.jsonl",             "duplicate_key", "stub_status"),
    ("dry_run",           "logs/ceo_execution_dry_run_result_queue.jsonl",            "duplicate_key", "dry_run_status"),
    ("candidate",         "logs/ceo_execution_candidate_queue.jsonl",                "duplicate_key", "candidate_status"),
    ("limited",           "logs/ceo_limited_execution_queue.jsonl",                  "duplicate_key", "limited_status"),
    ("gate",              "logs/ceo_execution_guard_result_queue.jsonl",              "duplicate_key", "guard_status"),
    ("patch_plan",        "logs/ceo_config_patch_plan_queue.jsonl",                  "duplicate_key", "plan_status"),
    ("apply_queue",       "logs/ceo_config_apply_queue.jsonl",                       "duplicate_key", "apply_status"),
    ("apply_result",      "logs/ceo_config_apply_result_queue.jsonl",                "duplicate_key", "result_status"),
    ("reinject_priority", "logs/ceo_reinject_priority_queue.jsonl",                  "duplicate_key", "priority_status"),
    ("reinject_dispatch", "logs/ceo_reinject_dispatch_queue.jsonl",                  "duplicate_key", "dispatch_status"),
    ("reinject_gate",     "logs/ceo_reinject_gate_queue.jsonl",                      "duplicate_key", "gate_status"),
    ("patch_ready",       "logs/ceo_reinject_patch_ready_queue.jsonl",               "duplicate_key", "patch_status"),
    ("reserve",           "logs/ceo_reinject_patch_reserve_queue.jsonl",             "duplicate_key", "reserve_status"),
    ("commit",            "logs/ceo_reinject_patch_commit_queue.jsonl",              "duplicate_key", "commit_status"),
    ("apply_gate",        "logs/ceo_reinject_apply_gate_queue.jsonl",                "duplicate_key", "gate_status"),
    ("apply_ready",       "logs/ceo_reinject_apply_ready_queue.jsonl",               "duplicate_key", "ready_status"),
    ("unlock_candidate",  "logs/ceo_reinject_apply_unlock_candidate_queue.jsonl",    "duplicate_key", "candidate_status"),
    ("unlock_judge",      "logs/ceo_reinject_unlock_judge_queue.jsonl",              "duplicate_key", "judge_status"),
    ("unlock_execute",    "logs/ceo_unlock_execute_queue.jsonl",                     "duplicate_key", "unlock_status"),
    ("apply_execute",     "logs/ceo_apply_execute_queue.jsonl",                      "duplicate_key", "apply_execute_status"),
    ("apply_result_exec", "logs/ceo_apply_execute_result_queue.jsonl",               "duplicate_key", "result_status"),
    ("post_apply_judge",  "logs/ceo_post_apply_judge_queue.jsonl",                   "duplicate_key", "judge_label"),
    ("rollback_dispatch", "logs/ceo_rollback_dispatch_queue.jsonl",                  "duplicate_key", "router_status"),
    ("rollback_watch",    "logs/ceo_rollback_watch_queue.jsonl",                     "duplicate_key", "router_status"),
]

LANE_ORDER = [ld[0] for ld in LANE_DEFS]


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


def build_trace_index(top_n: int = 20) -> list[dict]:
    """
    全レーンをスキャンし duplicate_key ごとの到達レーンを返す。
    最大 top_n 件（最も進んだもの優先）。
    """
    # duplicate_key → {lane: status}
    trace: dict[str, dict[str, str]] = {}

    for label, rel_path, dup_field, status_field in LANE_DEFS:
        path = BASE / rel_path
        for rec in _load_jsonl(path):
            dup_key = rec.get(dup_field, "")
            if not dup_key:
                continue
            status = str(rec.get(status_field, "present"))
            if dup_key not in trace:
                trace[dup_key] = {}
            # 後から来たほうが最新 → 上書き
            trace[dup_key][label] = status

    if not trace:
        return []

    # 到達レーン数でソート（多いほど進んだ）
    def _score(item: tuple) -> tuple:
        dup_key, lanes = item
        last_idx = -1
        for i, lane in enumerate(LANE_ORDER):
            if lane in lanes:
                last_idx = i
        return (-last_idx, -len(lanes))

    sorted_items = sorted(trace.items(), key=_score)[:top_n]

    result = []
    for dup_key, lanes in sorted_items:
        reached = [ln for ln in LANE_ORDER if ln in lanes]
        latest_lane  = reached[-1] if reached else "—"
        latest_status = lanes.get(latest_lane, "—")
        # dup_key から agent/type 推定
        parts = dup_key.split("|")
        agent = parts[0] if parts else "—"
        result.append({
            "duplicate_key":   dup_key,
            "agent":           agent,
            "reached_lanes":   reached,
            "lane_count":      len(reached),
            "latest_lane":     latest_lane,
            "latest_status":   latest_status,
            "lane_summary":    " → ".join(reached[-5:]) if len(reached) > 5 else " → ".join(reached),
        })
    return result


def get_lifecycle_trace_stats(top_n: int = 20) -> dict:
    traces = build_trace_index(top_n)
    top3   = traces[:3]
    return {
        "lifecycle_trace_count":        len(traces),
        "lifecycle_trace_top1_key":     top3[0]["duplicate_key"][:80] if len(top3) > 0 else "—",
        "lifecycle_trace_top1_agent":   top3[0]["agent"] if len(top3) > 0 else "—",
        "lifecycle_trace_top1_lane":    top3[0]["latest_lane"] if len(top3) > 0 else "—",
        "lifecycle_trace_top1_lanes":   top3[0]["lane_count"] if len(top3) > 0 else 0,
        "lifecycle_trace_top2_agent":   top3[1]["agent"] if len(top3) > 1 else "—",
        "lifecycle_trace_top3_agent":   top3[2]["agent"] if len(top3) > 2 else "—",
        "lifecycle_traces":             traces,
    }


if __name__ == "__main__":
    import json as _json
    stats = get_lifecycle_trace_stats()
    # traces はデカいので件数だけ表示
    traces = stats.pop("lifecycle_traces", [])
    print(_json.dumps(stats, ensure_ascii=False, indent=2))
    for t in traces[:5]:
        print(f"  {t['agent']:20s} lane={t['lane_count']:2d} last={t['latest_lane']:20s} {t['lane_summary']}")
