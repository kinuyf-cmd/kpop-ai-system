#!/usr/bin/env python3
"""過去7日の公開記事でGA4 PV=0のURLをIndexing APIで再通知"""
import sys
import json
import os
import urllib.request
import base64
import time
from datetime import datetime, timezone, timedelta

sys.path.insert(0, "/home/aiuser/kpop-ai-system/lib")
os.environ.setdefault(
    "GOOGLE_APPLICATION_CREDENTIALS",
    "/home/aiuser/kpop-ai-system/google_metrics/service_account.json",
)

from gsc_indexing import notify_url_updated, get_access_token, get_quota_remaining

AUTH = base64.b64encode(b"kpop-bot:vl1H 1brV m4Pq Z1sm F8lZ 3nzh").decode()

# GA4で過去7日のPVを取得
viewed = set()
try:
    from google.analytics.data_v1beta import BetaAnalyticsDataClient
    from google.analytics.data_v1beta.types import (
        RunReportRequest,
        DateRange,
        Dimension,
        Metric,
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

# 過去7日の公開記事
since = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S")
q = (
    f"https://www.kpopjournal.tokyo/wp-json/wp/v2/posts"
    f"?after={since}&per_page=50&_fields=slug,date"
)
try:
    req = urllib.request.Request(q, headers={"Authorization": f"Basic {AUTH}"})
    posts = json.loads(urllib.request.urlopen(req, timeout=30).read())
except Exception as e:
    print(f"WP fetch error: {e}")
    sys.exit(1)

# PV=0のURLを抽出
missing = []
for p in posts:
    path = f"/{p['slug']}".rstrip("/")
    if path not in viewed:
        missing.append(f"https://www.kpopjournal.tokyo{path}/")

print(f"未インデックス候補: {len(missing)}件 (7日内記事 {len(posts)}件中)")

if not missing:
    print("対象なし")
    sys.exit(0)

# クォータ確認
remaining = get_quota_remaining()
max_send = min(len(missing), remaining - 20, 30)  # 最大30件、バッファ20残す
if max_send <= 0:
    print(f"クォータ不足 (残{remaining})")
    sys.exit(0)

print(f"通知: {max_send}件")
token = get_access_token()
ok, ng = 0, 0
for url in missing[:max_send]:
    r = notify_url_updated(url, token=token)
    if r["status"] == "ok":
        ok += 1
    else:
        ng += 1
        if r["status"] == "quota_exceeded":
            break
    time.sleep(1.5)

print(f"結果: OK={ok} / NG={ng}")
