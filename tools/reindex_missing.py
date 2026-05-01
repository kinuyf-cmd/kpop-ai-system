#!/usr/bin/env python3
"""
未インデックス記事のGSC Indexing API再通知

モード:
  (default) 過去7日の公開記事でGA4 PV=0のURLを再通知
  --from-tracker  GSCインデックスログに記録のない全公開記事を再通知
  --limit N       1回あたりの最大通知数（デフォルト50）
"""
import sys
import json
import os
import argparse
import urllib.request
import base64
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, "/home/aiuser/kpop-ai-system/lib")
os.environ.setdefault(
    "GOOGLE_APPLICATION_CREDENTIALS",
    "/home/aiuser/kpop-ai-system/google_metrics/service_account.json",
)

from gsc_indexing import notify_url_updated, get_access_token, get_quota_remaining
from dotenv import load_dotenv
load_dotenv("/home/aiuser/kpop-ai-system/.env")

AUTH = base64.b64encode(
    f"{os.getenv('WP_USER','')}:{os.getenv('WP_PASS','')}".encode()
).decode()

BASE = Path("/home/aiuser/kpop-ai-system")
GSC_LOG = BASE / "data" / "gsc_indexing_log.jsonl"


def get_indexed_slugs() -> set:
    """GSCインデックスログから登録済みslugを取得"""
    slugs = set()
    if GSC_LOG.exists():
        for line in GSC_LOG.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                slug = entry.get("slug", "")
                if slug:
                    slugs.add(slug)
            except (json.JSONDecodeError, ValueError):
                continue
    return slugs


def fetch_all_published_posts() -> list[dict]:
    """全公開記事のslug/linkを取得"""
    all_posts = []
    for endpoint in ["posts", "popup"]:
        for page in range(1, 20):
            url = (
                f"https://www.kpopjournal.tokyo/wp-json/wp/v2/{endpoint}"
                f"?status=publish&per_page=100&page={page}&_fields=id,slug,link,date"
            )
            try:
                req = urllib.request.Request(url, headers={"Authorization": f"Basic {AUTH}"})
                data = json.loads(urllib.request.urlopen(req, timeout=30).read())
                if not data:
                    break
                all_posts.extend(data)
            except Exception:
                break
    return all_posts


def find_missing_from_tracker() -> list[str]:
    """GSCインデックスログに記録のない公開記事URLを抽出"""
    indexed_slugs = get_indexed_slugs()
    all_posts = fetch_all_published_posts()
    missing = []
    for p in all_posts:
        slug = p.get("slug", "")
        link = p.get("link", "")
        if slug and slug not in indexed_slugs and link:
            missing.append(link)
    print(f"全公開記事: {len(all_posts)}件, GSC登録済: {len(indexed_slugs)}件, 未登録: {len(missing)}件")
    return missing


def find_missing_from_ga4() -> list[str]:
    """過去7日の公開記事でGA4 PV=0のURLを抽出（従来方式）"""
    viewed = set()
    try:
        from google.analytics.data_v1beta import BetaAnalyticsDataClient
        from google.analytics.data_v1beta.types import (
            RunReportRequest, DateRange, Dimension, Metric,
        )
        c = BetaAnalyticsDataClient()
        rp = c.run_report(
            RunReportRequest(
                property="properties/493983919",
                date_ranges=[DateRange(start_date="7daysAgo", end_date="today")],
                dimensions=[Dimension(name="pagePath")],
                metrics=[Metric(name="screenPageViews")],
                limit=500,
            )
        )
        for row in rp.rows:
            path = row.dimension_values[0].value
            if row.metric_values[0].value and int(row.metric_values[0].value) > 0:
                viewed.add(path.rstrip("/"))
        print(f"GA4 過去7日PV>0: {len(viewed)}件")
    except Exception as e:
        print(f"GA4 error: {e}")

    since = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S")
    url = (
        f"https://www.kpopjournal.tokyo/wp-json/wp/v2/posts"
        f"?after={since}&per_page=50&_fields=slug,date"
    )
    try:
        req = urllib.request.Request(url, headers={"Authorization": f"Basic {AUTH}"})
        posts = json.loads(urllib.request.urlopen(req, timeout=30).read())
    except Exception as e:
        print(f"WP fetch error: {e}")
        return []

    missing = []
    for p in posts:
        path = f"/{p['slug']}".rstrip("/")
        if path not in viewed:
            missing.append(f"https://www.kpopjournal.tokyo{path}/")
    print(f"未インデックス候補: {len(missing)}件 (7日内記事 {len(posts)}件中)")
    return missing


def send_indexing_requests(missing: list[str], limit: int):
    """Indexing APIで再通知"""
    if not missing:
        print("対象なし")
        return

    remaining = get_quota_remaining()
    max_send = min(len(missing), remaining - 20, limit)
    if max_send <= 0:
        print(f"クォータ不足 (残{remaining})")
        return

    print(f"通知: {max_send}件 (クォータ残: {remaining})")
    token = get_access_token()
    ok, ng = 0, 0
    for url in missing[:max_send]:
        r = notify_url_updated(url, token=token)
        if r["status"] == "ok":
            ok += 1
            # GSCログにも記録
            slug = url.rstrip("/").split("/")[-1]
            with open(GSC_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "slug": slug, "url": url,
                    "indexed_at": datetime.now(timezone.utc).isoformat(),
                    "source": "reindex_missing"
                }, ensure_ascii=False) + "\n")
        else:
            ng += 1
            if r["status"] == "quota_exceeded":
                print("クォータ超過 — 中断")
                break
        time.sleep(1.5)

    print(f"結果: OK={ok} / NG={ng}")


def main():
    parser = argparse.ArgumentParser(description="未インデックス記事のGSC再通知")
    parser.add_argument("--from-tracker", action="store_true",
                        help="GSCインデックスログに記録のない全公開記事を対象にする")
    parser.add_argument("--limit", type=int, default=50,
                        help="1回あたりの最大通知数 (default: 50)")
    args = parser.parse_args()

    print(f"=== reindex_missing {datetime.now().isoformat()[:19]} ===")

    if args.from_tracker:
        missing = find_missing_from_tracker()
    else:
        missing = find_missing_from_ga4()

    send_indexing_requests(missing, args.limit)


if __name__ == "__main__":
    main()
