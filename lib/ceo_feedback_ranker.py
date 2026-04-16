"""
ceo_feedback_ranker.py — フィードバック再投入優先順位付け
入力: ceo_feedback_loop_queue.jsonl + dashboard_summary.json + revenue_metrics.json + agent_metrics.json
出力: ceo_reinject_priority_queue.jsonl / ceo_reinject_priority_history.jsonl
"""

from __future__ import annotations

import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"

FEEDBACK_QUEUE_PATH    = LOGS / "ceo_feedback_loop_queue.jsonl"
REINJECT_QUEUE_PATH    = LOGS / "ceo_reinject_priority_queue.jsonl"
REINJECT_HISTORY_PATH  = LOGS / "ceo_reinject_priority_history.jsonl"

DASHBOARD_SUMMARY_PATH = BASE / "dashboard_summary.json"
REVENUE_METRICS_PATH   = BASE / "revenue_metrics.json"
AGENT_METRICS_PATH     = BASE / "agent_metrics.json"

# 売上直結AI（売上影響スコアで加算対象）
_REVENUE_AGENTS = {"バタフリー", "サーナイト", "カイリュー", "WP投稿", "アルセウス", "X投稿B"}

# SEO直結AI
_SEO_AGENTS = {"バタフリー", "サーナイト", "X投稿B"}

# CVR直結AI
_CVR_AGENTS = {"カイリュー", "X投稿B", "サーナイト"}

# ラベル閾値
_LABEL_CRITICAL = 0.75
_LABEL_HIGH     = 0.55
_LABEL_MEDIUM   = 0.35


# ────────────────────────────────────────────
# ユーティリティ
# ────────────────────────────────────────────

def _now_jst() -> str:
    from datetime import timedelta
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


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


def _parse_delta(delta_str: str) -> float:
    """'+7.1%' → 0.071, '-12%' → -0.12"""
    try:
        return float(str(delta_str).replace("%", "").replace("+", "")) / 100.0
    except Exception:
        return 0.0


def _make_dup_key(rec: dict) -> str:
    agent  = rec.get("target_agent", "")
    ftype  = rec.get("feedback_type", "")
    hint   = rec.get("next_improvement_hint", "")[:80]
    return f"{agent}|{ftype}|{hint}"


def _priority_label(score: float) -> str:
    if score >= _LABEL_CRITICAL:
        return "CRITICAL"
    if score >= _LABEL_HIGH:
        return "HIGH"
    if score >= _LABEL_MEDIUM:
        return "MEDIUM"
    return "LOW"


# ────────────────────────────────────────────
# スコアリング
# ────────────────────────────────────────────

def _revenue_impact_score(rec: dict, agent_info: dict) -> float:
    score = 0.0
    ftype   = rec.get("feedback_type", "")
    agent   = rec.get("target_agent", "")
    srate   = float(rec.get("success_rate", 1.0))
    delta   = _parse_delta(rec.get("performance_delta", "0%"))

    # feedback_type 加点
    if ftype == "urgent_fix":
        score += 0.35
    elif ftype == "minor_adjust":
        score += 0.20

    # 売上直結AI 加点
    if agent in _REVENUE_AGENTS:
        score += 0.25

    # performance_delta がマイナス → 絶対値比例 +0.05〜+0.20
    if delta < 0:
        abs_delta = abs(delta)
        # 0〜0.30 の範囲を 0.05〜0.20 にマッピング
        score += _clamp(0.05 + abs_delta * 0.50)

    # success_rate 低下加点
    if srate < 0.85:
        score += 0.10
    if srate < 0.60:
        score += 0.10

    return _clamp(score)


def _seo_impact_score(rec: dict, agent_info: dict) -> float:
    score = 0.0
    agent = rec.get("target_agent", "")
    ftype = rec.get("feedback_type", "")
    eval_result = rec.get("evaluation_result", "")

    if agent in _SEO_AGENTS:
        score += 0.50
    if ftype == "urgent_fix":
        score += 0.30
    elif ftype == "minor_adjust":
        score += 0.15
    if eval_result == "degraded":
        score += 0.20

    return _clamp(score)


