#!/usr/bin/env python3
"""
Data Collector - GSC/GA4/AdSense統合データ取得 + 記事別KPI
データ本部（ミュウツー）管轄

既存の fetch_yesterday_metrics.py を拡張し、記事別PV/CTR/順位/収益を取得
"""
import json
import os
import sys
from datetime import date, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS_DIR = os.path.join(BASE_DIR, "logs")
METRICS_DIR = os.path.expanduser("~/google_metrics")

SERVICE_ACCOUNT_FILE = os.path.join(METRICS_DIR, "service_account.json")
GA4_PROPERTY_ID = os.environ.get("GA4_PROPERTY_ID", "493983919")
GSC_SITE_URL = os.environ.get("GSC_SITE_URL", "https://www.kpopjournal.tokyo/")


def get_gsc_article_metrics(days=7, row_limit=100):
    """GSC APIから記事別のクリック/表示/CTR/順位を取得"""
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError:
        return {"error": "google-api-python-client not installed"}

    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=["https://www.googleapis.com/auth/webmasters.readonly"]
    )
    service = build("searchconsole", "v1", credentials=creds)

    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=days - 1)

    # ページ別メトリクス
    page_body = {
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "dimensions": ["page"],
        "rowLimit": row_limit,
    }
    page_res = service.searchanalytics().query(siteUrl=GSC_SITE_URL, body=page_body).execute()

    articles = []
    for row in page_res.get("rows", []):
        articles.append({
            "url": row["keys"][0],
            "clicks": row.get("clicks", 0),
            "impressions": row.get("impressions", 0),
            "ctr": round(row.get("ctr", 0), 4),
            "position": round(row.get("position", 0), 1),
        })

    # クエリ別メトリクス（キーワード分析用）
    query_body = {
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "dimensions": ["query"],
        "rowLimit": row_limit,
    }
    query_res = service.searchanalytics().query(siteUrl=GSC_SITE_URL, body=query_body).execute()

    queries = []
    for row in query_res.get("rows", []):
        queries.append({
            "query": row["keys"][0],
            "clicks": row.get("clicks", 0),
            "impressions": row.get("impressions", 0),
            "ctr": round(row.get("ctr", 0), 4),
            "position": round(row.get("position", 0), 1),
        })

    # ページ×クエリ（上位記事の流入キーワード）
    page_query_body = {
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "dimensions": ["page", "query"],
        "rowLimit": 200,
    }
    pq_res = service.searchanalytics().query(siteUrl=GSC_SITE_URL, body=page_query_body).execute()

    article_keywords = {}
    for row in pq_res.get("rows", []):
        page = row["keys"][0]
        query = row["keys"][1]
        if page not in article_keywords:
            article_keywords[page] = []
        article_keywords[page].append({
            "query": query,
            "clicks": row.get("clicks", 0),
            "impressions": row.get("impressions", 0),
            "position": round(row.get("position", 0), 1),
        })

    return {
        "period": {"start": start.isoformat(), "end": end.isoformat(), "days": days},
        "articles": articles,
        "queries": queries,
        "article_keywords": {k: v[:10] for k, v in article_keywords.items()},
        "summary": {
            "total_clicks": sum(a["clicks"] for a in articles),
            "total_impressions": sum(a["impressions"] for a in articles),
            "avg_ctr": round(sum(a["ctr"] for a in articles) / max(len(articles), 1), 4),
            "avg_position": round(sum(a["position"] for a in articles) / max(len(articles), 1), 1),
            "articles_tracked": len(articles),
        }
    }


