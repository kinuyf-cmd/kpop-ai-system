#!/bin/bash
# CEO会議 自動検証スクリプト（1回限り）
# 21:00 cron実行後に呼ばれ、結果を検証してレポートを出力する
set -uo pipefail

REPO="$HOME/kpop-ai-system"
REPORTS="$HOME/ai_company/reports"
LOG="$REPO/logs/ai_meeting.log"
REPORT_OUT="$REPO/logs/meeting_verify_$(date '+%Y%m%d').txt"
TODAY=$(date '+%Y-%m-%d')

# 会議完了を最大20分待つ
WAITED=0
while [ $WAITED -lt 1200 ]; do
  if grep -q "=== \[$TODAY" "$LOG" 2>/dev/null && \
     tail -5 "$LOG" | grep -q "Discord送信完了" 2>/dev/null; then
    break
  fi
  sleep 30
  WAITED=$((WAITED + 30))
done

{
echo "=============================="
echo "CEO会議 自動検証レポート"
echo "検証時刻: $(date '+%Y-%m-%d %H:%M:%S')"
echo "=============================="
echo ""

# ① ログ確認
LAST_START=$(grep "run_ai_meeting 開始" "$LOG" | tail -1)
LAST_COMPLETE=$(tail -20 "$LOG" | grep "AI会社会議 完了" | tail -1)
LAST_DISCORD=$(tail -20 "$LOG" | grep "Discord送信完了" | tail -1)

if echo "$LAST_START" | grep -q "$TODAY"; then
  echo "① CEO会議ログ: ✅ 今日実行あり"
  echo "   開始: $LAST_START"
else
  echo "① CEO会議ログ: ❌ 今日の実行なし"
  echo "   最終: $LAST_START"
fi

if [ -n "$LAST_COMPLETE" ]; then
  echo "   完了: ✅"
else
  echo "   完了: ❌ 完了ログなし"
fi

if [ -n "$LAST_DISCORD" ]; then
  echo "   Discord: ✅ 送信済み"
else
  echo "   Discord: ⚠ 送信未確認"
fi

echo ""

# ② タスクファイル確認
echo "② 制作部タスクファイル:"
ALL_OK=true
for agent in deoxys metamon meowth; do
  FILE="$REPORTS/${agent}_task.md"
  if [ -f "$FILE" ]; then
    SIZE=$(wc -c < "$FILE")
    MDATE=$(date -r "$FILE" '+%Y-%m-%d')
    if [ "$SIZE" -gt 0 ] && [ "$MDATE" = "$TODAY" ]; then
      echo "   ${agent}_task.md: ✅ ${SIZE}B (${MDATE})"
    elif [ "$SIZE" -eq 0 ]; then
      echo "   ${agent}_task.md: ❌ 0バイト（extract_sectionバグ再発の可能性）"
      ALL_OK=false
    else
      echo "   ${agent}_task.md: ⚠ ${SIZE}B だが日付が古い(${MDATE})"
      ALL_OK=false
    fi
  else
    echo "   ${agent}_task.md: ❌ ファイルなし"
    ALL_OK=false
  fi
done

echo ""

# ③ 主要レポート確認
echo "③ 主要レポート更新:"
for report in butterfree_report lapras_report mimikyu_report jirachi_report \
              mewtwo_decision arceus_audit porygon_z_sre porygon_review \
              deoxys_output metamon_output meowth_output; do
  FILE="$REPORTS/${report}.md"
  if [ -f "$FILE" ]; then
    SIZE=$(wc -c < "$FILE")
    MDATE=$(date -r "$FILE" '+%Y-%m-%d')
    if [ "$MDATE" = "$TODAY" ] && [ "$SIZE" -gt 0 ]; then
      echo "   ${report}.md: ✅ ${SIZE}B"
    else
      echo "   ${report}.md: ⚠ ${SIZE}B (${MDATE})"
    fi
  else
    echo "   ${report}.md: ❌ なし"
  fi
done

echo ""

# ④ 総合判定
echo "=============================="
if echo "$LAST_START" | grep -q "$TODAY" && [ -n "$LAST_COMPLETE" ] && [ "$ALL_OK" = true ]; then
  echo "総合判定: ✅ 全正常 — 組織稼働復旧完了"
else
  echo "総合判定: ⚠ 要確認項目あり"
fi
echo "=============================="
} | tee "$REPORT_OUT"

# Discord通知
MEETING_SCRIPT_DIR="$REPO"
source "$REPO/lib/discord_channels.sh" 2>/dev/null || true
WEBHOOK=$(get_discord_webhook "daily_ceo_report" 2>/dev/null || echo "")
[ -z "$WEBHOOK" ] && WEBHOOK="${DISCORD_WEBHOOK:-}"
[ -z "$WEBHOOK" ] && [ -f ~/.kpop_discord_webhook ] && WEBHOOK=$(cat ~/.kpop_discord_webhook | tr -d '[:space:]')

if [ -n "$WEBHOOK" ]; then
  VERIFY_MSG=$(cat "$REPORT_OUT" | head -40 | tr '\n' ' ' | cut -c1-1900)
  curl -s -o /dev/null -X POST "$WEBHOOK" \
    -H "Content-Type: application/json" \
    -d "$(python3 -c "import json,sys; print(json.dumps({'content': sys.argv[1]}))" "$VERIFY_MSG")" 2>/dev/null
fi

# 自身のcronエントリを削除（1回限り）
crontab -l 2>/dev/null | grep -v "verify_meeting.sh" | crontab -