def _cvr_impact_score(rec: dict, agent_info: dict) -> float:
    score = 0.0
    agent = rec.get("target_agent", "")
    ftype = rec.get("feedback_type", "")
    eval_result = rec.get("evaluation_result", "")

    if agent in _CVR_AGENTS:
        score += 0.50
    if eval_result == "degraded":
        score += 0.30
    if ftype == "urgent_fix":
        score += 0.20

    return _clamp(score)


def _freshness_urgency_score(rec: dict, revenue_metrics: dict, agent_metrics: dict) -> float:
    score = 0.0
    ftype       = rec.get("feedback_type", "")
    eval_result = rec.get("evaluation_result", "")
    agent       = rec.get("target_agent", "")
    feedback_at = rec.get("feedback_at", "")

    # 汚染タイトル存在で加点
    contaminated = revenue_metrics.get("summary", {}).get("contaminated_title_count", 0)
    if contaminated > 0:
        score += 0.20

    # degraded は緊急
    if eval_result == "degraded":
        score += 0.35
    elif ftype == "urgent_fix":
        score += 0.25
    elif ftype == "minor_adjust":
        score += 0.10

    # feedback_at の新しさ（今日なら +0.15、1日以内なら +0.10）
    try:
        fb_date_str = feedback_at.replace(" JST", "").strip()
        fb_dt = datetime.strptime(fb_date_str, "%Y-%m-%d %H:%M:%S")
        from datetime import timedelta
        now = datetime.now()
        diff_hours = abs((now - fb_dt).total_seconds()) / 3600.0
        if diff_hours < 1:
            score += 0.15
        elif diff_hours < 24:
            score += 0.10
        elif diff_hours < 72:
            score += 0.05
    except Exception:
        pass

    # 売上直結AIが低成功率なら緊急度増
    srate = float(rec.get("success_rate", 1.0))
    if agent in _REVENUE_AGENTS and srate < 0.70:
        score += 0.15

    return _clamp(score)


def _reinject_priority_score(rv: float, seo: float, cvr: float, fresh: float) -> float:
    return round(rv * 0.40 + seo * 0.20 + cvr * 0.20 + fresh * 0.20, 4)


def _proposed_action(rec: dict) -> str:
    agent = rec.get("target_agent", "")
    ftype = rec.get("feedback_type", "")
    hint  = rec.get("next_improvement_hint", "")
    if ftype == "urgent_fix":
        return f"{agent} の directive を緊急見直し: {hint[:60]}..."
    elif ftype == "minor_adjust":
        return f"{agent} の directive を微調整: {hint[:60]}..."
    else:
        return f"{agent} の現状維持を確認"


# ────────────────────────────────────────────
# フェーズ1+2: ランキング生成
# ────────────────────────────────────────────

