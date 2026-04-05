"""
カテゴリ別パフォーマンス分析・不採算カテゴリ検出

Usage:
  python3 lib/category_analyzer.py analyze              # 全カテゴリ分析
  python3 lib/category_analyzer.py unprofitable         # 不採算カテゴリのみ
  python3 lib/category_analyzer.py optimize             # 最適化提案
  python3 lib/category_analyzer.py analyze --json       # JSON出力
"""
import json, sys, os
from datetime import datetime, timedelta
from collections import defaultdict
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
KPI_POSTS = BASE_DIR / "logs" / "kpi_posts.jsonl"
POST_LOG = BASE_DIR / "logs" / "post_log.json"
REVENUE_CONFIG = BASE_DIR / "config" / "revenue_config.json"
COST_PER_TOKEN = 0.000015
JPY_RATE = 150

# カテゴリID → 名前マッピング
CATEGORY_NAMES = {
    "2": "速報記事", "3": "カムバック情報", "4": "解説・考察",
    "5": "ライブ・イベント", "6": "新曲", "7": "出演情報",
    "8": "ドラマ", "9": "話題", "10": "コラボ",
    "11": "旅行", "12": "美容", "13": "新商品",
    "14": "ゴシップ・事件", "15": "広告", "17": "兵役",
    "20": "SBS人気歌謡", "31": "特集", "51": "スキンケア",
    "52": "ヘアケア", "53": "ダイエット", "54": "コスメ",
    "58": "今日話題のニュース", "61": "K-Pop Demon Hunters",
    "62": "カフェ・レストラン", "63": "ホテル", "64": "観光",
    "71": "K-POPチャート",
}


def load_posts(days=30):
    """直近N日の投稿データを読み込む"""
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    posts = []
    if not KPI_POSTS.exists():
        return posts
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
    return posts


def load_revenue_config():
    if not REVENUE_CONFIG.exists():
        return {}
    try:
        return json.loads(REVENUE_CONFIG.read_text())
    except json.JSONDecodeError:
        return {}


def analyze_categories(days=30):
    """カテゴリ別パフォーマンス分析"""
    posts = load_posts(days)
    rev_config = load_revenue_config()
    article_types = rev_config.get("article_types", {})

    # カテゴリ別集計
    cats = defaultdict(lambda: {
        "posts": 0, "tokens": 0, "chars": 0,
        "recent_posts": 0,  # 直近14日
        "older_posts": 0,   # 15-30日前
    })

    cutoff_14 = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d")

    for p in posts:
        ts = p.get("timestamp", p.get("date", ""))[:10]
        for cat_id in p.get("categories", []):
            cat = str(cat_id)
            cats[cat]["posts"] += 1
            cats[cat]["tokens"] += p.get("token_count", 0)
            cats[cat]["chars"] += p.get("char_count", 0)
            if ts >= cutoff_14:
                cats[cat]["recent_posts"] += 1
            else:
                cats[cat]["older_posts"] += 1

    # 分析結果構築
    results = []
    for cat_id, data in cats.items():
        token_cost_jpy = data["tokens"] * COST_PER_TOKEN * JPY_RATE

        # PV推定（記事タイプ別の期待収益から逆算は困難なので、投稿数ベースで推定）
        avg_type_config = article_types.get("flow", {})
        expected_rev_per_pv = avg_type_config.get("expected_revenue_per_pv", 1.5)

        # トレンド分析
        trend = "stable"
        if data["older_posts"] > 0:
            change = (data["recent_posts"] - data["older_posts"]) / data["older_posts"]
            if change > 0.3:
                trend = "growing"
            elif change < -0.3:
                trend = "declining"
        elif data["recent_posts"] > 0:
            trend = "new"
        elif data["older_posts"] > 0 and data["recent_posts"] == 0:
            trend = "abandoned"

        results.append({
            "category_id": cat_id,
            "category_name": CATEGORY_NAMES.get(cat_id, f"ID:{cat_id}"),
            "posts_total": data["posts"],
            "posts_recent_14d": data["recent_posts"],
            "posts_older_14d": data["older_posts"],
            "total_tokens": data["tokens"],
            "token_cost_jpy": round(token_cost_jpy, 1),
            "avg_chars": data["chars"] // max(data["posts"], 1),
            "trend": trend,
        })

    results.sort(key=lambda x: -x["posts_total"])
    return results


