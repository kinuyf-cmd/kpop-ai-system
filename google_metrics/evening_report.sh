#!/bin/bash
set -e

BASE="$HOME/google_metrics"
DISCORD_WEBHOOK="$DISCORD_WEBHOOK"
TODAY=$(date '+%Y-%m-%d')
TODAY_JP=$(date '+%Y年%m月%d日')

# 今日の投稿記事取得
TODAYS_POSTS=$(python3 - << 'PY'
import json, urllib.request, base64, urllib.parse
from datetime import datetime, timezone
today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0).strftime("%Y-%m-%dT%H:%M:%S")
url = "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts?per_page=20&after=" + urllib.parse.quote(today_start)
auth = base64.b64encode(os.environ.get("WP_USER","kpop-bot").encode() + b":" + os.environ.get("WP_PASS","").encode()).decode()
req = urllib.request.Request(url, headers={"Authorization": "Basic " + auth})
try:
    with urllib.request.urlopen(req, timeout=10) as res:
        posts = json.loads(res.read())
    for p in posts:
        print(p["title"]["rendered"][:40] + " | " + p.get("link",""))
except:
    print("投稿記事取得失敗")
PY
)

# メトリクス読み込み
METRICS_JSON="$BASE/metrics_yesterday.json"
SCORE_JSON=$(python3 "$BASE/score_articles.py" < "$METRICS_JSON" 2>/dev/null || echo "[]")

# ログ読み込み
TITLE_LOG=$(tail -20 "$BASE/auto_title_updates.log" 2>/dev/null | grep -E "更新成功|スキップ|NG" | head -5 || echo "なし")
REWRITE_LOG=$(tail -20 "$BASE/rewrite_low_ctr.log" 2>/dev/null | grep -E "成功|失敗" | head -5 || echo "なし")

# Claudeで日報生成
REPORT=$(claude -p "
あなたはK-POPメディア「kpopjournal.tokyo」の編集長AIです。

以下のデータをもとに夜の日報を作成してください。

【出力形式】
・絵文字を使って読みやすく
・1000文字以内
・説明禁止、データそのまま活用

【セクション構成】
📅 ${TODAY_JP} 夜の日報

📝 本日の投稿記事
${TODAYS_POSTS:-なし}

📊 記事スコア上位3件
${SCORE_JSON}

🔧 自動改善の結果
タイトル更新: ${TITLE_LOG}
本文リライト: ${REWRITE_LOG}

🎯 明日の勝ち筋
（スコアデータから改善余地が最も高い記事を1〜2本指摘）
")

# Discord送信
python3 - << 'PY' "$REPORT" "$DISCORD_WEBHOOK"
import requests, sys
report = sys.argv[1]
webhook = sys.argv[2]
payload = {"content": report[:1900]}
requests.post(webhook, json=payload, timeout=30)
print("夜の日報送信完了")
PY
