#!/bin/bash
# 自律コンテンツパイプライン(2時間ごと cron)。monitor → 執筆/ファクトチェック/validate/承認/公開 → X。
# 緊急停止: touch content/STOP   再開: rm content/STOP   状況: scripts/content-pipeline.sh status
cd "$(dirname "$0")/.." || exit 2
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
# cron 用の長期トークン(claude setup-token で発行)。ファイルがあれば使う(chmod 600)
TOKEN_FILE="$HOME/.config/kpj/claude_oauth_token"
if [ -s "$TOKEN_FILE" ]; then export CLAUDE_CODE_OAUTH_TOKEN="$(tr -d '[:space:]' < "$TOKEN_FILE")"; fi
PY=venv_kpi/bin/python3; [ -x "$PY" ] || PY=python3
STAGE="${1:-run}"; shift || true
if [ "$STAGE" = "status" ]; then exec "$PY" tools/content_pipeline/pipeline.py status; fi
# 前回の回がまだ走っていれば今回は飛ばす(並走で同じ項目を二重に書かない)
exec flock -n /tmp/kpj_content_pipeline.lock "$PY" tools/content_pipeline/pipeline.py "$STAGE" "$@"
