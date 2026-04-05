#!/usr/bin/env python3
"""
KPI Logger - 日次/週次/月次KPIのJSON記録・集計
データ本部（ミュウツー）管轄

ログ形式: 1行1JSON (JSONL) で追記式
"""
import json
import os
import sys
from datetime import date, datetime, timedelta
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS_DIR = os.path.join(BASE_DIR, "logs")


def ensure_logs_dir():
    os.makedirs(LOGS_DIR, exist_ok=True)


def log_post(post_data):
    """投稿1件のKPIを記録"""
    ensure_logs_dir()
    entry = {
        "timestamp": datetime.now().isoformat(),
        "date": date.today().isoformat(),
        "event": "post_published",
        "post_id": post_data.get("post_id"),
        "title": post_data.get("title", ""),
        "url": post_data.get("url", ""),
        "slug": post_data.get("slug", ""),
        "article_type": post_data.get("article_type", "flow"),
        "categories": post_data.get("categories", []),
        "char_count": post_data.get("char_count", 0),
        "h2_count": post_data.get("h2_count", 0),
        "score": post_data.get("score", 0),
        "pipeline": post_data.get("pipeline", ""),
        "has_cta": post_data.get("has_cta", False),
        "has_thumbnail": post_data.get("has_thumbnail", False),
        "token_count": post_data.get("token_count", 0),
        "processing_time_sec": post_data.get("processing_time_sec", 0),
    }

    log_file = os.path.join(LOGS_DIR, "kpi_posts.jsonl")
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return entry


def log_error(error_data):
    """エラー1件を記録"""
    ensure_logs_dir()
    entry = {
        "timestamp": datetime.now().isoformat(),
        "date": date.today().isoformat(),
        "event": "error",
        "pipeline": error_data.get("pipeline", ""),
        "step": error_data.get("step", ""),
        "error_type": error_data.get("error_type", ""),
        "message": error_data.get("message", ""),
        "recoverable": error_data.get("recoverable", True),
    }

    log_file = os.path.join(LOGS_DIR, "kpi_errors.jsonl")
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return entry


def log_daily_summary(summary_data):
    """日次サマリーを記録"""
    ensure_logs_dir()
    entry = {
        "date": date.today().isoformat(),
        "event": "daily_summary",
        "posts_total": summary_data.get("posts_total", 0),
        "posts_success": summary_data.get("posts_success", 0),
        "posts_failed": summary_data.get("posts_failed", 0),
        "success_rate": summary_data.get("success_rate", 0),
        "total_pv": summary_data.get("total_pv", 0),
        "search_traffic": summary_data.get("search_traffic", 0),
        "x_traffic": summary_data.get("x_traffic", 0),
        "revenue_adsense": summary_data.get("revenue_adsense", 0),
        "revenue_affiliate": summary_data.get("revenue_affiliate", 0),
        "total_tokens": summary_data.get("total_tokens", 0),
        "avg_tokens_per_post": summary_data.get("avg_tokens_per_post", 0),
        "error_count": summary_data.get("error_count", 0),
        "article_types": summary_data.get("article_types", {}),
    }

    log_file = os.path.join(LOGS_DIR, "kpi_daily.jsonl")
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return entry


def generate_daily_report(target_date=None):
    """指定日のKPIレポートを生成"""
    if target_date is None:
        target_date = date.today().isoformat()

    posts_file = os.path.join(LOGS_DIR, "kpi_posts.jsonl")
    errors_file = os.path.join(LOGS_DIR, "kpi_errors.jsonl")

    posts = []
    if os.path.exists(posts_file):
        with open(posts_file, encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line.strip())
                    if entry.get("date") == target_date:
                        posts.append(entry)
                except (json.JSONDecodeError, KeyError):
                    continue

    errors = []
    if os.path.exists(errors_file):
        with open(errors_file, encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line.strip())
                    if entry.get("date") == target_date:
                        errors.append(entry)
                except (json.JSONDecodeError, KeyError):
                    continue

    total = len(posts)
    type_counts = defaultdict(int)
    total_chars = 0
    total_tokens = 0
    cta_count = 0

    for p in posts:
        type_counts[p.get("article_type", "unknown")] += 1
        total_chars += p.get("char_count", 0)
        total_tokens += p.get("token_count", 0)
        if p.get("has_cta"):
            cta_count += 1

    report = {
        "date": target_date,
        "posts": {
            "total": total,
            "by_type": dict(type_counts),
            "avg_char_count": round(total_chars / max(total, 1)),
            "cta_rate": round(cta_count / max(total, 1), 2),
        },
        "tokens": {
            "total": total_tokens,
            "avg_per_post": round(total_tokens / max(total, 1)),
        },
        "errors": {
            "total": len(errors),
            "by_type": dict(defaultdict(int, {e.get("error_type", "unknown"): 1 for e in errors})),
        },
        "success_rate": round(total / max(total + len(errors), 1), 4),
    }

    return report


