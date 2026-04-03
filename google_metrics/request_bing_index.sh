#!/bin/bash
# Bing URL Submission API
# Usage: bash ~/google_metrics/request_bing_index.sh "https://www.kpopjournal.tokyo/slug/"
#
# Bing Webmaster Tools API Key を ~/.bing_api_key に保存しておくこと
# 取得方法: https://www.bing.com/webmasters → API access → API Key

URL="$1"
API_KEY=$(cat ~/.bing_api_key 2>/dev/null | tr -d '[:space:]' || echo "")

if [ -z "$URL" ]; then
  echo "❌ URLが指定されていません"
  exit 1
fi

if [ -z "$API_KEY" ]; then
  echo "⚠ Bing API Key未設定 → スキップ (echo 'YOUR_KEY' > ~/.bing_api_key)"
  exit 0
fi

echo "=== Bing URL Submission ==="
echo "  URL: $URL"

RESPONSE=$(curl -s -X POST "https://ssl.bing.com/webmaster/api.svc/json/SubmitUrl?apikey=${API_KEY}" \
  -H "Content-Type: application/json" \
  -d "{\"siteUrl\":\"https://www.kpopjournal.tokyo\",\"url\":\"${URL}\"}")

if echo "$RESPONSE" | python3 -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if d.get('d') is None else 1)" 2>/dev/null; then
  echo "✅ Bing インデックス登録成功: $URL"
else
  echo "⚠ Bing レスポンス: $RESPONSE"
fi
