#!/bin/bash
# 週次レポート reports/weekly-<date>.md(毎週月曜 cron)
cd "$(dirname "$0")/.." || exit 2
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
# cron 用の長期トークン(claude setup-token で発行)。ファイルがあれば使う(chmod 600)
TOKEN_FILE="$HOME/.config/kpj/claude_oauth_token"
if [ -s "$TOKEN_FILE" ]; then export CLAUDE_CODE_OAUTH_TOKEN="$(tr -d '[:space:]' < "$TOKEN_FILE")"; fi
PY=venv_kpi/bin/python3; [ -x "$PY" ] || PY=python3
exec "$PY" tools/content_pipeline/weekly_report.py "$@"