def get_ga4_article_metrics(days=7):
    """GA4 APIから記事別のPV/セッション/滞在時間を取得"""
    try:
        from google.oauth2 import service_account
        from google.analytics.data_v1beta import BetaAnalyticsDataClient
        from google.analytics.data_v1beta.types import DateRange, Dimension, Metric, RunReportRequest
    except ImportError:
        return {"error": "google-analytics-data not installed"}

    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=["https://www.googleapis.com/auth/analytics.readonly"]
    )
    client = BetaAnalyticsDataClient(credentials=creds)

    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=days - 1)

    req = RunReportRequest(
        property=f"properties/{GA4_PROPERTY_ID}",
        dimensions=[Dimension(name="pagePath")],
        metrics=[
            Metric(name="screenPageViews"),
            Metric(name="sessions"),
            Metric(name="totalUsers"),
            Metric(name="engagedSessions"),
            Metric(name="averageSessionDuration"),
            Metric(name="bounceRate"),
        ],
        date_ranges=[DateRange(start_date=start.isoformat(), end_date=end.isoformat())],
        limit=100,
    )

    res = client.run_report(req)

    articles = []
    for row in res.rows:
        articles.append({
            "path": row.dimension_values[0].value,
            "pageviews": int(row.metric_values[0].value),
            "sessions": int(row.metric_values[1].value),
            "users": int(row.metric_values[2].value),
            "engaged_sessions": int(row.metric_values[3].value),
            "avg_duration": float(row.metric_values[4].value),
            "bounce_rate": float(row.metric_values[5].value),
        })

    # サマリー
    summary_req = RunReportRequest(
        property=f"properties/{GA4_PROPERTY_ID}",
        metrics=[
            Metric(name="screenPageViews"),
            Metric(name="sessions"),
            Metric(name="totalUsers"),
        ],
        date_ranges=[DateRange(start_date=start.isoformat(), end_date=end.isoformat())],
    )
    summary_res = client.run_report(summary_req)
    s = summary_res.rows[0] if summary_res.rows else None

    return {
        "period": {"start": start.isoformat(), "end": end.isoformat(), "days": days},
        "articles": articles,
        "summary": {
            "total_pageviews": int(s.metric_values[0].value) if s else 0,
            "total_sessions": int(s.metric_values[1].value) if s else 0,
            "total_users": int(s.metric_values[2].value) if s else 0,
        }
    }


def merge_article_data(gsc_data, ga4_data):
    """GSCとGA4のデータを記事URLで結合"""
    merged = {}
    site = GSC_SITE_URL.rstrip("/")

    for article in gsc_data.get("articles", []):
        url = article["url"]
        path = url.replace(site, "")
        merged[path] = {
            "url": url,
            "path": path,
            "gsc_clicks": article["clicks"],
            "gsc_impressions": article["impressions"],
            "gsc_ctr": article["ctr"],
            "gsc_position": article["position"],
            "ga4_pageviews": 0,
            "ga4_sessions": 0,
            "ga4_bounce_rate": 0,
            "ga4_avg_duration": 0,
        }

    for article in ga4_data.get("articles", []):
        path = article["path"]
        if path in merged:
            merged[path].update({
                "ga4_pageviews": article["pageviews"],
                "ga4_sessions": article["sessions"],
                "ga4_bounce_rate": article["bounce_rate"],
                "ga4_avg_duration": article["avg_duration"],
            })
        else:
            merged[path] = {
                "url": site + path,
                "path": path,
                "gsc_clicks": 0,
                "gsc_impressions": 0,
                "gsc_ctr": 0,
                "gsc_position": 0,
                "ga4_pageviews": article["pageviews"],
                "ga4_sessions": article["sessions"],
                "ga4_bounce_rate": article["bounce_rate"],
                "ga4_avg_duration": article["avg_duration"],
            }

    return sorted(merged.values(), key=lambda x: x["ga4_pageviews"], reverse=True)


def collect_and_save(days=7):
    """全データ収集してJSONに保存"""
    result = {
        "collected_at": date.today().isoformat(),
        "period_days": days,
    }

    try:
        gsc = get_gsc_article_metrics(days)
        result["gsc"] = gsc
    except Exception as e:
        result["gsc"] = {"error": str(e)}
        gsc = {}

    try:
        ga4 = get_ga4_article_metrics(days)
        result["ga4"] = ga4
    except Exception as e:
        result["ga4"] = {"error": str(e)}
        ga4 = {}

    if gsc and ga4 and "error" not in gsc and "error" not in ga4:
        result["merged_articles"] = merge_article_data(gsc, ga4)[:50]

    # 保存
    os.makedirs(LOGS_DIR, exist_ok=True)
    out_file = os.path.join(LOGS_DIR, f"article_metrics_{date.today().isoformat()}.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # latest シンボリックリンク的に最新ファイルも保存
    latest_file = os.path.join(LOGS_DIR, "article_metrics_latest.json")
    with open(latest_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    return out_file


if __name__ == "__main__":
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    path = collect_and_save(days)
    print(f"Saved to {path}")
