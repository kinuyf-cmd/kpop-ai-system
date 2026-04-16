#!/bin/bash
# Google Indexing API にURL更新を通知するスクリプト
# Usage: bash ~/google_metrics/request_index.sh "https://example.com/post-slug"

# venv有効化（google-authモジュールのため）
VENV="$HOME/kpop-ai-system/.venv/bin/activate"
[ -f "$VENV" ] && source "$VENV"

URL="$1"

if [ -z "$URL" ]; then
  echo "❌ URLが指定されていません"
  echo "Usage: $0 <URL>"
  exit 1
fi

echo "=== Google Indexing API リクエスト ==="
echo "  URL: $URL"

python3 - "$URL" << 'PY'
import sys, json, time
from google.oauth2 import service_account
from google.auth.transport.requests import Request
import requests

url = sys.argv[1]
MAX_RETRIES = 3

SCOPES = ["https://www.googleapis.com/auth/indexing"]

creds = service_account.Credentials.from_service_account_file(
    "/home/aiuser/kpop-ai-system/google_metrics/service_account.json",
    scopes=SCOPES
)

creds.refresh(Request())

endpoint = "https://indexing.googleapis.com/v3/urlNotifications:publish"

headers = {
    "Content-Type": "application/json",
    "Authorization": "Bearer " + creds.token
}

data = {
    "url": url,
    "type": "URL_UPDATED"
}

for attempt in range(MAX_RETRIES):
    try:
        r = requests.post(endpoint, headers=headers, data=json.dumps(data), timeout=30)
        result = r.json() if r.ok else {"error": r.text}
        print(json.dumps(result, indent=2, ensure_ascii=False))

        if r.ok:
            print(f"\n✅ インデックス登録リクエスト成功: {url}")
            sys.exit(0)
        else:
            print(f"\n⚠ 試行{attempt+1}/{MAX_RETRIES} 失敗 (HTTP {r.status_code})")
    except Exception as e:
        print(f"\n⚠ 試行{attempt+1}/{MAX_RETRIES} エラー: {e}")

    if attempt < MAX_RETRIES - 1:
        delay = 5 * (attempt + 1)
        print(f"  {delay}秒後にリトライ...")
        time.sleep(delay)

print(f"\n❌ インデックス登録失敗（{MAX_RETRIES}回リトライ後）: {url}")
sys.exit(1)
PY
