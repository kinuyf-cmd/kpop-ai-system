"""
Exit指標ダッシュボード

Usage:
  python3 lib/exit_metrics.py                # 最新レポート
  python3 lib/exit_metrics.py --json         # JSON出力

バイアウト/法人化に向けた主要指標を週次で計測:
- MRR（月間経常収益）
- 成長率
- コンテンツ資産価値
- オーガニック流入比率
- 自動化率
- LTV
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
JPY_RATE = 150


def load_period_data(days):
    """直近N日のデータを読み込む"""
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    posts, daily = [], []

    if KPI_POSTS.exists():
        for line in KPI_POSTS.read_text().strip().split("\n"):
            if not line.strip():
                continue
            try:
                d = json.loads(line)
                ts = d.get("timestamp", d.get("date", ""))[:10]
                if ts >= cutoff:
                    posts.append(d)
            except (json.JSONDecodeError, KeyError):
                continue

    if KPI_DAILY.exists():
        for line in KPI_DAILY.read_text().strip().split("\n"):
            if not line.strip():
                continue
            try:
                d = json.loads(line)
                ts = d.get("date", "")[:10]
                if ts >= cutoff:
                    daily.append(d)
            except (json.JSONDecodeError, KeyError):
                continue

    return posts, daily


def load_targets():
    if REVENUE_CONFIG.exists():
        try:
            return json.loads(REVENUE_CONFIG.read_text())
        except Exception:
            pass
    return {}


def calculate_exit_metrics():
    """Exit指標を計算"""
    # 直近30日 vs 前30日
    posts_30, daily_30 = load_period_data(30)
    posts_60, daily_60 = load_period_data(60)
    targets = load_targets()

    # 前30日（30-60日前）
    cutoff_30 = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    posts_prev = [p for p in posts_60 if p.get("timestamp", p.get("date", ""))[:10] < cutoff_30]
    daily_prev = [d for d in daily_60 if d.get("date", "")[:10] < cutoff_30]

    # ── 1. MRR（月間経常収益）──
    revenue_30 = sum(d.get("revenue_adsense", 0) + d.get("revenue_affiliate", 0) for d in daily_30)
    revenue_prev = sum(d.get("revenue_adsense", 0) + d.get("revenue_affiliate", 0) for d in daily_prev)
    mrr = revenue_30
    mrr_growth = ((mrr / max(revenue_prev, 1)) - 1) * 100 if revenue_prev > 0 else 0

    # ── 2. PV成長率 ──
    pv_30 = sum(d.get("total_pv", 0) for d in daily_30)
    pv_prev = sum(d.get("total_pv", 0) for d in daily_prev)
    pv_growth = ((pv_30 / max(pv_prev, 1)) - 1) * 100 if pv_prev > 0 else 0

    # ── 3. コンテンツ資産 ──
    total_posts = len(posts_30)
    total_posts_all = len(posts_60)  # 累計に近い数字
    asset_posts = sum(1 for p in posts_30 if p.get("article_type") == "asset")
    content_velocity = total_posts  # 月間投稿数

    # ── 4. オーガニック流入比率 ──
    search_traffic = sum(d.get("search_traffic", 0) for d in daily_30)
    total_traffic = max(pv_30, 1)
    organic_ratio = round(search_traffic / total_traffic * 100, 1)

    # ── 5. トークンコスト・粗利 ──
    total_tokens = sum(p.get("token_count", 0) for p in posts_30)
    token_cost_jpy = total_tokens * COST_PER_TOKEN * JPY_RATE
    gross_profit = mrr - token_cost_jpy
    gross_margin = round(gross_profit / max(mrr, 1) * 100, 1) if mrr > 0 else 0

    # ── 6. 自動化率 ──
    # 全記事が自動パイプライン経由なら100%
    auto_posts = sum(1 for p in posts_30 if p.get("pipeline") in ["post_to_wp", "speed", "strategy", "chart"])
    automation_rate = round(auto_posts / max(total_posts, 1) * 100, 1)

    # ── 7. 記事あたり収益 ──
    revenue_per_post = round(mrr / max(total_posts, 1), 1)
    revenue_per_pv = round(mrr / max(pv_30, 1), 4)

    # ── 8. 目標達成率 ──
    daily_targets = targets.get("daily_targets", {})
    month_3_target = daily_targets.get("month_3", 6600) * 30  # 月間
    month_6_target = daily_targets.get("month_6", 16600) * 30
    month_12_target = daily_targets.get("month_12", 33000) * 30
    target_achievement = round(mrr / max(month_3_target, 1) * 100, 1)

    # ── 9. Exit Readiness Score (0-100) ──
    score = 0
    # MRR >= 100万 → 30点
    score += min(30, round(mrr / 1000000 * 30, 0))
    # 成長率 > 0 → 15点
    score += min(15, max(0, round(mrr_growth / 10 * 15, 0)))
    # オーガニック比率 >= 60% → 15点
    score += min(15, round(organic_ratio / 60 * 15, 0))
    # 粗利率 >= 70% → 15点
    score += min(15, round(gross_margin / 70 * 15, 0))
    # 自動化率 >= 80% → 15点
    score += min(15, round(automation_rate / 80 * 15, 0))
    # コンテンツ資産 >= 300本 → 10点
    score += min(10, round(total_posts_all / 300 * 10, 0))

    return {
        "generated_at": datetime.now().isoformat(),
        "period": "直近30日",
        "mrr": {
            "current_jpy": round(mrr),
            "previous_jpy": round(revenue_prev),
            "growth_pct": round(mrr_growth, 1),
            "target_month3_jpy": month_3_target,
            "target_achievement_pct": target_achievement,
        },
        "traffic": {
            "monthly_pv": pv_30,
            "pv_growth_pct": round(pv_growth, 1),
            "organic_ratio_pct": organic_ratio,
            "search_traffic": search_traffic,
        },
        "content": {
            "monthly_posts": total_posts,
            "asset_posts": asset_posts,
            "total_inventory": total_posts_all,
            "content_velocity": content_velocity,
        },
        "financials": {
            "revenue_jpy": round(mrr),
            "token_cost_jpy": round(token_cost_jpy),
            "gross_profit_jpy": round(gross_profit),
            "gross_margin_pct": gross_margin,
            "revenue_per_post_jpy": revenue_per_post,
            "revenue_per_pv_jpy": revenue_per_pv,
        },
        "operations": {
            "automation_rate_pct": automation_rate,
            "total_tokens": total_tokens,
            "avg_tokens_per_post": total_tokens // max(total_posts, 1),
        },
        "exit_readiness": {
            "score": int(min(score, 100)),
            "grade": "A" if score >= 80 else "B" if score >= 60 else "C" if score >= 40 else "D",
            "milestones": {
                "mrr_1m": mrr >= 1000000,
                "organic_60pct": organic_ratio >= 60,
                "margin_70pct": gross_margin >= 70,
                "automation_80pct": automation_rate >= 80,
                "inventory_300": total_posts_all >= 300,
            },
        },
    }


def format_dashboard(m):
    lines = []
    lines.append("=" * 55)
    lines.append(" EXIT READINESS DASHBOARD")
    lines.append(f" {m['period']} | {m['generated_at'][:10]}")
    lines.append("=" * 55)

    er = m["exit_readiness"]
    lines.append(f"\n  Exit Score: {er['score']}/100 (Grade: {er['grade']})")
    lines.append("")

    # マイルストーン
    lines.append("  Milestones:")
    for k, v in er["milestones"].items():
        icon = "done" if v else "...."
        labels = {
            "mrr_1m": "MRR 100万円",
            "organic_60pct": "検索流入 60%",
            "margin_70pct": "粗利率 70%",
            "automation_80pct": "自動化率 80%",
            "inventory_300": "記事資産 300本",
        }
        lines.append(f"    [{icon}] {labels.get(k, k)}")

    # MRR
    mrr = m["mrr"]
    lines.append(f"\n  MRR: {mrr['current_jpy']:,}円 (前月比: {mrr['growth_pct']:+.1f}%)")
    lines.append(f"  目標達成率: {mrr['target_achievement_pct']}% (3ヶ月目標: {mrr['target_month3_jpy']:,}円)")

    # トラフィック
    tr = m["traffic"]
    lines.append(f"\n  月間PV: {tr['monthly_pv']:,} (前月比: {tr['pv_growth_pct']:+.1f}%)")
    lines.append(f"  検索流入比率: {tr['organic_ratio_pct']}%")

    # 財務
    fin = m["financials"]
    lines.append(f"\n  売上: {fin['revenue_jpy']:,}円")
    lines.append(f"  コスト: {fin['token_cost_jpy']:,}円")
    lines.append(f"  粗利: {fin['gross_profit_jpy']:,}円 ({fin['gross_margin_pct']}%)")

    # 運用
    ops = m["operations"]
    lines.append(f"\n  自動化率: {ops['automation_rate_pct']}%")
    lines.append(f"  コンテンツ: {m['content']['monthly_posts']}本/月 (累計{m['content']['total_inventory']}本)")

    return "\n".join(lines)


if __name__ == "__main__":
    metrics = calculate_exit_metrics()
    if "--json" in sys.argv:
        print(json.dumps(metrics, ensure_ascii=False, indent=2))
    else:
        print(format_dashboard(metrics))
