#!/bin/bash
set -e

BASE_DIR="$HOME/google_metrics"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/lib/discord_channels.sh" 2>/dev/null || true
WEBHOOK_URL=$(get_discord_webhook "seo" 2>/dev/null || cat ~/.kpop_discord_webhook 2>/dev/null | tr -d '[:space:]' || echo "")

JSON_PATH="$BASE_DIR/metrics_yesterday.json"

PROMPT_FILE="$BASE_DIR/prompt_morning_report.txt"
METRICS_JSON=$(cat "$JSON_PATH")
PROMPT_TEXT=$(cat "$PROMPT_FILE")
SCORE_JSON=$(python3 "$BASE_DIR/score_articles.py" < "$JSON_PATH")

REPORT=$(claude -p "$PROMPT_TEXT

以下が前日の実データです。
$METRICS_JSON")

SCORE_REPORT=$(claude -p "【記事スコア分析】
以下のJSONは記事スコアです。
上位3記事と下位3記事を抽出し、以下を出力せよ：

- 強化すべき記事（理由）
- 改善すべき記事（具体改善案）
- 捨てる or 放置する記事

JSON:
$SCORE_JSON")

echo "$REPORT" > /tmp/morning_report.txt
echo "$SCORE_REPORT" > /tmp/morning_score_report.txt
echo "$WEBHOOK_URL" > /tmp/morning_webhook.txt

python3 - << 'PY'
import json, requests

with open("/tmp/morning_webhook.txt") as f:
    webhook = f.read().strip()
with open("/tmp/morning_report.txt") as f:
    report = f.read().strip()
with open("/tmp/morning_score_report.txt") as f:
    score_report = f.read().strip()

for content in [report, score_report]:
    payload = {"content": content[:1900]}
    requests.post(webhook, json=payload, timeout=30)
PY
