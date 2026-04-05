"""
月次メトリクス集計

Usage:
  python3 lib/monthly_metrics_aggregator.py              # 前月
  python3 lib/monthly_metrics_aggregator.py 2026-03      # 指定月
  python3 lib/monthly_metrics_aggregator.py 2026-03 --json
"""
import json, sys, os
from datetime import datetime, timedelta
from collections import defaultdict
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
KPI_POSTS = BASE_DIR / "logs" / "kpi_posts.jsonl"
KPI_DAILY = BASE_DIR / "logs" / "kpi_daily.jsonl"
REVENUE_CONFIG = BASE_DIR / "config" / "revenue_config.json"
COST_PER_TOKEN = 0.000015


def get_month_range(month_str):
    """YYYY-MM から開始日・終了日を返す"""
    dt = datetime.strptime(month_str + "-01", "%Y-%m-%d")
    start = dt.strftime("%Y-%m-%d")
    if dt.month == 12:
        end_dt = dt.replace(year=dt.year + 1, month=1) - timedelta(days=1)
    else:
        end_dt = dt.replace(month=dt.month + 1) - timedelta(days=1)
    end = end_dt.strftime("%Y-%m-%d")
    return start, end


def load_posts(start, end):
    posts = []
    if not KPI_POSTS.exists():
        return posts
    for line in KPI_POSTS.read_text().strip().split("\n"):
        if not line.strip():
            continue
        try:
            d = json.loads(line)
            ts = d.get("timestamp", d.get("date", ""))[:10]
            if start <= ts <= end:
                posts.append(d)
        except (json.JSONDecodeError, KeyError):
            continue
    return posts


def load_daily_kpi(start, end):
    entries = []
    if not KPI_DAILY.exists():
        return entries
    for line in KPI_DAILY.read_text().strip().split("\n"):
        if not line.strip():
            continue
        try:
            d = json.loads(line)
            ts = d.get("date", "")[:10]
            if start <= ts <= end:
                entries.append(d)
        except (json.JSONDecodeError, KeyError):
            continue
    return entries


def load_revenue_targets():
    if not REVENUE_CONFIG.exists():
        return {}
    try:
        return json.loads(REVENUE_CONFIG.read_text())
    except json.JSONDecodeError:
        return {}


def aggregate(month_str):
    start, end = get_month_range(month_str)
    posts = load_posts(start, end)
    daily_kpi = load_daily_kpi(start, end)

    # 投稿集計
    total_posts = len(posts)
    total_tokens = sum(p.get("token_count", 0) for p in posts)
    total_cost_usd = total_tokens * COST_PER_TOKEN
    total_chars = sum(p.get("char_count", 0) for p in posts)

    # タイプ別
    by_type = defaultdict(lambda: {"posts": 0, "tokens": 0, "chars": 0})
    for p in posts:
        t = p.get("article_type", "unknown")
        by_type[t]["posts"] += 1
        by_type[t]["tokens"] += p.get("token_count", 0)
        by_type[t]["chars"] += p.get("char_count", 0)

    # カテゴリ別
    by_category = defaultdict(int)
    for p in posts:
        for cat in p.get("categories", []):
            by_category[str(cat)] += 1

    # パイプライン別
    by_pipeline = defaultdict(lambda: {"posts": 0, "tokens": 0})
    for p in posts:
        pl = p.get("pipeline", "unknown")
        by_pipeline[pl]["posts"] += 1
        by_pipeline[pl]["tokens"] += p.get("token_count", 0)

    # 日次KPIからPV・収益集計
    total_pv = sum(d.get("total_pv", 0) for d in daily_kpi)
    total_search = sum(d.get("search_traffic", 0) for d in daily_kpi)
    total_x_traffic = sum(d.get("x_traffic", 0) for d in daily_kpi)
    total_adsense = sum(d.get("revenue_adsense", 0) for d in daily_kpi)
    total_affiliate = sum(d.get("revenue_affiliate", 0) for d in daily_kpi)
    total_revenue = total_adsense + total_affiliate
    total_errors = sum(d.get("error_count", 0) for d in daily_kpi)
    success_rates = [d.get("success_rate", 0) for d in daily_kpi if d.get("success_rate")]
    avg_success_rate = sum(success_rates) / max(len(success_rates), 1)

    # 目標との比較
    rev_config = load_revenue_targets()
    targets = rev_config.get("daily_targets", {})

    report = {
        "month": month_str,
        "period": f"{start} ~ {end}",
        "posts": {
            "total": total_posts,
            "by_type": dict(by_type),
            "by_pipeline": dict(by_pipeline),
            "by_category_top10": dict(sorted(by_category.items(), key=lambda x: -x[1])[:10]),
            "total_chars": total_chars,
            "avg_chars": total_chars // max(total_posts, 1),
        },
        "tokens": {
            "total": total_tokens,
            "cost_usd": round(total_cost_usd, 4),
            "cost_jpy": round(total_cost_usd * 150, 0),
            "avg_per_post": total_tokens // max(total_posts, 1),
        },
        "traffic": {
            "total_pv": total_pv,
            "search_traffic": total_search,
            "x_traffic": total_x_traffic,
            "search_ratio": round(total_search / max(total_pv, 1) * 100, 1),
            "x_ratio": round(total_x_traffic / max(total_pv, 1) * 100, 1),
        },
        "revenue": {
            "total_jpy": total_revenue,
            "adsense_jpy": total_adsense,
            "affiliate_jpy": total_affiliate,
            "revenue_per_post": round(total_revenue / max(total_posts, 1), 1),
            "revenue_per_pv": round(total_revenue / max(total_pv, 1), 2),
        },
        "quality": {
            "avg_success_rate": round(avg_success_rate, 2),
            "total_errors": total_errors,
            "active_days": len(daily_kpi),
        },
        "cost_vs_revenue": {
            "token_cost_jpy": round(total_cost_usd * 150, 0),
            "revenue_jpy": total_revenue,
            "profit_jpy": round(total_revenue - total_cost_usd * 150, 0),
            "roi": round((total_revenue / max(total_cost_usd * 150, 1) - 1) * 100, 1),
        },
    }
    return report


