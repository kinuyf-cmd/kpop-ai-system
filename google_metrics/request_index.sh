#!/bin/bash
# Google Indexing API にURL更新を通知するスクリプト
# Usage: bash ~/google_metrics/request_index.sh "https://example.com/post-slug"

URL="$1"

if [ -z "$URL" ]; then
  echo "❌ URLが指定されていません"
  echo "Usage: $0 <URL>"
  exit 1
fi

echo "=== Google Indexing API リクエスト ==="
echo "  URL: $URL"

python3 - "$URL" << 'PY'
import sys, json
from google.oauth2 import service_account
from google.auth.transport.requests import Request
import requests

url = sys.argv[1]

SCOPES = ["https://www.googleapis.com/auth/indexing"]

creds = service_account.Credentials.from_service_account_file(
    "/Users/funayamayuuta/google_metrics/service_account.json",
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

r = requests.post(endpoint, headers=headers, data=json.dumps(data))
result = r.json() if r.ok else {"error": r.text}
print(json.dumps(result, indent=2, ensure_ascii=False))

if r.ok:
    print(f"\n✅ インデックス登録リクエスト成功: {url}")
else:
    print(f"\n❌ インデックス登録失敗 (HTTP {r.status_code})")
    sys.exit(1)
PY
