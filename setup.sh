#!/bin/bash
set -e
cd "$(dirname "$0")"
python3 -m pip install --user requests playwright google-api-python-client google-auth google-auth-oauthlib google-analytics-data pillow browser-cookie3
python3 -m playwright install chromium
chmod +x *.sh 2>/dev/null || true
chmod +x google_metrics/*.sh 2>/dev/null || true
chmod +x ai_company/*.sh 2>/dev/null || true
echo "✅ setup 完了"