def identify_unprofitable(days=30):
    """不採算カテゴリを検出"""
    categories = analyze_categories(days)
    warnings = []

    for cat in categories:
        reasons = []

        # 高コスト低投稿（1本あたりのトークンコストが高い）
        if cat["posts_total"] > 0:
            cost_per_post = cat["token_cost_jpy"] / cat["posts_total"]
            if cost_per_post > 100:  # 1記事100円超
                reasons.append(f"記事単価高 ({cost_per_post:.0f}円/本)")

        # 衰退トレンド
        if cat["trend"] == "declining":
            reasons.append("投稿数-30%超（直近14日 vs 前14日）")

        # 放置カテゴリ（以前はアクティブだったが14日間投稿なし）
        if cat["trend"] == "abandoned":
            reasons.append("14日間投稿なし（以前はアクティブ）")

        if reasons:
            warnings.append({
                "category_id": cat["category_id"],
                "category_name": cat["category_name"],
                "reasons": reasons,
                "posts_total": cat["posts_total"],
                "token_cost_jpy": cat["token_cost_jpy"],
                "trend": cat["trend"],
            })

    return warnings


def generate_optimization_suggestions(days=30):
    """カテゴリ別最適化提案"""
    categories = analyze_categories(days)
    suggestions = []

    for cat in categories:
        if cat["posts_total"] < 2:
            continue

        actions = []

        # 高コスト
        if cat["posts_total"] > 0:
            cost_per_post = cat["token_cost_jpy"] / cat["posts_total"]
            if cost_per_post > 100:
                actions.append("投稿頻度を下げるか、短いパイプライン（速報型）に切り替え検討")

        # 衰退
        if cat["trend"] == "declining":
            actions.append("SEOリフレッシュ or トピック転換を検討")

        # 放置
        if cat["trend"] == "abandoned":
            actions.append("カテゴリ統合 or 再活性化を判断")

        # 成長中
        if cat["trend"] == "growing":
            actions.append("好調。投稿頻度維持 or 増加を検討")

        if actions:
            suggestions.append({
                "category_id": cat["category_id"],
                "category_name": cat["category_name"],
                "trend": cat["trend"],
                "posts_total": cat["posts_total"],
                "actions": actions,
            })

    return suggestions


def format_analysis(categories):
    lines = ["=== カテゴリ別パフォーマンス分析（直近30日）===", ""]
    lines.append(f"{'カテゴリ':<20} {'投稿':>5} {'直近14日':>8} {'トークンコスト':>12} {'トレンド':>8}")
    lines.append("-" * 60)
    for c in categories:
        lines.append(
            f"{c['category_name']:<20} {c['posts_total']:>5} "
            f"{c['posts_recent_14d']:>8} "
            f"{c['token_cost_jpy']:>10.0f}円 "
            f"{c['trend']:>8}"
        )
    return "\n".join(lines)


def format_warnings(warnings):
    if not warnings:
        return "不採算カテゴリなし"
    lines = ["=== 不採算カテゴリ警告 ===", ""]
    for w in warnings:
        lines.append(f"[{w['category_name']}] (ID:{w['category_id']})")
        for r in w["reasons"]:
            lines.append(f"  - {r}")
    return "\n".join(lines)


def format_suggestions(suggestions):
    if not suggestions:
        return "最適化提案なし"
    lines = ["=== カテゴリ最適化提案 ===", ""]
    for s in suggestions:
        icon = {"growing": "+", "declining": "-", "abandoned": "!", "stable": "=", "new": "*"}.get(s["trend"], "?")
        lines.append(f"[{icon}] {s['category_name']} ({s['posts_total']}本, {s['trend']})")
        for a in s["actions"]:
            lines.append(f"    -> {a}")
    return "\n".join(lines)


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "analyze"
    use_json = "--json" in sys.argv

    if command == "analyze":
        result = analyze_categories()
        if use_json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(format_analysis(result))

    elif command == "unprofitable":
        result = identify_unprofitable()
        if use_json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(format_warnings(result))

    elif command == "optimize":
        result = generate_optimization_suggestions()
        if use_json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(format_suggestions(result))
    else:
        print(f"Unknown command: {command}")
        print("Usage: python3 lib/category_analyzer.py [analyze|unprofitable|optimize] [--json]")
        sys.exit(1)
