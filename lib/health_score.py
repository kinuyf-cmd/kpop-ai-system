#!/usr/bin/env python3
"""health_score.py - Company health score calculation engine.

Calculates a weighted overall health score (/100) from 5 department scores:
  - コンテンツ部 (0.30)
  - 品質部       (0.20)
  - SEO部        (0.20)
  - 収益部       (0.15)
  - 運用部       (0.15)

Data sources:
  - agent_metrics.json
  - google_metrics/metrics_yesterday.json
  - logs/pipeline.jsonl  (last 24h)
  - config/error_patterns.json
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

BASE = Path(__file__).resolve().parent.parent  # kpop-ai-system root
JST = timezone(timedelta(hours=9))

# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

def _load_json(rel_path):
    p = BASE / rel_path
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_jsonl(rel_path):
    p = BASE / rel_path
    if not p.exists():
        return []
    records = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                records.append(json.loads(line))
            except Exception:
                pass
    return records


def _recent_pipeline_records(hours=24):
    """Return pipeline.jsonl records from the last *hours*."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    records = _load_jsonl("logs/pipeline.jsonl")
    recent = []
    for r in records:
        ts = r.get("timestamp", "")
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if dt >= cutoff:
                recent.append(r)
        except Exception:
            pass
    return recent


# ---------------------------------------------------------------------------
# Score thresholds & badge
# ---------------------------------------------------------------------------

_THRESHOLDS = [
    (90, "\U0001f7e2", "健全", "#22c55e"),      # green circle
    (70, "\U0001f7e1", "注意", "#eab308"),      # yellow circle
    (50, "\U0001f7e0", "要改善", "#f97316"),    # orange circle
    (0,  "\U0001f534", "危険", "#ef4444"),      # red circle
]


def _threshold(score):
    for min_val, emoji, label, color in _THRESHOLDS:
        if score >= min_val:
            return emoji, label, color
    return "\U0001f534", "危険", "#ef4444"


def get_score_badge(score):
    """Return a small HTML badge string for *score* (/100)."""
    score = max(0, min(100, round(score)))
    emoji, label, color = _threshold(score)
    return (
        f'<span style="display:inline-block;background:{color}22;color:{color};'
        f'border:1px solid {color};padding:1px 8px;border-radius:6px;'
        f'font-size:0.75rem;font-weight:700;margin-left:8px;vertical-align:middle;">'
        f'{emoji} {score}/100 {label}</span>'
    )


# ---------------------------------------------------------------------------
# Utility: clamp score 0-100
# ---------------------------------------------------------------------------

def _clamp(v):
    return max(0.0, min(100.0, float(v)))


# ---------------------------------------------------------------------------
# Department score calculators
# ---------------------------------------------------------------------------

def _score_content():
    """コンテンツ部: 記事公開数 vs target, 本文品質平均, 空出力率(inverse)."""
    metrics = _load_json("agent_metrics.json")
    agents = metrics.get("agents", {})
    summary = metrics.get("summary", {})

    # 記事公開数 — use pipeline.jsonl last 24h for "approved" or "published"
    recent = _recent_pipeline_records(24)
    published = sum(1 for r in recent if r.get("status") in ("approved", "published", "ok"))
    target_daily = 5  # target articles per day
    pub_score = _clamp(published / target_daily * 100)

    # 本文品質平均 — average success_rate of content-producing agents
    content_agents = ["deoxys", "metamon", "eevee", "jirachi", "kairyu"]
    rates = [agents[a]["success_rate"] for a in content_agents if a in agents and "success_rate" in agents[a]]
    quality_score = _clamp((sum(rates) / len(rates) * 100) if rates else 50)

    # 空出力率(inverse)
    total_empty = sum(agents[a].get("empty_output_count", 0) for a in agents)
    total_runs = sum(agents[a].get("total_count", 1) for a in agents)
    empty_rate = total_empty / max(total_runs, 1)
    empty_inv_score = _clamp((1 - empty_rate) * 100)

    # Weighted combination
    score = pub_score * 0.40 + quality_score * 0.35 + empty_inv_score * 0.25

    return {
        "score": round(score, 1),
        "components": {
            "記事公開数": {"value": published, "target": target_daily, "score": round(pub_score, 1)},
            "品質平均": {"value": round(sum(rates)/len(rates), 3) if rates else 0, "score": round(quality_score, 1)},
            "空出力率": {"value": round(empty_rate, 4), "score": round(empty_inv_score, 1)},
        },
        "status": _threshold(score)[1],
    }


