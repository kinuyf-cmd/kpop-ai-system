#!/bin/bash
# Google Indexing API にURL更新を通知するスクリプト
# Usage: bash ~/google_metrics/request_index.sh "https://example.com/post-slug"

# venv有効化（google-authモジュールのため）
VENV_DIR="$HOME/kpop-ai-system/.venv"
VENV="$VENV_DIR/bin/activate"
[ -f "$VENV" ] && source "$VENV"
# cron環境ではsource後もPATHが通らない場合があるため明示指定
PYTHON3="${VENV_DIR}/bin/python3"
[ ! -x "$PYTHON3" ] && PYTHON3="python3"

URL="$1"

if [ -z "$URL" ]; then
  echo "❌ URLが指定されていません"
  echo "Usage: $0 <URL>"
  exit 1
fi

# 重複送信防止: 24時間以内に同じURLを送信済みならスキップ
LOG_FILE="$HOME/kpop-ai-system/data/gsc_indexing_log.jsonl"
if [ -f "$LOG_FILE" ]; then
  CUTOFF=$(date -d '24 hours ago' +%Y-%m-%dT%H:%M 2>/dev/null || date -v-24H +%Y-%m-%dT%H:%M 2>/dev/null)
  if [ -n "$CUTOFF" ]; then
    RECENT_HIT=$(grep "$URL" "$LOG_FILE" | tail -5 | grep -c "\"status\": \"ok\"" || true)
    if [ "$RECENT_HIT" -gt 0 ]; then
      LAST_TS=$(grep "$URL" "$LOG_FILE" | grep '"status": "ok"' | tail -1 | grep -oP '"timestamp": "\K[^"]+' || echo "")
      if [ -n "$LAST_TS" ] && [[ "$LAST_TS" > "$CUTOFF" ]]; then
        echo "⏭ スキップ: $URL (24h以内に送信済み: $LAST_TS)"
        exit 0
      fi
    fi
  fi
fi

echo "=== Google Indexing API リクエスト ==="
echo "  URL: $URL"

$PYTHON3 - "$URL" << 'PY'
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
            # gsc_indexing_log.jsonl にも記録(重複検知用)
            import datetime as _dt
            _log_entry = {"status": "ok", "url": url,
                         "timestamp": _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=9))).isoformat(),
                         "method": "indexing_api"}
            try:
                with open("/home/aiuser/kpop-ai-system/data/gsc_indexing_log.jsonl", "a") as _f:
                    _f.write(json.dumps(_log_entry, ensure_ascii=False) + "\n")
            except: pass
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
