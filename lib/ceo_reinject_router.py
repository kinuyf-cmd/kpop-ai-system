"""
ceo_reinject_router.py — 再投入交通整理レイヤー
フェーズ1: reinject_priority_queue → reinject_dispatch_queue
フェーズ2: reinject_dispatch_queue → reinject_limited_return_queue

実行・config書込・WP変更は一切しない。候補の抽出・振り分け・可視化のみ。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"

REINJECT_PRIORITY_QUEUE_PATH  = LOGS / "ceo_reinject_priority_queue.jsonl"
DISPATCH_QUEUE_PATH           = LOGS / "ceo_reinject_dispatch_queue.jsonl"
DISPATCH_HISTORY_PATH         = LOGS / "ceo_reinject_dispatch_history.jsonl"
LIMITED_RETURN_QUEUE_PATH     = LOGS / "ceo_reinject_limited_return_queue.jsonl"
LIMITED_RETURN_HISTORY_PATH   = LOGS / "ceo_reinject_limited_return_history.jsonl"

# 売上直結AI（MEDIUMでも限定再投入候補に上げる対象）
_REVENUE_AGENTS = {"バタフリー", "サーナイト", "カイリュー", "WP投稿", "アルセウス", "X投稿B"}

# dispatch対象ラベル
_DISPATCH_LABELS = {"CRITICAL", "HIGH", "MEDIUM"}


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


# ────────────────────────────────────────────
# フェーズ1: priority → dispatch
# ────────────────────────────────────────────

def build_dispatch_queue() -> dict:
    """reinject_priority_queue の CRITICAL/HIGH/MEDIUM を dispatch_queue へ振り分け"""
    priority_recs = _load_jsonl(REINJECT_PRIORITY_QUEUE_PATH)
    existing_disp = _load_jsonl(DISPATCH_QUEUE_PATH)

    existing_dup_keys: set[str] = {
        r.get("duplicate_key", "")
        for r in existing_disp
        if r.get("dispatch_status") in ("pending", "archived")
    }

    # 対象抽出: pending + 対象ラベル + reinject_order > 0
    candidates = [
        r for r in priority_recs
        if r.get("status") == "pending"
        and r.get("reinject_priority_label") in _DISPATCH_LABELS
        and int(r.get("reinject_order", 0)) > 0
    ]

    # ソート: reinject_order asc → reinject_priority_score desc
    candidates.sort(key=lambda r: (
        int(r.get("reinject_order", 999)),
        -float(r.get("reinject_priority_score", 0)),
    ))

    promoted = 0
    dup_count = 0

    for rec in candidates:
        dup_key = rec.get("duplicate_key", "")

        dispatch_rec = {
            "dispatched_at":           _now_jst(),
            "source_ranked_at":        rec.get("ranked_at", ""),
            "target_agent":            rec.get("target_agent", ""),
            "feedback_type":           rec.get("feedback_type", ""),
            "reinject_priority_score": rec.get("reinject_priority_score", 0.0),
            "reinject_priority_label": rec.get("reinject_priority_label", ""),
            "reinject_order":          rec.get("reinject_order", 0),
            "next_improvement_hint":   rec.get("next_improvement_hint", ""),
            "proposed_reinject_action": rec.get("proposed_reinject_action", ""),
            "dispatch_status":         "pending",
            "dispatch_ready":          True,
            "execution_blocked":       True,
            "write_scope":             "none",
            "dispatch_from":           "ceo_reinject_priority_queue",
            "duplicate_key":           dup_key,
            "ceo_judgment":            "ミュウツーCEO再投入ディスパッチ",
        }

        if dup_key in existing_dup_keys:
            dup_count += 1
            _append_jsonl(DISPATCH_HISTORY_PATH, {
                **dispatch_rec,
                "dispatch_status": "dispatch_duplicate",
                "reason": f"同一 duplicate_key が既に pending/archived に存在: {dup_key}",
            })
            continue

        existing_dup_keys.add(dup_key)
        _append_jsonl(DISPATCH_QUEUE_PATH, dispatch_rec)
        promoted += 1

    pending_total = sum(
        1 for r in _load_jsonl(DISPATCH_QUEUE_PATH)
        if r.get("dispatch_status") == "pending"
    )

    return {"promoted": promoted, "dup": dup_count, "pending": pending_total}


# ────────────────────────────────────────────
# フェーズ2: dispatch → limited_return
# ────────────────────────────────────────────

def build_limited_return_queue() -> dict:
    """dispatch_queue の上位候補を limited_return_queue へ振り分け（実書き戻しは未実装）"""
    dispatch_recs = _load_jsonl(DISPATCH_QUEUE_PATH)
    existing_ret  = _load_jsonl(LIMITED_RETURN_QUEUE_PATH)

    existing_dup_keys: set[str] = {
        r.get("duplicate_key", "")
        for r in existing_ret
        if r.get("return_status") in ("pending", "archived")
    }

    # 対象条件: pending + dispatch_ready=True + ラベル条件
    def _qualifies(r: dict) -> bool:
        if r.get("dispatch_status") != "pending":
            return False
        if not r.get("dispatch_ready", False):
            return False
        lbl   = r.get("reinject_priority_label", "")
        agent = r.get("target_agent", "")
        if lbl in ("CRITICAL", "HIGH"):
            return True
        if lbl == "MEDIUM" and agent in _REVENUE_AGENTS:
            return True
        return False

    candidates = [r for r in dispatch_recs if _qualifies(r)]

    # ソート: reinject_order asc → score desc
    candidates.sort(key=lambda r: (
        int(r.get("reinject_order", 999)),
        -float(r.get("reinject_priority_score", 0)),
    ))

    promoted = 0
    dup_count = 0

    for rec in candidates:
        dup_key = rec.get("duplicate_key", "")

        return_rec = {
            "returned_at":             _now_jst(),
            "source_dispatched_at":    rec.get("dispatched_at", ""),
            "target_agent":            rec.get("target_agent", ""),
            "feedback_type":           rec.get("feedback_type", ""),
            "reinject_priority_score": rec.get("reinject_priority_score", 0.0),
            "reinject_priority_label": rec.get("reinject_priority_label", ""),
            "reinject_order":          rec.get("reinject_order", 0),
            "proposed_reinject_action": rec.get("proposed_reinject_action", ""),
            "next_improvement_hint":   rec.get("next_improvement_hint", ""),
            "return_ready":            True,
            "return_target_lane":      "limited_execution_queue",
            "return_status":           "pending",
            "execution_blocked":       True,
            "write_scope":             "none",
            "returned_from":           "ceo_reinject_dispatch_queue",
            "duplicate_key":           dup_key,
            "ceo_judgment":            "ミュウツーCEO限定再投入候補",
        }

        if dup_key in existing_dup_keys:
            dup_count += 1
            _append_jsonl(LIMITED_RETURN_HISTORY_PATH, {
                **return_rec,
                "return_status": "return_duplicate",
                "reason": f"同一 duplicate_key が既に pending/archived に存在: {dup_key}",
            })
            continue

        existing_dup_keys.add(dup_key)
        _append_jsonl(LIMITED_RETURN_QUEUE_PATH, return_rec)
        promoted += 1

    pending_total = sum(
        1 for r in _load_jsonl(LIMITED_RETURN_QUEUE_PATH)
        if r.get("return_status") == "pending"
    )

    return {"promoted": promoted, "dup": dup_count, "pending": pending_total}


# ────────────────────────────────────────────
# 統計
# ────────────────────────────────────────────

def get_reinject_dispatch_stats() -> dict:
    recs = [r for r in _load_jsonl(DISPATCH_QUEUE_PATH) if r.get("dispatch_status") == "pending"]
    counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for r in recs:
        lbl = r.get("reinject_priority_label", "LOW")
        counts[lbl] = counts.get(lbl, 0) + 1

    sorted_recs = sorted(recs, key=lambda r: (int(r.get("reinject_order", 999)), -float(r.get("reinject_priority_score", 0))))
    top1   = sorted_recs[0] if sorted_recs else {}
    latest = recs[-1]       if recs        else {}

    return {
        "reinject_dispatch_pending_count": len(recs),
        "reinject_dispatch_high_count":    counts.get("HIGH", 0) + counts.get("CRITICAL", 0),
        "reinject_dispatch_medium_count":  counts.get("MEDIUM", 0),
        "reinject_dispatch_latest_agent":  latest.get("target_agent", "—"),
        "reinject_dispatch_latest_label":  latest.get("reinject_priority_label", "—"),
        "reinject_dispatch_top1_agent":    top1.get("target_agent", "—"),
        "reinject_dispatch_top1_score":    top1.get("reinject_priority_score", 0.0),
        "reinject_dispatch_top1_label":    top1.get("reinject_priority_label", "—"),
    }


def get_reinject_return_stats() -> dict:
    recs = [r for r in _load_jsonl(LIMITED_RETURN_QUEUE_PATH) if r.get("return_status") == "pending"]
    counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for r in recs:
        lbl = r.get("reinject_priority_label", "LOW")
        counts[lbl] = counts.get(lbl, 0) + 1

    sorted_recs = sorted(recs, key=lambda r: (int(r.get("reinject_order", 999)), -float(r.get("reinject_priority_score", 0))))
    top1   = sorted_recs[0] if sorted_recs else {}
    latest = recs[-1]       if recs        else {}

    return {
        "reinject_return_pending_count": len(recs),
        "reinject_return_high_count":    counts.get("HIGH", 0) + counts.get("CRITICAL", 0),
        "reinject_return_medium_count":  counts.get("MEDIUM", 0),
        "reinject_return_latest_agent":  latest.get("target_agent", "—"),
        "reinject_return_latest_label":  latest.get("reinject_priority_label", "—"),
        "reinject_return_top1_agent":    top1.get("target_agent", "—"),
        "reinject_return_top1_score":    top1.get("reinject_priority_score", 0.0),
    }


# ────────────────────────────────────────────
# 統合実行
# ────────────────────────────────────────────

def run_reinject_routing_cycle() -> dict:
    disp_result   = build_dispatch_queue()
    return_result = build_limited_return_queue()
    return {
        "dispatch":      disp_result,
        "limited_return": return_result,
    }
