#!/bin/bash
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# K-POP誕生日記事自動生成パイプライン
# 毎朝 6:30 に実行 — 当日＋翌日の誕生日記事を自動生成・投稿
#
# 使い方:
#   bash kpop_birthday_pipeline.sh              # 当日+翌日分
#   bash kpop_birthday_pipeline.sh --dry-run    # テスト
#   bash kpop_birthday_pipeline.sh --check-week # 今週の誕生日確認
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/env_loader.sh"

# パイプライン排他ロック
_GLOBAL_PIPELINE_LOCK="/tmp/kpop_pipeline_global.flock"
exec 9>"$_GLOBAL_PIPELINE_LOCK"
if ! flock -n 9; then
  echo "⏭️  他のパイプラインが実行中のため、この起動はスキップします（birthday）"
  exit 0
fi

# パイプラインログ
PIPELINE_JSONL="$SCRIPT_DIR/logs/pipeline.jsonl"
mkdir -p "$SCRIPT_DIR/logs"
RUN_ID=$(date '+%Y%m%d_%H%M%S')
TODAY=$(date '+%Y年%m月%d日')
TODAY_ISO=$(date '+%Y-%m-%d')

log_step() {
  local step="$1" status="$2" msg="${3:-}"
  local ts
  ts=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
  msg="${msg//\\/\\\\}"
  msg="${msg//\"/\\\"}"
  printf '{"timestamp":"%s","run_id":"%s","pipeline":"birthday","step":"%s","status":"%s","message":"%s"}\n' \
    "$ts" "$RUN_ID" "$step" "$status" "$msg" >> "$PIPELINE_JSONL"
}

echo "========================================"
echo " K-POP誕生日記事パイプライン"
echo " 実行日: $TODAY"
echo " RUN_ID: $RUN_ID"
echo "========================================"

# --check-week モードの場合はチェックのみ
if [[ "$1" == "--check-week" ]] || [[ "$1" == "--check-month" ]]; then
  python3 "$SCRIPT_DIR/lib/birthday_article_generator.py" "$1"
  exit 0
fi

ARGS="$@"
if [[ -z "$ARGS" ]]; then
  ARGS="--include-tomorrow"
fi

log_step "start" "ok" "args=$ARGS"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [1] 誕生日チェック（該当者がいなければ早期終了）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo ""
echo "[1/4] 誕生日チェック..."

