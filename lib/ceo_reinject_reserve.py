"""
ceo_reinject_reserve.py — 再接続予約レーン
入力: ceo_reinject_patch_ready_queue.jsonl
出力: ceo_reinject_patch_reserve_queue.jsonl / ceo_reinject_patch_reserve_history.jsonl

ceo_config_patch_plan_queue への実書き戻しは一切しない。
予約・優先順位付け・可視化のみ。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"

PATCH_READY_QUEUE_PATH   = LOGS / "ceo_reinject_patch_ready_queue.jsonl"
RESERVE_QUEUE_PATH       = LOGS / "ceo_reinject_patch_reserve_queue.jsonl"
RESERVE_HISTORY_PATH     = LOGS / "ceo_reinject_patch_reserve_history.jsonl"

_REVENUE_AGENTS  = {"バタフリー", "サーナイト", "カイリュー", "WP投稿", "アルセウス", "X投稿B"}
_TARGET_LABELS   = {"CRITICAL", "HIGH", "MEDIUM"}


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
    agent = rec.get("target_agent", "")
    ftype = rec.get("feedback_type", "")
    hint  = (rec.get("next_improvement_hint", "") or "").strip()
    if hint:
        return f"{agent}|{ftype}|{hint[:80]}"
    action = (rec.get("proposed_reinject_action", "") or "").strip()
    return f"{agent}|{ftype}|{action[:80]}"


# ────────────────────────────────────────────
# スコアリング
# ────────────────────────────────────────────

def _freshness_score(reinject_order: int) -> float:
    if reinject_order == 1:
        return 1.00
    if reinject_order == 2:
        return 0.85
    if reinject_order == 3:
        return 0.70
    return 0.55


def _revenue_restore_score(agent: str) -> float:
    return 1.00 if agent in _REVENUE_AGENTS else 0.50


def _patch_simplicity_score(feedback_type: str) -> float:
    return {"minor_adjust": 0.90, "urgent_fix": 0.60, "keep": 0.30}.get(feedback_type, 0.40)


def _reserve_priority_score(rec: dict) -> float:
    ri_score  = float(rec.get("reinject_priority_score", 0.0))
    order     = int(rec.get("reinject_order", 99))
    agent     = rec.get("target_agent", "")
    ftype     = rec.get("feedback_type", "")

    fresh     = _freshness_score(order)
    revenue   = _revenue_restore_score(agent)
    simplicity = _patch_simplicity_score(ftype)

    score = (
        ri_score   * 0.45 +
        fresh      * 0.20 +
        revenue    * 0.25 +
        simplicity * 0.10
    )
    return round(score, 4)


def _reserve_label(score: float) -> str:
    if score >= 0.80:
        return "CRITICAL"
    if score >= 0.65:
        return "HIGH"
    if score >= 0.45:
        return "MEDIUM"
    return "LOW"


# ────────────────────────────────────────────
# フェーズ1+2: patch_ready → reserve
# ────────────────────────────────────────────

def build_patch_reserve_queue() -> dict:
    """patch_ready_queue → patch_reserve_queue（スコアリング + 順位付け）"""
    ready_recs     = _load_jsonl(PATCH_READY_QUEUE_PATH)
    existing_res   = _load_jsonl(RESERVE_QUEUE_PATH)

    existing_dup_keys: set[str] = {
        r.get("duplicate_key", "")
        for r in existing_res
        if r.get("reserve_status") in ("pending", "archived")
    }

    # 対象抽出
    candidates = [
        r for r in ready_recs
        if r.get("patch_ready_status") == "pending"
        and r.get("patch_ready") is True
        and r.get("reinject_priority_label") in _TARGET_LABELS
    ]

    promoted  = 0
    dup_count = 0
    scored: list[dict] = []

    for rec in candidates:
        dup_key   = _make_dup_key(rec)
        res_score = _reserve_priority_score(rec)
        res_label = _reserve_label(res_score)

        reserve_rec = {
            "reserved_at":             _now_jst(),
            "source_readied_at":       rec.get("readied_at", ""),
            "target_agent":            rec.get("target_agent", ""),
            "feedback_type":           rec.get("feedback_type", ""),
            "reinject_priority_score": rec.get("reinject_priority_score", 0.0),
            "reinject_priority_label": rec.get("reinject_priority_label", ""),
            "reinject_order":          rec.get("reinject_order", 0),
            "proposed_reinject_action": rec.get("proposed_reinject_action", ""),
            "next_improvement_hint":   rec.get("next_improvement_hint", ""),
            "patch_target_lane":       rec.get("patch_target_lane", "ceo_config_patch_plan_queue"),
            "reserve_priority_score":  res_score,
            "reserve_order":           0,   # 後でソート後に付番
            "reserve_label":           res_label,
            "reserve_status":          "pending",
            "reserve_ready":           True,
            "execution_blocked":       True,
            "write_scope":             "none",
            "reserved_from":           "ceo_reinject_patch_ready_queue",
            "duplicate_key":           dup_key,
            "ceo_judgment":            "ミュウツーCEO再接続予約",
        }

        if dup_key in existing_dup_keys:
            dup_count += 1
            _append_jsonl(RESERVE_HISTORY_PATH, {
                **reserve_rec,
                "reserve_status": "reserve_duplicate",
                "reason": f"同一 duplicate_key が既に pending/archived に存在: {dup_key}",
            })
            continue

        existing_dup_keys.add(dup_key)
        scored.append(reserve_rec)
        promoted += 1

    # ソート: reserve_priority_score desc → reinject_priority_score desc → reinject_order asc → agent asc
    scored.sort(key=lambda r: (
        -r["reserve_priority_score"],
        -r["reinject_priority_score"],
        int(r.get("reinject_order", 999)),
        r["target_agent"],
    ))

    # reserve_order 付番
    for i, r in enumerate(scored, start=1):
        r["reserve_order"] = i

    for r in scored:
        _append_jsonl(RESERVE_QUEUE_PATH, r)

    pending_total = sum(
        1 for r in _load_jsonl(RESERVE_QUEUE_PATH)
        if r.get("reserve_status") == "pending"
    )

    return {"promoted": promoted, "dup": dup_count, "pending": pending_total}


# ────────────────────────────────────────────
# 統計
# ────────────────────────────────────────────

def get_reinject_reserve_stats() -> dict:
    recs = [r for r in _load_jsonl(RESERVE_QUEUE_PATH) if r.get("reserve_status") == "pending"]
    counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for r in recs:
        lbl = r.get("reserve_label", "LOW")
        counts[lbl] = counts.get(lbl, 0) + 1

    sorted_r = sorted(recs, key=lambda r: (int(r.get("reserve_order", 999)), -float(r.get("reserve_priority_score", 0))))
    top1   = sorted_r[0] if sorted_r else {}
    latest = recs[-1]    if recs     else {}

    return {
        "reinject_reserve_pending_count":  len(recs),
        "reinject_reserve_critical_count": counts["CRITICAL"],
        "reinject_reserve_high_count":     counts["HIGH"],
        "reinject_reserve_medium_count":   counts["MEDIUM"],
        "reinject_reserve_low_count":      counts["LOW"],
        "reinject_reserve_top1_agent":     top1.get("target_agent", "—"),
        "reinject_reserve_top1_score":     top1.get("reserve_priority_score", 0.0),
        "reinject_reserve_top1_label":     top1.get("reserve_label", "—"),
        "reinject_reserve_latest_agent":   latest.get("target_agent", "—"),
        "reinject_reserve_latest_label":   latest.get("reserve_label", "—"),
        "reinject_reserve_latest_order":   latest.get("reserve_order", 0),
    }


# ────────────────────────────────────────────
# 統合実行
# ────────────────────────────────────────────

def run_reinject_reserve_cycle() -> dict:
    return build_patch_reserve_queue()