def _score_quality():
    """品質部: pre_publish_hook PASS率, HARD_FAIL件数(inverse), サーナイト成功率."""
    metrics = _load_json("agent_metrics.json")
    agents = metrics.get("agents", {})

    # pre_publish_hook pass rate — use gardevoir's success_rate as proxy
    gardevoir = agents.get("gardevoir", agents.get("gardevoir_hook_critic", {}))
    gardevoir_rate = gardevoir.get("success_rate", 0.8)
    pass_score = _clamp(gardevoir_rate * 100)

    # HARD_FAIL件数(inverse) — aggregate hard_fail_count
    hard_fails = sum(agents[a].get("hard_fail_count", 0) for a in agents)
    # 0 hard fails = 100, 10+ = 0
    hf_score = _clamp(max(0, 100 - hard_fails * 10))

    # サーナイト(gardevoir) success rate directly
    gardevoir_score = _clamp(gardevoir_rate * 100)

    score = pass_score * 0.40 + hf_score * 0.30 + gardevoir_score * 0.30

    return {
        "score": round(score, 1),
        "components": {
            "PASS率": {"value": round(gardevoir_rate, 3), "score": round(pass_score, 1)},
            "HARD_FAIL件数": {"value": hard_fails, "score": round(hf_score, 1)},
            "サーナイト成功率": {"value": round(gardevoir_rate, 3), "score": round(gardevoir_score, 1)},
        },
        "status": _threshold(score)[1],
    }


def _score_seo():
    """SEO部: GSCクリック変化率, インデックス率, 平均順位改善."""
    gsc_data = _load_json("google_metrics/metrics_yesterday.json")
    gsc = gsc_data.get("gsc", {})
    top_pages = gsc.get("top_pages", [])

    total_clicks = sum(p.get("clicks", 0) for p in top_pages)
    total_impressions = sum(p.get("impressions", 0) for p in top_pages)

    # Click score — baseline 20 clicks/day = 100
    click_score = _clamp(total_clicks / 20 * 100)

    # Index rate — pages with impressions > 0 out of top_pages
    indexed = sum(1 for p in top_pages if p.get("impressions", 0) > 0)
    index_rate = indexed / max(len(top_pages), 1)
    index_score = _clamp(index_rate * 100)

    # Average position — lower is better, target < 10
    if top_pages:
        avg_pos = sum(p.get("position", 50) * p.get("impressions", 1) for p in top_pages) / max(total_impressions, 1)
    else:
        avg_pos = 50
    # Position 1 = 100, position 50+ = 0
    pos_score = _clamp(max(0, (50 - avg_pos) / 50 * 100))

    score = click_score * 0.40 + index_score * 0.30 + pos_score * 0.30

    return {
        "score": round(score, 1),
        "components": {
            "GSCクリック数": {"value": total_clicks, "score": round(click_score, 1)},
            "インデックス率": {"value": round(index_rate, 3), "score": round(index_score, 1)},
            "平均順位": {"value": round(avg_pos, 1), "score": round(pos_score, 1)},
        },
        "status": _threshold(score)[1],
    }