def format_report(r):
    lines = []
    lines.append(f"{'='*50}")
    lines.append(f" 月次経営レポート: {r['month']}")
    lines.append(f" 期間: {r['period']}")
    lines.append(f"{'='*50}")
    lines.append("")

    p = r["posts"]
    lines.append(f"【投稿】 合計{p['total']}本 (平均{p['avg_chars']}文字/本)")
    for t, v in p["by_type"].items():
        lines.append(f"  {t}: {v['posts']}本")

    t = r["tokens"]
    lines.append(f"\n【トークンコスト】")
    lines.append(f"  合計: {t['total']:,}トークン")
    lines.append(f"  コスト: ${t['cost_usd']:.4f} (約{t['cost_jpy']:.0f}円)")
    lines.append(f"  平均: {t['avg_per_post']:,}/本")

    tr = r["traffic"]
    lines.append(f"\n【トラフィック】")
    lines.append(f"  総PV: {tr['total_pv']:,}")
    lines.append(f"  検索流入: {tr['search_traffic']:,} ({tr['search_ratio']}%)")
    lines.append(f"  X流入: {tr['x_traffic']:,} ({tr['x_ratio']}%)")

    rv = r["revenue"]
    lines.append(f"\n【収益】")
    lines.append(f"  月間売上: {rv['total_jpy']:,.0f}円")
    lines.append(f"    AdSense: {rv['adsense_jpy']:,.0f}円")
    lines.append(f"    アフィリエイト: {rv['affiliate_jpy']:,.0f}円")
    lines.append(f"  記事単価: {rv['revenue_per_post']:.1f}円/本")

    cv = r["cost_vs_revenue"]
    lines.append(f"\n【損益】")
    lines.append(f"  トークンコスト: {cv['token_cost_jpy']:.0f}円")
    lines.append(f"  売上: {cv['revenue_jpy']:,.0f}円")
    lines.append(f"  粗利: {cv['profit_jpy']:,.0f}円")
    lines.append(f"  ROI: {cv['roi']}%")

    q = r["quality"]
    lines.append(f"\n【品質】")
    lines.append(f"  平均成功率: {q['avg_success_rate']:.0%}")
    lines.append(f"  エラー数: {q['total_errors']}件")
    lines.append(f"  稼働日数: {q['active_days']}日")

    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] != "--json":
        month = sys.argv[1]
    else:
        # 前月をデフォルト
        now = datetime.now()
        if now.month == 1:
            month = f"{now.year - 1}-12"
        else:
            month = f"{now.year}-{now.month - 1:02d}"

    report = aggregate(month)
    if "--json" in sys.argv:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(format_report(report))
