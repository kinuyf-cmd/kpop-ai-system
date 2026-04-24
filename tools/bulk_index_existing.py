#!/usr/bin/env python3
"""既存の公開記事をIndexing APIで一括通知する (初回実行専用)

実行後は cron+enricherで新規記事のみ自動通知されるため再実行不要
"""
import sys
import json
import urllib.request
import base64
from datetime import datetime, timezone, timedelta

sys.path.insert(0, "/home/aiuser/kpop-ai-system/lib")

from gsc_indexing import notify_url_updated, get_access_token, get_quota_remaining
import time

AUTH = base64.b64encode(b"kpop-bot:vl1H 1brV m4Pq Z1sm F8lZ 3nzh").decode()

# 過去30日の公開記事を取得
since = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S")
urls = []
for page in range(1, 5):
    q = (
        f"https://www.kpopjournal.tokyo/wp-json/wp/v2/posts"
        f"?after={since}&per_page=50&page={page}&orderby=date&order=asc&_fields=slug,date"
    )
    try:
        req = urllib.request.Request(q, headers={"Authorization": f"Basic {AUTH}"})
        posts = json.loads(urllib.request.urlopen(req, timeout=30).read())
        if not posts:
            break
        for p in posts:
            urls.append(f"https://www.kpopjournal.tokyo/{p['slug']}/")
    except urllib.error.HTTPError as e:
        if e.code == 400:
            break
        print(f"page {page} error: {e}")
        break
    except Exception as e:
        print(f"page {page} error: {e}")
        break

print(f"対象URL数: {len(urls)}")

# クォータ残量チェック
remaining = get_quota_remaining()
print(f"本日クォータ残: {remaining}")

# 新規記事用にバッファ30件残す
max_bulk = min(len(urls), remaining - 30)
if max_bulk <= 0:
    print("クォータ不足、スキップ")
    sys.exit(0)

urls = urls[:max_bulk]
print(f"通知実行: {len(urls)}件")

token = get_access_token()
ok, ng = 0, 0
for i, url in enumerate(urls, 1):
    r = notify_url_updated(url, token=token)
    mark = "OK" if r["status"] == "ok" else r["status"].upper()
    if i <= 5 or i % 20 == 0:
        print(f"  [{i}/{len(urls)}] {mark} {url[-40:]}")
    if r["status"] == "ok":
        ok += 1
    else:
        ng += 1
        if r["status"] == "quota_exceeded":
            print("  QUOTA EXCEEDED — stopping")
            break
    time.sleep(1.0)

print(f"\n結果: OK={ok} / NG={ng}")