def _score_revenue():
    """収益部: AdSense収益, CPM/RPM, CTA率."""
    gsc_data = _load_json("google_metrics/metrics_yesterday.json")
    adsense = gsc_data.get("adsense", {})

    earnings = float(adsense.get("ESTIMATED_EARNINGS", 0))
    rpm = float(adsense.get("PAGE_VIEWS_RPM", 0))
    page_views = float(adsense.get("PAGE_VIEWS", 0))
    impressions = float(adsense.get("IMPRESSIONS", 0))

    # Earnings score — target 200 yen/day = 100
    earn_score = _clamp(earnings / 200 * 100)

    # RPM score — target 300 = 100
    rpm_score = _clamp(rpm / 300 * 100)

    # CTA rate — from cta_events
    cta = gsc_data.get("cta_events", {})
    cta_ctr = cta.get("cta_ctr_real", 0)
    # target 3% = 100
    cta_score = _clamp(cta_ctr / 3.0 * 100)

    score = earn_score * 0.40 + rpm_score * 0.35 + cta_score * 0.25

    return {
        "score": round(score, 1),
        "components": {
            "AdSense収益": {"value": earnings, "target": 200, "score": round(earn_score, 1)},
            "RPM": {"value": rpm, "target": 300, "score": round(rpm_score, 1)},
            "CTA率": {"value": round(cta_ctr, 2), "score": round(cta_score, 1)},
        },
        "status": _threshold(score)[1],
    }


def _score_operations():
    """運用部: cron成功率, pipeline完走率, エラー件数(inverse)."""
    recent = _recent_pipeline_records(24)
    error_patterns = _load_json("config/error_patterns.json")
    patterns = error_patterns.get("patterns", {})

    # Pipeline completion rate
    total_runs = len(recent)
    ok_runs = sum(1 for r in recent if r.get("status") in ("ok", "approved", "published"))
    pipeline_rate = ok_runs / max(total_runs, 1)
    pipeline_score = _clamp(pipeline_rate * 100)

    # Cron success rate — approximate from pipeline runs (no separate cron log)
    # Use same pipeline metric as proxy
    cron_score = pipeline_score

    # Error count (inverse) — count unresolved errors
    unresolved = sum(
        1 for p in patterns.values()
        if isinstance(p, dict) and not p.get("resolved_at") and p.get("count", 0) > 0
    )
    # Also count recent errors from error_patterns
    recent_errors = sum(
        p.get("count", 0) for p in patterns.values()
        if isinstance(p, dict) and not p.get("resolved_at")
    )
    # 0 errors = 100, 20+ = 0
    error_inv_score = _clamp(max(0, 100 - recent_errors * 5))

    score = cron_score * 0.35 + pipeline_score * 0.35 + error_inv_score * 0.30

    return {
        "score": round(score, 1),
        "components": {
            "cron成功率": {"value": round(pipeline_rate, 3), "score": round(cron_score, 1)},
            "pipeline完走率": {"value": round(pipeline_rate, 3), "score": round(pipeline_score, 1)},
            "未解決エラー数": {"value": unresolved, "score": round(error_inv_score, 1)},
        },
        "status": _threshold(score)[1],
    }


# ---------------------------------------------------------------------------
# Department registry
# ---------------------------------------------------------------------------