BIRTHDAY_CHECK=$(python3 -c "
from datetime import date, timedelta
import json
from pathlib import Path

config = json.loads(Path('$SCRIPT_DIR/config/artist_master.json').read_text())
today = date.fromisoformat('$TODAY_ISO')
dates = [today, today + timedelta(days=1)]
count = 0
for d in dates:
    mm_dd = d.strftime('%m-%d')
    for a in config['artists']:
        for m in a.get('members', []):
            if m.get('birthday', '')[5:] == mm_dd:
                count += 1
                print(f'  {d.strftime(\"%m/%d\")} {m[\"name\"]:15s} ({a[\"name_en\"]})')
print(f'TOTAL:{count}')
" 2>/dev/null)

BDAY_COUNT=$(echo "$BIRTHDAY_CHECK" | grep "^TOTAL:" | cut -d: -f2)

if [[ "$BDAY_COUNT" == "0" ]]; then
  echo "  本日・明日の誕生日該当なし → パイプライン終了"
  log_step "check" "ok" "no_birthdays"
  exit 0
fi

echo "$BIRTHDAY_CHECK" | grep -v "^TOTAL:"
echo "  該当: ${BDAY_COUNT}名"
log_step "check" "ok" "count=$BDAY_COUNT"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [2] 記事生成・投稿
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo ""
echo "[2/4] 誕生日記事生成..."

python3 "$SCRIPT_DIR/lib/birthday_article_generator.py" $ARGS 2>&1 | tee "$SCRIPT_DIR/logs/birthday_${RUN_ID}.log"
GEN_EXIT=$?

if [[ $GEN_EXIT -ne 0 ]]; then
  echo "❌ 記事生成でエラー (exit: $GEN_EXIT)"
  log_step "generation" "error" "exit_code=$GEN_EXIT"
fi
log_step "generation" "ok"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [3] サムネイル生成
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo ""
echo "[3/4] サムネイル生成..."

# 今回生成した記事のサムネイルを生成
POSTED_TODAY=$(grep "\"action\": \"posted\"" "$SCRIPT_DIR/logs/birthday_articles.jsonl" 2>/dev/null | \
  python3 -c "
import sys, json
for line in sys.stdin:
    try:
        d = json.loads(line.strip())
        ts = d.get('timestamp', '')
        if '$TODAY_ISO' in ts:
            name = d.get('member', '')
            group = d.get('group', '')
            post_id = d.get('post_id', '')
            url = d.get('url', '')
            print(f'{post_id}|{name}({group})|{url}')
    except: pass
" 2>/dev/null)

if [[ -n "$POSTED_TODAY" ]]; then
  while IFS='|' read -r post_id label post_url; do
    if [[ -n "$post_id" && "$post_id" != "None" ]]; then
      THUMB_TITLE="${label} 誕生日"
      echo "  サムネイル生成: $label"
      python3 "$SCRIPT_DIR/make_thumbnail.py" "$THUMB_TITLE" --genre birthday --title "$label 誕生日記念" 2>/dev/null

      if [[ -f "$SCRIPT_DIR/thumbnail.jpg" ]]; then
        MEDIA_RESPONSE=$(curl -s -X POST "https://www.kpopjournal.tokyo/wp-json/wp/v2/media" \
          -K "$HOME/.wp_auth" \
          -H "Content-Disposition: attachment; filename=birthday_thumb.jpg" \
          -H "Content-Type: image/jpeg" \
          --data-binary "@$SCRIPT_DIR/thumbnail.jpg")
        MEDIA_ID=$(echo "$MEDIA_RESPONSE" | python3 -c "import json,sys; print(json.load(sys.stdin).get('id',0))" 2>/dev/null || echo 0)
        if [[ -n "$MEDIA_ID" && "$MEDIA_ID" != "0" ]]; then
          curl -s -X POST "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/${post_id}" \
            -K "$HOME/.wp_auth" \
            -H "Content-Type: application/json" \
            -d "{\"featured_media\": $MEDIA_ID}" > /dev/null 2>&1
          # ALTテキスト設定
          ALT_TEXT=$(echo "$label 誕生日記念" | sed 's/[【】「」]/ /g' | head -c 100)
          curl -s -X POST "https://www.kpopjournal.tokyo/wp-json/wp/v2/media/${MEDIA_ID}" \
            -K "$HOME/.wp_auth" \
            -H "Content-Type: application/json" \
            -d "{\"alt_text\": \"$(echo "$ALT_TEXT" | sed 's/"/\\"/g')\"}" > /dev/null 2>&1
          echo "    ✅ サムネイル設定完了 (media_id=$MEDIA_ID)"
        fi
      fi
    fi
  done <<< "$POSTED_TODAY"
else
  echo "  新規投稿なし（スキップ）"
fi
log_step "thumbnails" "ok"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [4] SNS投稿（X/Twitter）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo ""
echo "[4/4] SNS投稿..."

if [[ -n "$POSTED_TODAY" ]]; then
  while IFS='|' read -r post_id label post_url; do
    if [[ -n "$post_url" && "$post_url" != "None" ]]; then
      echo "  X投稿: $label"
      # ペルシアンでSNS拡散文を生成
      X_TEXT=$(claude --no-session-persistence -p "
以下のK-POPアーティスト誕生日記事のX(Twitter)投稿文を1つだけ生成せよ。
【記事タイトル】${label} 誕生日記念
【URL】${post_url}
【条件】
- 280文字以内
- 祝福ムード + 記事誘導
- ハッシュタグ3つ以内
- URL末尾に配置
出力: 投稿文のみ（他の説明不要）
" 2>/dev/null)

      if [[ -n "$X_TEXT" ]]; then
        _BDAY_PERSIAN=$(mktemp /tmp/bday_persian_XXXXXX.md)
        printf 'パターンA（採用推奨）\n```\n%s\n```\n' "$X_TEXT" > "$_BDAY_PERSIAN"
        bash "$SCRIPT_DIR/google_metrics/post_to_x.sh" "$label" "$post_url" "$_BDAY_PERSIAN" 2>&1 || echo "    ⚠️ X投稿スキップ"
        rm -f "$_BDAY_PERSIAN"
      fi

      # Google/Bing インデックス登録
      bash "$SCRIPT_DIR/google_metrics/request_index.sh" "$post_url" 2>&1 || echo "    ⚠️ Google インデックススキップ"
      bash "$SCRIPT_DIR/google_metrics/request_bing_index.sh" "$post_url" 2>&1 || echo "    ⚠️ Bing インデックススキップ"
    fi
  done <<< "$POSTED_TODAY"
else
  echo "  新規投稿なし（スキップ）"
fi
log_step "sns" "ok"

echo ""
echo "========================================"
echo " ✅ 誕生日記事パイプライン完了"
echo " ログ: logs/birthday_${RUN_ID}.log"
echo "========================================"
log_step "complete" "ok"
