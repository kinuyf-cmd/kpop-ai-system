#!/usr/bin/env python3
"""
LTV Calculator - ユーザー/記事/カテゴリ単位のLTV算出
データ本部（ミュウツー）管轄
"""
import json
import os
import sys
from datetime import date

CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config")
LOGS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")


def load_config():
    with open(os.path.join(CONFIG_DIR, "revenue_config.json"), encoding="utf-8") as f:
        return json.load(f)


def calculate_user_ltv(config=None):
    """ユーザーLTV = (平均セッション価値 × 平均セッション数) / (1 + 割引率 - リテンション率)"""
    if config is None:
        config = load_config()
    ltv = config["ltv_config"]

    avg_session_value = ltv["avg_session_value_adsense"]
    return_rate = ltv["avg_return_rate"]
    avg_sessions = ltv["avg_sessions_per_returning_user"]
    churn = ltv["churn_rate_monthly"]
    discount = ltv["discount_rate_monthly"]

    # 新規ユーザー分（1セッション）
    new_user_value = avg_session_value

    # リピーター分（幾何級数）
    retention = 1 - churn
    if discount + churn > 0:
        returning_user_value = (avg_session_value * avg_sessions * retention) / (discount + churn)
    else:
        returning_user_value = avg_session_value * avg_sessions * 12

    # 加重平均
    ltv_value = (1 - return_rate) * new_user_value + return_rate * returning_user_value
    return round(ltv_value, 2)


def calculate_article_ltv(article_data):
    """記事LTV = 累積PV × 記事タイプ別期待収益/PV"""
    config = load_config()
    article_type = article_data.get("type", "flow")
    cv_design = config["article_type_cv_design"].get(article_type, {})

    total_pv = article_data.get("total_pv", 0)
    expected_rev_per_pv = cv_design.get("expected_revenue_per_pv", 1.5)
    age_days = article_data.get("age_days", 1)

    # 実績収益があればそれを使う
    actual_revenue = article_data.get("actual_revenue", 0)
    if actual_revenue > 0:
        actual_rev_per_pv = actual_revenue / max(total_pv, 1)
        # 実績と期待値の加重平均（実績を重視）
        blended_rev_per_pv = actual_rev_per_pv * 0.7 + expected_rev_per_pv * 0.3
    else:
        blended_rev_per_pv = expected_rev_per_pv

    current_value = total_pv * blended_rev_per_pv

    # 将来価値推定（記事タイプ別の減衰率）
    decay_rates = {"flow": 0.15, "asset": 0.02, "revenue": 0.05}
    decay = decay_rates.get(article_type, 0.1)

    # 12ヶ月先の累積推定
    daily_pv = total_pv / max(age_days, 1)
    future_value = 0
    for month in range(1, 13):
        monthly_pv = daily_pv * 30 * ((1 - decay) ** month)
        future_value += monthly_pv * blended_rev_per_pv

    return {
        "current_value": round(current_value, 2),
        "projected_12m_value": round(future_value, 2),
        "total_ltv": round(current_value + future_value, 2),
        "rev_per_pv": round(blended_rev_per_pv, 4),
        "daily_pv_avg": round(daily_pv, 1),
        "article_type": article_type,
    }


def calculate_category_ltv(category_data):
    """カテゴリLTV = 配下記事LTVの合計"""
    total_ltv = 0
    article_count = len(category_data.get("articles", []))

    for article in category_data.get("articles", []):
        a_ltv = calculate_article_ltv(article)
        total_ltv += a_ltv["total_ltv"]

    cost = category_data.get("total_token_cost", 0)
    roi = (total_ltv - cost) / max(cost, 1)

    return {
        "category_id": category_data.get("category_id"),
        "category_name": category_data.get("category_name", ""),
        "article_count": article_count,
        "total_ltv": round(total_ltv, 2),
        "avg_article_ltv": round(total_ltv / max(article_count, 1), 2),
        "total_cost": round(cost, 2),
        "roi": round(roi, 4),
        "profitable": roi > 0,
    }


def generate_ltv_report():
    """KPIログからLTVレポートを生成"""
    config = load_config()
    user_ltv = calculate_user_ltv(config)

    kpi_file = os.path.join(LOGS_DIR, "kpi_daily.json")
    articles = []
    if os.path.exists(kpi_file):
        with open(kpi_file, encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line.strip())
                    if "post_id" in entry:
                        articles.append(entry)
                except (json.JSONDecodeError, KeyError):
                    continue

    report = {
        "date": date.today().isoformat(),
        "user_ltv": user_ltv,
        "revenue_targets": config["daily_revenue_targets"],
        "article_count": len(articles),
    }

    return report


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "report":
        report = generate_ltv_report()
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        config = load_config()
        ltv = calculate_user_ltv(config)
        print(f"User LTV: ¥{ltv}")

        sample = {"type": "revenue", "total_pv": 5000, "age_days": 30, "actual_revenue": 15000}
        result = calculate_article_ltv(sample)
        print(json.dumps(result, ensure_ascii=False, indent=2))