_DEPARTMENTS = {
    "コンテンツ部": {"weight": 0.30, "fn": _score_content},
    "品質部":       {"weight": 0.20, "fn": _score_quality},
    "SEO部":        {"weight": 0.20, "fn": _score_seo},
    "収益部":       {"weight": 0.15, "fn": _score_revenue},
    "運用部":       {"weight": 0.15, "fn": _score_operations},
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def calculate_department_score(dept_name):
    """Calculate score for a single department.

    Returns dict: {"score": float, "components": {...}, "status": str}
    """
    dept = _DEPARTMENTS.get(dept_name)
    if not dept:
        return {"score": 0, "components": {}, "status": "不明"}
    try:
        return dept["fn"]()
    except Exception as e:
        return {"score": 0, "components": {"error": str(e)}, "status": "エラー"}


def calculate_overall_health():
    """Calculate the overall company health score.

    Returns dict with overall score, departments breakdown, and timestamp.
    """
    departments = {}
    weighted_sum = 0.0

    for name, info in _DEPARTMENTS.items():
        result = calculate_department_score(name)
        departments[name] = {
            "weight": info["weight"],
            **result,
        }
        weighted_sum += result["score"] * info["weight"]

    overall = round(weighted_sum, 1)
    emoji, label, color = _threshold(overall)

    return {
        "overall": overall,
        "overall_status": f"{emoji} {label}",
        "departments": departments,
        "timestamp": datetime.now(JST).isoformat(),
    }


# ---------------------------------------------------------------------------
# Per-section score helpers (for dashboard badges)
# ---------------------------------------------------------------------------

def score_for_section(section_id):
    """Return a score (0-100) for a specific dashboard section.

    section_id: e.g. "sec_01", "sec_09"
    """
    try:
        if section_id == "sec_01":
            # Emergency: inverse of critical error count
            ep = _load_json("config/error_patterns.json")
            patterns = ep.get("patterns", {})
            critical = sum(
                1 for p in patterns.values()
                if isinstance(p, dict) and not p.get("resolved_at")
                and p.get("count", 0) >= 5
            )
            return _clamp(max(0, 100 - critical * 20))

        elif section_id == "sec_02":
            # Important: inverse of 24h warning count
            ep = _load_json("config/error_patterns.json")
            patterns = ep.get("patterns", {})
            warnings = sum(
                1 for p in patterns.values()
                if isinstance(p, dict) and not p.get("resolved_at")
                and 0 < p.get("count", 0) < 5
            )
            return _clamp(max(0, 100 - warnings * 10))

        elif section_id == "sec_03":
            # Daily KPI achievement
            recent = _recent_pipeline_records(24)
            published = sum(1 for r in recent if r.get("status") in ("approved", "published", "ok"))
            return _clamp(published / 5 * 100)

        elif section_id == "sec_04":
            # Weekly trend
            recent = _recent_pipeline_records(168)  # 7 days
            published = sum(1 for r in recent if r.get("status") in ("approved", "published", "ok"))
            return _clamp(published / 35 * 100)  # 5/day * 7

        elif section_id == "sec_05":
            # Monthly target progress
            gsc_data = _load_json("google_metrics/metrics_yesterday.json")
            adsense = gsc_data.get("adsense", {})
            earnings = float(adsense.get("ESTIMATED_EARNINGS", 0))
            daily_target = 200
            return _clamp(earnings / daily_target * 100)

        elif section_id == "sec_06":
            # Average agent success rate
            metrics = _load_json("agent_metrics.json")
            summary = metrics.get("summary", {})
            overall_rate = summary.get("overall_success_rate", 0)
            return _clamp(overall_rate * 100)

        elif section_id == "sec_07":
            # Meeting completion rate
            meetings_dir = BASE / "data" / "meetings" / "general"
            if meetings_dir.exists():
                today = datetime.now(JST).strftime("%Y-%m-%d")
                standup = meetings_dir / f"standup_{today}.md"
                return 100.0 if standup.exists() else 50.0
            return 50.0

        elif section_id == "sec_08":
            # Inverse error severity
            ep = _load_json("config/error_patterns.json")
            patterns = ep.get("patterns", {})
            unresolved = sum(
                p.get("count", 0) for p in patterns.values()
                if isinstance(p, dict) and not p.get("resolved_at")
            )
            return _clamp(max(0, 100 - unresolved * 5))

        elif section_id == "sec_09":
            # SEO department score
            return _score_seo()["score"]

        elif section_id == "sec_10":
            # Revenue department score
            return _score_revenue()["score"]

        else:
            return 50.0

    except Exception:
        return 50.0


# ---------------------------------------------------------------------------
# Main: calculate and append to data/health_scores.jsonl
# ---------------------------------------------------------------------------

def main():
    result = calculate_overall_health()
    today = datetime.now(JST).strftime("%Y-%m-%d")

    record = {
        "date": today,
        "overall": result["overall"],
        "departments": {
            name: {
                "score": dept["score"],
                "status": dept["status"],
            }
            for name, dept in result["departments"].items()
        },
        "timestamp": result["timestamp"],
    }

    # Append to data/health_scores.jsonl
    outfile = BASE / "data" / "health_scores.jsonl"
    outfile.parent.mkdir(parents=True, exist_ok=True)
    with open(outfile, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # Print summary
    emoji, label, _ = _threshold(result["overall"])
    print(f"[health_score] {today} overall={result['overall']}/100 {emoji} {label}")
    for name, dept in result["departments"].items():
        d_emoji, d_label, _ = _threshold(dept["score"])
        print(f"  {name}: {dept['score']}/100 {d_emoji} {d_label}")
    print(f"  -> {outfile}")

    return result


if __name__ == "__main__":
    main()
