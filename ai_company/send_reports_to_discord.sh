#!/bin/bash
set -e

BASE="$HOME/ai_company/reports"
WEBHOOK=$(cat ~/.kpop_discord_webhook | tr -d '[:space:]')

send() {
  local title="$1"
  local file="$2"

  [ ! -f "$file" ] && return

  CONTENT=$(cat "$file")

  python3 - << PY
import requests, json

webhook = """$WEBHOOK"""
title = """$title"""
content = """$CONTENT"""

msg = f"📊 {title}\n\n{content}"

# Discord制限対策
msg = msg[:1900]

requests.post(webhook, json={"content": msg}, timeout=20)
PY
}

# =========================
# 朝レポート
# =========================
send "戦略会議（butterfree）" "$BASE/butterfree_report.md"
send "SEO分析（lapras）" "$BASE/lapras_report.md"
send "競合分析（mimikyu）" "$BASE/mimikyu_report.md"
send "未来予測（jirachi）" "$BASE/jirachi_report.md"
send "編集長判断（mewtwo）" "$BASE/mewtwo_decision.md"

# =========================
# 夜レポート
# =========================
send "記事生成（deoxys）" "$BASE/deoxys_output.md"
send "CTR改善（metamon）" "$BASE/metamon_output.md"
send "収益分析（meowth）" "$BASE/meowth_output.md"
send "全体振り返り（porygon）" "$BASE/porygon_review.md"

echo "✅ Discord送信完了"
