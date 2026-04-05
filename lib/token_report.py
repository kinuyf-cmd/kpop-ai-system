"""
トークン使用量レポート生成

Usage:
  python3 lib/token_report.py daily          # 本日分
  python3 lib/token_report.py weekly         # 直近7日
  python3 lib/token_report.py monthly        # 直近30日
  python3 lib/token_report.py daily 2026-04-05  # 指定日
"""
import json, sys, os
from datetime import datetime, timedelta
from collections import defaultdict
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
KPI_POSTS = BASE_DIR / "logs" / "kpi_posts.jsonl"
COST_PER_TOKEN = 0.000015  # USD


def load_posts(start_date, end_date):
    """kpi_posts.jsonl から期間内のレコードを読み込む"""
    posts = []
    if not KPI_POSTS.exists():
        return posts
    for line in KPI_POSTS.read_text().strip().split("\n"):
        if not line.strip():
            continue
        try:
            d = json.loads(line)
            ts = d.get("timestamp", d.get("date", ""))[:10]
            if start_date <= ts <= end_date:
                posts.append(d)
        except (json.JSONDecodeError, KeyError):
            continue
    return posts


def load_token_logs(start_date, end_date):
    """kpop_archives/*/token_usage.jsonl から詳細ログを読み込む"""
    archives_dir = Path.home() / "kpop_archives"
    entries = []
    if not archives_dir.exists():
        return entries
    for archive in archives_dir.iterdir():
        if not archive.is_dir():
            continue
        token_file = archive / "token_usage.jsonl"
        if not token_file.exists():
            continue
        # ディレクトリ名から日付を推定
        dir_name = archive.name
        for line in token_file.read_text().strip().split("\n"):
            if not line.strip():
                continue
            try:
                d = json.loads(line)
                d["run_id"] = dir_name
                entries.append(d)
            except json.JSONDecodeError:
                continue
    return entries


def generate_report(period, target_date=None):
    today = target_date or datetime.now().strftime("%Y-%m-%d")

    if period == "daily":
        start = end = today
    elif period == "weekly":
        start = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=6)).strftime("%Y-%m-%d")
        end = today
    elif period == "monthly":
        start = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=29)).strftime("%Y-%m-%d")
        end = today
    else:
        start = end = today

    posts = load_posts(start, end)

    # 集計
    total_tokens = sum(p.get("token_count", 0) for p in posts)
    total_cost = total_tokens * COST_PER_TOKEN
    post_count = len(posts)
    avg_tokens = total_tokens // max(post_count, 1)

    # パイプライン別
    by_pipeline = defaultdict(lambda: {"posts": 0, "tokens": 0})
    for p in posts:
        pipeline = p.get("pipeline", "unknown")
        by_pipeline[pipeline]["posts"] += 1
        by_pipeline[pipeline]["tokens"] += p.get("token_count", 0)

    # 記事タイプ別
    by_type = defaultdict(lambda: {"posts": 0, "tokens": 0})
    for p in posts:
        atype = p.get("article_type", "unknown")
        by_type[atype]["posts"] += 1
        by_type[atype]["tokens"] += p.get("token_count", 0)

    # 日別推移（weekly/monthly用）
    by_date = defaultdict(lambda: {"posts": 0, "tokens": 0, "cost_usd": 0})
    for p in posts:
        d = p.get("timestamp", p.get("date", ""))[:10]
        by_date[d]["posts"] += 1
        t = p.get("token_count", 0)
        by_date[d]["tokens"] += t
        by_date[d]["cost_usd"] += t * COST_PER_TOKEN

    report = {
        "period": period,
        "start_date": start,
        "end_date": end,
        "total_posts": post_count,
        "total_tokens": total_tokens,
        "total_cost_usd": round(total_cost, 4),
        "total_cost_jpy": round(total_cost * 150, 0),  # 概算レート
        "avg_tokens_per_post": avg_tokens,
        "by_pipeline": dict(by_pipeline),
        "by_article_type": dict(by_type),
    }

    if period in ("weekly", "monthly"):
        report["by_date"] = dict(sorted(by_date.items()))

    return report


def format_report(report):
    """人間が読みやすい形式"""
    lines = []
    lines.append(f"=== トークンレポート ({report['period']}) ===")
    lines.append(f"期間: {report['start_date']} 〜 {report['end_date']}")
    lines.append(f"投稿数: {report['total_posts']}")
    lines.append(f"総トークン: {report['total_tokens']:,}")
    lines.append(f"コスト: ${report['total_cost_usd']:.4f} (約{report['total_cost_jpy']:.0f}円)")
    lines.append(f"平均トークン/記事: {report['avg_tokens_per_post']:,}")
    lines.append("")

    if report.get("by_pipeline"):
        lines.append("【パイプライン別】")
        for k, v in report["by_pipeline"].items():
            lines.append(f"  {k}: {v['posts']}本 / {v['tokens']:,}トークン")
        lines.append("")

    if report.get("by_article_type"):
        lines.append("【記事タイプ別】")
        for k, v in report["by_article_type"].items():
            lines.append(f"  {k}: {v['posts']}本 / {v['tokens']:,}トークン")

    return "\n".join(lines)


if __name__ == "__main__":
    period = sys.argv[1] if len(sys.argv) > 1 else "daily"
    target = sys.argv[2] if len(sys.argv) > 2 else None

    if "--json" in sys.argv:
        print(json.dumps(generate_report(period, target), ensure_ascii=False, indent=2))
    else:
        print(format_report(generate_report(period, target)))
