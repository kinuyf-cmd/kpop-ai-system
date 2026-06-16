#!/bin/bash
# popup_thumbnail_cron_verify.sh — 当日の popup cron 実行後にサムネ root-cause 修正
# (2026-06-16 / [[popup-cron-thumbnail-aiuser-write-fail]])が効いているかを検証し、
# 結果を Discord に通知する。明朝 06:00 ローカル cron で1回走る確認用。
#
# 合否:
#   - 当日分 cron.log に "Permission denied" / "[Errno 13]" が無い
#   - かつ 当日 publish の popup 投稿が（あれば）すべて _thumbnail_id を持つ
#   両方満たせば PASS。新規 popup が 0 件の日は「対象なし」で SKIP 扱い（PASS）。
#
# このスクリプトは一度確認できたら cron から外してよい（恒久監視は audit に委ねる）。
set -uo pipefail

ROOT="/home/aiuser/kpop-ai-system"
cd "$ROOT" || exit 1
LOG="/home/aiuser/.kpop_recovery/popup_event_logs/cron.log"
WP_RO="sudo -n /usr/local/sbin/kpop/kpop-wp-ro"
TODAY="$(date +%Y-%m-%d)"

source "$ROOT/lib/discord_channels.sh" 2>/dev/null || true

notify() {  # <channel> <message>
  if declare -f discord_send >/dev/null 2>&1; then
    discord_send "$1" "$2" >/dev/null 2>&1
  fi
  echo "[$1] $2"
}

# ── 1) 当日分ログに Permission denied が出ていないか ──────────────
# cron.log は追記式。当日の実行ブロック（"$TODAY" を含む行〜）だけを対象にする。
TODAY_BLOCK="$(grep -n "$TODAY" "$LOG" 2>/dev/null | head -1 | cut -d: -f1)"
if [ -n "$TODAY_BLOCK" ]; then
  PERM_HITS="$(tail -n +"$TODAY_BLOCK" "$LOG" | grep -c -E "Permission denied|\[Errno 13\]" 2>/dev/null)"
else
  PERM_HITS="NA"  # 当日ログ無し（cron 未実行/ログ形式変化）
fi

# ── 2) 当日 publish の popup 投稿の featured 充足 ────────────────
IDS="$($WP_RO post list --post_type=post --post_status=publish \
        --after="${TODAY} 00:00" --category_name=popup --field=ID 2>/dev/null \
        | grep -E '^[0-9]+$')"
TOTAL=0; MISSING=0; MISS_IDS=""
for id in $IDS; do
  TOTAL=$((TOTAL+1))
  t="$($WP_RO post meta get "$id" _thumbnail_id 2>/dev/null)"
  if [ -z "$t" ]; then MISSING=$((MISSING+1)); MISS_IDS="$MISS_IDS $id"; fi
done

# ── 判定 ────────────────────────────────────────────────────
if [ "$PERM_HITS" = "NA" ]; then
  notify urgent_errors "⚠️ popupサムネ検証: 当日(${TODAY})のcronログが見つからない。cron未実行/ログ確認を。"
  exit 0
fi

if [ "$PERM_HITS" -gt 0 ] || [ "$MISSING" -gt 0 ]; then
  notify urgent_errors "❌ popupサムネ修正が未達(${TODAY}): Permission denied=${PERM_HITS}件 / featured欠落=${MISSING}/${TOTAL}件(ID:${MISS_IDS}). 手動復旧手順=memory popup-cron-thumbnail-aiuser-write-fail"
  exit 1
fi

if [ "$TOTAL" -eq 0 ]; then
  notify publishing_log "✅ popupサムネ修正OK(${TODAY}): Permission denied 0件。本日新規popupは0件のため featured検証は対象なし。"
else
  notify publishing_log "✅ popupサムネ根治確認(${TODAY}): Permission denied 0件・新規popup ${TOTAL}件すべてfeatured設定済。rw import委譲が正常稼働。"
fi
exit 0