def generate_weekly_report(weeks_ago=0):
    """週次KPIレポートを生成"""
    today = date.today()
    week_end = today - timedelta(days=today.weekday() + 7 * weeks_ago)
    week_start = week_end - timedelta(days=6)

    daily_reports = []
    current = week_start
    while current <= week_end:
        daily_reports.append(generate_daily_report(current.isoformat()))
        current += timedelta(days=1)

    total_posts = sum(r["posts"]["total"] for r in daily_reports)
    total_errors = sum(r["errors"]["total"] for r in daily_reports)
    total_tokens = sum(r["tokens"]["total"] for r in daily_reports)

    type_totals = defaultdict(int)
    for r in daily_reports:
        for t, c in r["posts"].get("by_type", {}).items():
            type_totals[t] += c

    return {
        "period": {"start": week_start.isoformat(), "end": week_end.isoformat()},
        "posts": {
            "total": total_posts,
            "daily_avg": round(total_posts / 7, 1),
            "by_type": dict(type_totals),
        },
        "tokens": {
            "total": total_tokens,
            "avg_per_post": round(total_tokens / max(total_posts, 1)),
        },
        "errors": {"total": total_errors},
        "success_rate": round(total_posts / max(total_posts + total_errors, 1), 4),
    }


def generate_monthly_report(target_month=None):
    """月次KPIレポートを生成"""
    if target_month is None:
        today = date.today()
        target_month = today.replace(day=1)

    month_start = target_month if isinstance(target_month, date) else date.fromisoformat(target_month + "-01")
    if month_start.month == 12:
        month_end = month_start.replace(year=month_start.year + 1, month=1, day=1) - timedelta(days=1)
    else:
        month_end = month_start.replace(month=month_start.month + 1, day=1) - timedelta(days=1)

    daily_reports = []
    current = month_start
    while current <= min(month_end, date.today()):
        daily_reports.append(generate_daily_report(current.isoformat()))
        current += timedelta(days=1)

    total_posts = sum(r["posts"]["total"] for r in daily_reports)
    total_tokens = sum(r["tokens"]["total"] for r in daily_reports)
    days_counted = len(daily_reports)

    type_totals = defaultdict(int)
    for r in daily_reports:
        for t, c in r["posts"].get("by_type", {}).items():
            type_totals[t] += c

    return {
        "period": {"start": month_start.isoformat(), "end": month_end.isoformat()},
        "days_counted": days_counted,
        "posts": {
            "total": total_posts,
            "daily_avg": round(total_posts / max(days_counted, 1), 1),
            "by_type": dict(type_totals),
            "revenue_ratio": round(type_totals.get("revenue", 0) / max(total_posts, 1), 4),
        },
        "tokens": {
            "total": total_tokens,
            "avg_per_post": round(total_tokens / max(total_posts, 1)),
            "estimated_cost_usd": round(total_tokens * 0.000015, 2),
        },
    }


# ── CLI ──

if __name__ == "__main__":
    ensure_logs_dir()

    if len(sys.argv) < 2:
        print("Usage: kpi_logger.py <log_post|log_error|daily|weekly|monthly> [args...]")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "log_post":
        data = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
        result = log_post(data)
        print(json.dumps(result, ensure_ascii=False))

    elif cmd == "log_error":
        data = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
        result = log_error(data)
        print(json.dumps(result, ensure_ascii=False))

    elif cmd == "daily":
        target = sys.argv[2] if len(sys.argv) > 2 else None
        report = generate_daily_report(target)
        print(json.dumps(report, ensure_ascii=False, indent=2))

    elif cmd == "weekly":
        weeks = int(sys.argv[2]) if len(sys.argv) > 2 else 0
        report = generate_weekly_report(weeks)
        print(json.dumps(report, ensure_ascii=False, indent=2))

    elif cmd == "monthly":
        report = generate_monthly_report()
        print(json.dumps(report, ensure_ascii=False, indent=2))

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