def run_feedback_ranking_cycle() -> dict:
    """feedback_loop_queue を読み reinject_priority_queue を生成する"""
    feedback_recs    = _load_jsonl(FEEDBACK_QUEUE_PATH)
    existing_queue   = _load_jsonl(REINJECT_QUEUE_PATH)
    revenue_metrics  = _load_json(REVENUE_METRICS_PATH)
    agent_metrics_raw= _load_json(AGENT_METRICS_PATH)
    agent_metrics    = agent_metrics_raw.get("agents", {})

    # 既存 pending/archived の duplicate_key セット
    existing_dup_keys: set[str] = set()
    for r in existing_queue:
        if r.get("status") in ("pending", "archived"):
            existing_dup_keys.add(r.get("duplicate_key", ""))

    scored: list[dict] = []
    dup_count   = 0
    ranked_count = 0

    for rec in feedback_recs:
        ftype = rec.get("feedback_type", "")
        # keep は再投入しない（スコアリングは行うが最低ランクで記録）
        agent = rec.get("target_agent", "")
        agent_info = agent_metrics.get(rec.get("agent_id", ""), {})

        rv   = _revenue_impact_score(rec, agent_info)
        seo  = _seo_impact_score(rec, agent_info)
        cvr  = _cvr_impact_score(rec, agent_info)
        fresh = _freshness_urgency_score(rec, revenue_metrics, agent_metrics)
        pri_score = _reinject_priority_score(rv, seo, cvr, fresh)
        label = _priority_label(pri_score)

        dup_key = _make_dup_key(rec)
        delta_str = rec.get("performance_delta", "+0.0%")

        candidate = {
            "ranked_at":               _now_jst(),
            "source_feedback_at":      rec.get("feedback_at", ""),
            "target_agent":            agent,
            "feedback_type":           ftype,
            "priority":                rec.get("priority", ""),
            "success_rate":            float(rec.get("success_rate", 0.0)),
            "performance_delta":       delta_str,
            "revenue_impact_score":    round(rv, 4),
            "seo_impact_score":        round(seo, 4),
            "cvr_impact_score":        round(cvr, 4),
            "freshness_urgency_score": round(fresh, 4),
            "reinject_priority_score": pri_score,
            "reinject_priority_label": label,
            "next_improvement_hint":   rec.get("next_improvement_hint", ""),
            "proposed_reinject_action": _proposed_action(rec),
            "status":                  "pending",
            "duplicate_key":           dup_key,
            "ranked_from":             "ceo_feedback_loop_queue",
            "ceo_judgment":            "ミュウツーCEO再投入優先順位",
        }

        if dup_key in existing_dup_keys:
            dup_count += 1
            _append_jsonl(REINJECT_HISTORY_PATH, {
                **candidate,
                "status": "rank_duplicate",
                "reason": f"同一 duplicate_key が既に pending/archived に存在: {dup_key}",
            })
            continue

        existing_dup_keys.add(dup_key)
        scored.append(candidate)
        ranked_count += 1

    # ソート: reinject_priority_score desc → revenue_impact_score desc → freshness desc → agent asc
    scored.sort(key=lambda r: (
        -r["reinject_priority_score"],
        -r["revenue_impact_score"],
        -r["freshness_urgency_score"],
        r["target_agent"],
    ))

    # reinject_order 付与
    for i, r in enumerate(scored, start=1):
        r["reinject_order"] = i

    # append to queue
    for r in scored:
        _append_jsonl(REINJECT_QUEUE_PATH, r)

    return {
        "ranked": ranked_count,
        "dup":    dup_count,
        "pending": sum(1 for r in _load_jsonl(REINJECT_QUEUE_PATH) if r.get("status") == "pending"),
    }


# ────────────────────────────────────────────
# 統計取得
# ────────────────────────────────────────────

def get_reinject_priority_stats() -> dict:
    recs = [r for r in _load_jsonl(REINJECT_QUEUE_PATH) if r.get("status") == "pending"]

    counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for r in recs:
        lbl = r.get("reinject_priority_label", "LOW")
        counts[lbl] = counts.get(lbl, 0) + 1

    # 1位 (reinject_order=1 or first)
    sorted_recs = sorted(recs, key=lambda r: r.get("reinject_order", 999))
    top1   = sorted_recs[0]  if sorted_recs else {}
    latest = recs[-1]        if recs        else {}

    return {
        "reinject_pending_count":  len(recs),
        "reinject_critical_count": counts["CRITICAL"],
        "reinject_high_count":     counts["HIGH"],
        "reinject_medium_count":   counts["MEDIUM"],
        "reinject_low_count":      counts["LOW"],
        "reinject_top1_agent":     top1.get("target_agent",            "—"),
        "reinject_top1_score":     top1.get("reinject_priority_score", 0.0),
        "reinject_top1_label":     top1.get("reinject_priority_label", "—"),
        "reinject_latest_agent":   latest.get("target_agent",            "—"),
        "reinject_latest_score":   latest.get("reinject_priority_score", 0.0),
        "reinject_latest_label":   latest.get("reinject_priority_label", "—"),
    }
