#!/bin/bash
set -e

BASE="$HOME/google_metrics"
DISCORD_WEBHOOK="$DISCORD_WEBHOOK"
LOG="$BASE/weekly_review.log"

echo "" >> "$LOG"
echo "=== $(date '+%Y-%m-%d %H:%M') 週次レビュー ===" >> "$LOG"

# 過去7日間のGA4/GSC/AdSenseデータ取得
WEEK_METRICS=$(python3 - << 'PY'
import os, json
from google.oauth2 import service_account
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import DateRange, Metric, Dimension, RunReportRequest
from googleapiclient.discovery import build
from datetime import date, timedelta
import warnings
warnings.filterwarnings("ignore")

BASE = os.path.expanduser("~/google_metrics")
SA = os.path.join(BASE, "service_account.json")

# GA4 週次
creds = service_account.Credentials.from_service_account_file(SA, scopes=["https://www.googleapis.com/auth/analytics.readonly"])
client = BetaAnalyticsDataClient(credentials=creds)
req = RunReportRequest(
    property="properties/493983919",
    metrics=[
        {"name":"sessions"},{"name":"totalUsers"},
        {"name":"screenPageViews"},{"name":"engagedSessions"}
    ],
    date_ranges=[DateRange(start_date="7daysAgo", end_date="yesterday")],
)
res = client.run_report(req)
row = res.rows[0]
ga4 = {
    "sessions": row.metric_values[0].value,
    "users": row.metric_values[1].value,
    "pageviews": row.metric_values[2].value,
    "engaged": row.metric_values[3].value,
}

# GSC 週次
gsc_creds = service_account.Credentials.from_service_account_file(SA, scopes=["https://www.googleapis.com/auth/webmasters.readonly"])
svc = build("searchconsole", "v1", credentials=gsc_creds)
end = (date.today() - timedelta(days=1)).isoformat()
start = (date.today() - timedelta(days=7)).isoformat()
gsc_res = svc.searchanalytics().query(
    siteUrl="https://www.kpopjournal.tokyo/",
    body={"startDate": start, "endDate": end,
          "dimensions": ["query"], "rowLimit": 10}
).execute()
top_queries = [
    {"query": r["keys"][0], "clicks": r.get("clicks",0), "impressions": r.get("impressions",0), "ctr": round(r.get("ctr",0)*100,1), "position": round(r.get("position",0),1)}
    for r in gsc_res.get("rows", [])
]

print(json.dumps({"ga4": ga4, "gsc": {"top_queries": top_queries}}, ensure_ascii=False))
PY
)

# 今週の投稿記事数
POSTS_THIS_WEEK=$(python3 - << 'PY'
import urllib.request, base64, urllib.parse, json
from datetime import datetime, timedelta, timezone
start = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S")
url = "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts?per_page=100&after=" + urllib.parse.quote(start)
auth = base64.b64encode(os.environ.get("WP_USER","kpop-bot").encode() + b":" + os.environ.get("WP_PASS","").encode()).decode()
req = urllib.request.Request(url, headers={"Authorization": "Basic " + auth})
with urllib.request.urlopen(req, timeout=10) as res:
    posts = json.loads(res.read())
print(len(posts))
for p in posts[:5]:
    print(p["title"]["rendered"][:40])
PY
)

# 改善ログ集計
TITLE_UPDATES=$(grep -c "更新成功" "$BASE/auto_title_updates.log" 2>/dev/null || echo 0)
REWRITES=$(grep -c "リライト成功" "$BASE/rewrite_low_ctr.log" 2>/dev/null || echo 0)
REVENUE_CTA=$(grep -c "CTA強化完了" "$BASE/revenue_cta.log" 2>/dev/null || echo 0)
NOINDEX=$(grep -c "noindex設定" "$BASE/noindex_candidates.log" 2>/dev/null || echo 0)

# Claudeで週次レポート生成
REPORT=$(claude -p "
あなたはK-POPメディア「kpopjournal.tokyo」の編集長AIです。

以下のデータをもとに週次レビューを作成してください。

【出力形式】
・絵文字を使って読みやすく
・1200文字以内
・説明禁止

【セクション構成】
📊 週次レポート

📈 今週のトラフィック
$WEEK_METRICS

📝 今週の投稿
$POSTS_THIS_WEEK

🔧 自動改善の実績
・タイトル更新: ${TITLE_UPDATES}件
・本文リライト: ${REWRITES}件
・CTA強化: ${REVENUE_CTA}件
・noindex設定: ${NOINDEX}件

🎯 来週の戦略
（データから来週やるべき1〜3のアクションを具体的に）
")

# Discord送信（2分割）
python3 - << 'PY' "$REPORT" "$DISCORD_WEBHOOK"
import requests, sys
report = sys.argv[1]
webhook = sys.argv[2]
chunks = [report[i:i+1900] for i in range(0, len(report), 1900)]
for chunk in chunks:
    requests.post(webhook, json={"content": chunk}, timeout=30)
print("週次レポート送信完了")
PY

echo "週次レビュー完了" | tee -a "$LOG"
