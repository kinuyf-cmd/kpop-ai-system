#!/usr/bin/env python3
"""
Keyword Classifier - キーワード分類・難易度判定・競合ドメイン分析
SEO本部（ルカリオ/フーディン/ポリゴンZ）管轄
"""
import json
import os
import re
import sys
from datetime import date

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(BASE_DIR, "config")
LOGS_DIR = os.path.join(BASE_DIR, "logs")


def load_seo_config():
    with open(os.path.join(CONFIG_DIR, "seo_config.json"), encoding="utf-8") as f:
        return json.load(f)


def classify_keyword(keyword, gsc_data=None):
    """キーワードを4分類（branded/non_branded_head/long_tail/trending）に振り分け"""
    config = load_seo_config()
    kw_lower = keyword.lower().strip()
    word_count = len(kw_lower.split())

    # 指名検索
    branded_terms = ["kpop journal", "kpopjournal", "ケーポップジャーナル", "kポップジャーナル"]
    if any(term in kw_lower for term in branded_terms):
        return {
            "keyword": keyword,
            "class": "branded",
            "difficulty": "low",
            "action": "maintain_and_protect",
        }

    # トレンド判定（速報性キーワード）
    trending_signals = [
        "速報", "最新", "今日", "発表", "決定", "急遽", "緊急",
        "2026", "2025", str(date.today().year),
    ]
    is_trending = any(sig in kw_lower for sig in trending_signals)

    # ロングテール判定（3語以上 or 具体的クエリ）
    specificity_signals = [
        "チケット", "値段", "日程", "時間", "場所", "方法",
        "やり方", "比較", "おすすめ", "ランキング", "口コミ",
    ]
    is_specific = word_count >= 3 or any(sig in kw_lower for sig in specificity_signals)

    # GSCデータがあれば検索ボリュームで補正
    impressions = 0
    if gsc_data:
        for q in gsc_data.get("top_queries", []):
            if q.get("query", "").lower() == kw_lower:
                impressions = q.get("impressions", 0)
                break

    if is_trending:
        return {
            "keyword": keyword,
            "class": "trending",
            "difficulty": "medium",
            "action": "publish_immediately",
            "impressions": impressions,
        }
    elif is_specific:
        return {
            "keyword": keyword,
            "class": "long_tail",
            "difficulty": "low",
            "action": "target_for_ranking",
            "impressions": impressions,
        }
    elif impressions > 100 or word_count <= 2:
        return {
            "keyword": keyword,
            "class": "non_branded_head",
            "difficulty": "high",
            "action": "pillar_content_strategy",
            "impressions": impressions,
        }
    else:
        return {
            "keyword": keyword,
            "class": "long_tail",
            "difficulty": "low",
            "action": "target_for_ranking",
            "impressions": impressions,
        }


def get_difficulty_allocation():
    """難易度別の記事配分を取得"""
    config = load_seo_config()
    return config["difficulty_article_allocation"]


def analyze_competitors_from_gsc(gsc_data):
    """GSCデータから競合ドメインの出現状況を分析"""
    config = load_seo_config()
    competitor_domains = config["competitor_domains"]

    analysis = {domain: {"overlap_queries": 0, "avg_position_gap": 0, "queries": []} for domain in competitor_domains}

    queries = gsc_data.get("top_queries", [])
    pages = gsc_data.get("top_pages", [])

    our_positions = {}
    for q in queries:
        our_positions[q["query"]] = q.get("position", 100)

    report = {
        "date": date.today().isoformat(),
        "our_avg_position": sum(q.get("position", 0) for q in queries) / max(len(queries), 1),
        "total_queries_tracked": len(queries),
        "high_opportunity_keywords": [],
        "competitor_summary": [],
    }

    # 高機会キーワード: 表示回数多い × 順位10-30位（改善余地あり）
    for q in queries:
        pos = q.get("position", 100)
        imp = q.get("impressions", 0)
        ctr = q.get("ctr", 0)
        if 5 < pos <= 30 and imp > 10:
            expected_ctr = 0.3 / pos  # 簡易CTRモデル
            ctr_gap = expected_ctr - ctr
            report["high_opportunity_keywords"].append({
                "query": q["query"],
                "position": round(pos, 1),
                "impressions": imp,
                "current_ctr": round(ctr, 4),
                "potential_ctr_gain": round(max(ctr_gap, 0), 4),
                "action": "improve_content" if pos <= 15 else "create_new_article",
            })

    report["high_opportunity_keywords"].sort(key=lambda x: x["impressions"], reverse=True)
    report["high_opportunity_keywords"] = report["high_opportunity_keywords"][:20]

    return report


def suggest_article_plan(gsc_data, current_portfolio=None):
    """GSCデータと現在のポートフォリオからキーワード戦略を提案"""
    config = load_seo_config()
    allocation = config["difficulty_article_allocation"]

    plan = {
        "date": date.today().isoformat(),
        "suggestions": [],
    }

    queries = gsc_data.get("top_queries", [])

    # 順位改善候補
    for q in queries:
        pos = q.get("position", 100)
        imp = q.get("impressions", 0)
        classification = classify_keyword(q["query"], gsc_data)

        if pos <= 5 and imp > 50:
            plan["suggestions"].append({
                "keyword": q["query"],
                "type": "defend",
                "reason": f"Top {int(pos)} with {imp} imp - defend position",
                "class": classification["class"],
            })
        elif 5 < pos <= 20 and imp > 20:
            plan["suggestions"].append({
                "keyword": q["query"],
                "type": "improve",
                "reason": f"Position {int(pos)} with {imp} imp - improve to top 5",
                "class": classification["class"],
            })
        elif pos > 20 and imp > 50:
            plan["suggestions"].append({
                "keyword": q["query"],
                "type": "new_article",
                "reason": f"Position {int(pos)} but {imp} imp - high demand, create pillar",
                "class": classification["class"],
            })

    plan["suggestions"].sort(key=lambda x: {"defend": 0, "improve": 1, "new_article": 2}[x["type"]])
    return plan


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: keyword_classifier.py <keyword|analyze|plan>")
        sys.exit(1)

    action = sys.argv[1]

    if action == "analyze":
        metrics_file = os.path.expanduser("~/google_metrics/metrics_yesterday.json")
        if os.path.exists(metrics_file):
            with open(metrics_file, encoding="utf-8") as f:
                data = json.load(f)
            report = analyze_competitors_from_gsc(data.get("gsc", {}))
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print('{"error": "No metrics data found"}')
    elif action == "plan":
        metrics_file = os.path.expanduser("~/google_metrics/metrics_yesterday.json")
        if os.path.exists(metrics_file):
            with open(metrics_file, encoding="utf-8") as f:
                data = json.load(f)
            plan = suggest_article_plan(data.get("gsc", {}))
            print(json.dumps(plan, ensure_ascii=False, indent=2))
        else:
            print('{"error": "No metrics data found"}')
    else:
        result = classify_keyword(action)
        print(json.dumps(result, ensure_ascii=False, indent=2))
