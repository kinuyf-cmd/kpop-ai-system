#!/bin/bash
# 48時間後再監査スクリプト
# Usage: bash run_reaudit.sh [--hours 48]
# 出力: 改善/未反映/悪化 の3分類レポート

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/.venv/bin/activate" 2>/dev/null || true

HOURS="${1:-48}"
REPORT_DATE=$(date +%Y-%m-%d_%H%M)
REPORT_FILE="$SCRIPT_DIR/logs/reaudit_${REPORT_DATE}.md"

echo "=== 再監査開始: $(date '+%Y-%m-%d %H:%M JST') ===" | tee "$REPORT_FILE"
echo "" >> "$REPORT_FILE"

echo "### [1] 総合監査" | tee -a "$REPORT_FILE"
python3 "$SCRIPT_DIR/lib/audit_72h.py" 2>/dev/null | tee -a "$REPORT_FILE"

echo "" >> "$REPORT_FILE"
echo "### [2] サムネイル監査 (ワースト5)" | tee -a "$REPORT_FILE"
python3 "$SCRIPT_DIR/lib/thumbnail_audit.py" 2555 2574 2544 2581 2442 2>/dev/null | tee -a "$REPORT_FILE"

echo "" >> "$REPORT_FILE"
echo "### [3] X投稿監査" | tee -a "$REPORT_FILE"
python3 "$SCRIPT_DIR/lib/x_post_audit.py" 2>/dev/null | head -40 | tee -a "$REPORT_FILE"

echo "" >> "$REPORT_FILE"
echo "### [4] GSCインデックス再確認" | tee -a "$REPORT_FILE"

# Run GSC check for the 17 submitted URLs
python3 - << 'PY' 2>/dev/null | tee -a "$REPORT_FILE"
import json, sys
from pathlib import Path
from google.oauth2 import service_account
from google.auth.transport.requests import Request
import requests

SCRIPT_DIR = Path('/home/aiuser/kpop-ai-system')

URLS_TO_CHECK = [
    ("2581", "https://www.kpopjournal.tokyo/aespa-serenade-lollipop-2026/"),
    ("2555", "https://www.kpopjournal.tokyo/kpop-chart-top10-week15-april-2026/"),
    ("2544", "https://www.kpopjournal.tokyo/bts-arirang-billboard-641-000-3weeks-1-2026/"),
    ("2530", "https://www.kpopjournal.tokyo/kpop-chart-guide-2530/"),
    ("2485", "https://www.kpopjournal.tokyo/kpop-profile-hub-2026/"),
    ("2475", "https://www.kpopjournal.tokyo/bts-profile-2026/"),
    ("2574", "https://www.kpopjournal.tokyo/top-another-dimension-13years-2026/"),
    ("2568", "https://www.kpopjournal.tokyo/bts-6years-return-arirang-2026/"),
]

try:
    SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
    creds = service_account.Credentials.from_service_account_file(
        str(SCRIPT_DIR / "google_metrics/service_account.json"), scopes=SCOPES
    )
    creds.refresh(Request())
    headers = {"Authorization": "Bearer " + creds.token, "Content-Type": "application/json"}

    indexed = []
    pending = []
    unknown = []

    for post_id, url in URLS_TO_CHECK:
        body = {"inspectionUrl": url, "siteUrl": "https://www.kpopjournal.tokyo/"}
        r = requests.post(
            "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect",
            headers=headers, json=body, timeout=10
        )
        if r.ok:
            result = r.json().get("inspectionResult", {})
            index_status = result.get("indexStatusResult", {}).get("coverageState", "unknown")
            verdict = result.get("indexStatusResult", {}).get("verdict", "NEUTRAL")
            if verdict == "PASS":
                indexed.append((post_id, url, index_status))
            else:
                unknown.append((post_id, url, index_status))
        else:
            pending.append((post_id, url, "API error"))

    print(f"  登録済み ({len(indexed)}件): {[p[0] for p in indexed]}")
    print(f"  未反映   ({len(pending) + len(unknown)}件): {[p[0] for p in pending + unknown]}")
    for pid, url, state in unknown[:5]:
        print(f"    ID={pid}: {state}")
except Exception as e:
    print(f"  GSC確認エラー: {e}")
PY

echo "" >> "$REPORT_FILE"
echo "=== 再監査完了: $(date '+%Y-%m-%d %H:%M JST') ===" | tee -a "$REPORT_FILE"
echo "レポート保存先: $REPORT_FILE"
