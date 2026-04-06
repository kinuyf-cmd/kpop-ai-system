#!/usr/bin/env python3
"""
初動パフォーマンス測定（v1.2 Phase 4）

投稿後24時間のPV・流入元を計測し、記録する。
毎日10:00にcronで実行し、前日投稿分の初動を計測。

データ本部（ミュウツー）管轄
"""
import json
import os
import sys
from datetime import date, datetime, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

LOGS_DIR = os.path.join(BASE_DIR, "logs")
KPI_FILE = os.path.join(LOGS_DIR, "kpi_posts.jsonl")
INITIAL_PERF_FILE = os.path.join(LOGS_DIR, "initial_performance.jsonl")
METRICS_FILE = os.path.join(BASE_DIR, "google_metrics", "metrics_yesterday.json")


def load_yesterday_posts():
    """前日に投稿された記事をKPIログから取得"""
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    posts = []
    if not os.path.exists(KPI_FILE):
        return posts
    with open(KPI_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if entry.get("date") == yesterday:
                    posts.append(entry)
            except json.JSONDecodeError:
                continue
    return posts


def load_metrics():
    """GA4/GSCメトリクスを読み込み"""
    if not os.path.exists(METRICS_FILE):
        return {}
    with open(METRICS_FILE, encoding="utf-8") as f:
        return json.load(f)


def measure_initial_performance():
    """前日投稿分の初動パフォーマンスを計測"""
    posts = load_yesterday_posts()
    if not posts:
        print("前日投稿なし → スキップ")
        return

    metrics = load_metrics()
    ga4 = metrics.get("ga4", {})
    gsc = metrics.get("gsc", {})

    # GA4のトップページデータからURL別PVを取得
    top_pages = ga4.get("top_landing_pages", [])
    page_pv_map = {}
    for page in top_pages:
        if isinstance(page, dict):
            page_pv_map[page.get("page", "")] = page.get("sessions", 0)
        elif isinstance(page, str):
            page_pv_map[page] = 0

    # GSCのトップページデータ
    gsc_pages = gsc.get("top_pages", [])
    page_clicks_map = {}
    page_impressions_map = {}
    for page in gsc_pages:
        if isinstance(page, dict):
            url = page.get("page", page.get("url", ""))
            page_clicks_map[url] = page.get("clicks", 0)
            page_impressions_map[url] = page.get("impressions", 0)

    os.makedirs(LOGS_DIR, exist_ok=True)
    results = []

    for post in posts:
        slug = post.get("slug", "")
        url = post.get("url", "")
        post_id = post.get("post_id", "")

        # URLまたはスラッグでマッチ
        initial_pv = 0
        search_clicks = 0
        search_impressions = 0

        for page_url, pv in page_pv_map.items():
            if slug and slug in page_url:
                initial_pv += pv
            elif url and url in page_url:
                initial_pv += pv

        for page_url, clicks in page_clicks_map.items():
            if slug and slug in page_url:
                search_clicks += clicks
            elif url and url in page_url:
                search_clicks += clicks

        for page_url, imps in page_impressions_map.items():
            if slug and slug in page_url:
                search_impressions += imps
            elif url and url in page_url:
                search_impressions += imps

        result = {
            "timestamp": datetime.now().isoformat(),
            "measurement_date": date.today().isoformat(),
            "post_date": post.get("date", ""),
            "post_id": post_id,
            "title": post.get("title", ""),
            "url": url,
            "slug": slug,
            "pipeline": post.get("pipeline", ""),
            "char_count": post.get("char_count", 0),
            "initial_24h_pv": initial_pv,
            "initial_24h_search_clicks": search_clicks,
            "initial_24h_search_impressions": search_impressions,
            "has_cta": post.get("has_cta", False),
            "token_count": post.get("token_count", 0),
        }
        results.append(result)

        with open(INITIAL_PERF_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")

    # サマリー出力
    total_posts = len(results)
    total_pv = sum(r["initial_24h_pv"] for r in results)
    avg_pv = total_pv / total_posts if total_posts else 0

    print(f"初動計測完了: {total_posts}記事")
    print(f"  合計PV: {total_pv}")
    print(f"  平均PV: {avg_pv:.1f}")
    for r in results:
        print(f"  - [{r['initial_24h_pv']}PV] {r['title'][:40]}")

    return results


if __name__ == "__main__":
    measure_initial_performance()
