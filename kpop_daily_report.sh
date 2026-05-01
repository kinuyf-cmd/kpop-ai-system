#!/bin/bash

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# K-POP 日次レポート
# 毎日 22:00 自動実行
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

TODAY=$(date '+%Y年%m月%d日')
TODAY_KEY=$(date '+%Y%m%d')
ARCHIVE_BASE=~/kpop_archives
REPORT_DIR=~/daily_reports
mkdir -p "$REPORT_DIR"

echo "========================================"
echo " K-POP 日次レポート: $TODAY"
echo "========================================"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [1] 本日のアーカイブ集計
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo ""
echo "=== [1] 本日のパイプライン実行集計 ==="

TOTAL=0; SUCCESS=0; STOPPED=0
SPEED_OK=0; STRATEGY_OK=0; CHART_OK=0
SPEED_NG=0; STRATEGY_NG=0; CHART_NG=0
ARTICLE_LIST=""

for dir in "$ARCHIVE_BASE"/*/; do
  [[ ! -d "$dir" ]] && continue
  dir_id=$(basename "$dir")
  dir_date=$(echo "$dir_id" | cut -c1-8)
  [[ "$dir_date" != "$TODAY_KEY" ]] && continue

  TOTAL=$((TOTAL + 1))
  summary="$dir/summary.txt"
  [[ ! -f "$summary" ]] && continue

  pipeline=$(grep 'パイプライン' "$summary" | sed 's/パイプライン.*: //' | tr -d ' ')
  verdict=$(grep '判定' "$summary" | head -1)
  title=$(grep 'タイトル' "$summary" | sed 's/タイトル.*: //')
  url=$(grep 'URL' "$summary" | sed 's/URL.*: //')
  chars=$(grep '文字数' "$summary" | sed 's/文字数.*: //')

  if echo "$verdict" | grep -q '投稿OK'; then
    SUCCESS=$((SUCCESS + 1))
    ARTICLE_LIST="${ARTICLE_LIST}\n  ✅ [${pipeline}] ${title}（${chars}文字）\n     ${url}"
    case "$pipeline" in
      speed)    SPEED_OK=$((SPEED_OK + 1)) ;;
      strategy) STRATEGY_OK=$((STRATEGY_OK + 1)) ;;
      chart)    CHART_OK=$((CHART_OK + 1)) ;;
    esac
  else
    STOPPED=$((STOPPED + 1))
    case "$pipeline" in
      speed)    SPEED_NG=$((SPEED_NG + 1)) ;;
      strategy) STRATEGY_NG=$((STRATEGY_NG + 1)) ;;
      chart)    CHART_NG=$((CHART_NG + 1)) ;;
    esac
  fi
done

echo "  総実行: ${TOTAL}回 | 成功: ${SUCCESS}回 | 停止: ${STOPPED}回"
echo "  速報: ✅${SPEED_OK} ❌${SPEED_NG}  戦略: ✅${STRATEGY_OK} ❌${STRATEGY_NG}  チャート: ✅${CHART_OK} ❌${CHART_NG}"

# トークンコスト集計
TOKEN_REPORT=$(python3 ~/kpop-ai-system/lib/token_report.py daily "$TODAY_KEY" --json 2>/dev/null || echo '{}')
TOKEN_TOTAL=$(echo "$TOKEN_REPORT" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(f\"{d.get('total_tokens',0):,}\")" 2>/dev/null || echo "0")
TOKEN_COST=$(echo "$TOKEN_REPORT" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(f\"${d.get('total_cost_usd',0):.4f} (約{d.get('total_cost_jpy',0):.0f}円)\")" 2>/dev/null || echo "N/A")
echo "  トークン: ${TOKEN_TOTAL} | コスト: ${TOKEN_COST}"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [2] WordPressの本日投稿を取得
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo ""
echo "=== [2] WordPress 本日投稿データ取得 ==="

WP_DATA=$(python3 - "$TODAY_KEY" <<'PYEOF'
import sys, json, os, urllib.request, base64, urllib.parse
from datetime import datetime, timezone

today_str = sys.argv[1]
today_dt = datetime.strptime(today_str, "%Y%m%d").replace(tzinfo=timezone.utc)
after  = today_dt.strftime("%Y-%m-%dT00:00:00")
before = today_dt.strftime("%Y-%m-%dT23:59:59")

auth = base64.b64encode(os.environ.get("WP_USER","kpop-bot").encode() + b":" + os.environ.get("WP_PASS","").encode()).decode()
headers = {"Authorization": "Basic " + auth}
url = ("https://www.kpopjournal.tokyo/wp-json/wp/v2/posts"
       "?per_page=50&after=" + urllib.parse.quote(after)
       + "&before=" + urllib.parse.quote(before)
       + "&orderby=date&order=desc")

try:
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=15) as res:
        posts = json.loads(res.read())
except Exception as e:
    print(f"WP取得失敗: {e}")
    sys.exit()

if not posts:
    print("本日の投稿なし")
    sys.exit()

print(f"本日のWP投稿: {len(posts)}件")
for p in posts:
    t = p.get("title", {}).get("rendered", "(不明)")
    link = p.get("link", "")
    date = p.get("date", "")[:16].replace("T", " ")
    print(f"  [{date}] {t}")
    print(f"    {link}")
PYEOF
)

echo "$WP_DATA"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [3] Claude によるレポート生成
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo ""
echo "=== [3] 日次レポート生成 ==="

REPORT=$(claude -p "
今日は${TODAY}です。
以下のデータをもとに、K-POPメディア運用の日次レポートを日本語で生成せよ。

【本日のパイプライン実行結果】
総実行: ${TOTAL}回 | 成功: ${SUCCESS}回 | 停止: ${STOPPED}回
速報パイプライン: 成功${SPEED_OK}回 / 失敗${SPEED_NG}回
戦略パイプライン: 成功${STRATEGY_OK}回 / 失敗${STRATEGY_NG}回
チャートパイプライン: 成功${CHART_OK}回 / 失敗${CHART_NG}回

【本日の投稿記事】
$(echo -e "$ARTICLE_LIST")

【WordPressデータ】
$WP_DATA

【レポート要件】
- 本日の総括（3行以内）
- 成果ハイライト（投稿数・注目記事）
- 課題・懸念点（あれば）
- 明日への一言アドバイス
- 全体を200文字以内でまとめたLINE送信用テキスト（最後に「【LINE用】」と表記してから記載）

簡潔・実用的に出力せよ。
")

echo "$REPORT"

# レポートをファイルに保存
echo "$REPORT" > "$REPORT_DIR/${TODAY_KEY}_daily.md"
echo ""
echo "  ✓ レポート保存: $REPORT_DIR/${TODAY_KEY}_daily.md"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [4] 通知送信
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo ""
echo "=== [4] 通知送信 ==="

# LINE用テキストを抽出
LINE_TEXT=$(echo "$REPORT" | sed -n '/【LINE用】/,$ p' | tail -n +2 | head -c 500)
if [[ -z "$LINE_TEXT" ]]; then
  LINE_TEXT="本日の投稿: ${SUCCESS}件成功 / ${STOPPED}件停止 | 総実行: ${TOTAL}回"
fi

# macOS通知
osascript -e "display notification \"本日の投稿: ${SUCCESS}件 / 実行: ${TOTAL}回\" with title \"K-POP 日次レポート\" subtitle \"$TODAY\"" 2>/dev/null

# LINE Notify
LINE_TOKEN_FILE=~/.kpop_line_token
if [[ -f "$LINE_TOKEN_FILE" ]]; then
  LINE_TOKEN=$(cat "$LINE_TOKEN_FILE" | tr -d '[:space:]')
  if [[ -n "$LINE_TOKEN" ]]; then
    BODY="📊 K-POP 日次レポート ${TODAY}"$'\n'"${LINE_TEXT}"
    curl -s -X POST https://notify-api.line.me/api/notify \
      -H "Authorization: Bearer ${LINE_TOKEN}" \
      --data-urlencode "message=${BODY}" > /dev/null 2>&1
    echo "  ✓ LINE通知送信"
  else
    echo "  ⚠️  LINE Token が空 → スキップ"
  fi
else
  echo "  ⚠️  ~/.kpop_line_token なし → LINE通知スキップ"
fi

# Discord Webhook（#daily-ceo-report チャネル）
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/lib/discord_channels.sh" 2>/dev/null || true
DISCORD_URL=$(get_discord_webhook "daily_ceo_report" 2>/dev/null || echo "")
if [[ -z "$DISCORD_URL" ]]; then
  DISCORD_WEBHOOK_FILE=~/.kpop_discord_webhook
  if [[ -f "$DISCORD_WEBHOOK_FILE" ]]; then
    DISCORD_URL=$(cat "$DISCORD_WEBHOOK_FILE" | tr -d '[:space:]')
  fi
fi
if [[ -n "$DISCORD_URL" ]]; then
  {
    # 投稿記事リストをDiscord用に整形
    DISCORD_ARTICLES=$(echo -e "$ARTICLE_LIST" | sed 's/^  //' | head -c 1800)

    DISCORD_JSON=$(python3 - "$TODAY" \
      "$TOTAL" "$SUCCESS" "$STOPPED" \
      "$SPEED_OK" "$SPEED_NG" \
      "$STRATEGY_OK" "$STRATEGY_NG" \
      "$CHART_OK" "$CHART_NG" \
      "$LINE_TEXT" "$DISCORD_ARTICLES" <<'PYEOF'
import sys, json

today        = sys.argv[1]
total        = sys.argv[2]
success      = sys.argv[3]
stopped      = sys.argv[4]
speed_ok     = sys.argv[5];  speed_ng     = sys.argv[6]
strategy_ok  = sys.argv[7];  strategy_ng  = sys.argv[8]
chart_ok     = sys.argv[9];  chart_ng     = sys.argv[10]
summary_text = sys.argv[11]
articles     = sys.argv[12]

color = 3066993 if int(stopped) == 0 else (15105570 if int(success) > 0 else 15158332)

fields = [
    {"name": "📊 総実行",   "value": f"`{total}回`",   "inline": True},
    {"name": "✅ 投稿成功", "value": f"`{success}件`", "inline": True},
    {"name": "❌ 停止",     "value": f"`{stopped}件`", "inline": True},
    {"name": "⚡ 速報",     "value": f"✅{speed_ok} ❌{speed_ng}",       "inline": True},
    {"name": "🧠 戦略",     "value": f"✅{strategy_ok} ❌{strategy_ng}", "inline": True},
    {"name": "📈 チャート", "value": f"✅{chart_ok} ❌{chart_ng}",       "inline": True},
]
if articles.strip():
    fields.append({"name": "📝 本日の投稿記事", "value": articles[:1024], "inline": False})
if summary_text.strip():
    fields.append({"name": "💬 サマリー", "value": summary_text[:1024], "inline": False})

print(json.dumps({
    "embeds": [{
        "title": f"📊 K-POP 日次レポート｜{today}",
        "color": color,
        "fields": fields,
        "footer": {"text": "K-POP自動運用システム"}
    }]
}))
PYEOF
)
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
      -X POST "$DISCORD_URL" \
      -H "Content-Type: application/json" \
      -d "$DISCORD_JSON")
    if [[ "$HTTP_CODE" == "204" ]]; then
      echo "  ✓ Discord通知送信"
    else
      echo "  ⚠️  Discord送信失敗 (HTTP ${HTTP_CODE})"
    fi
  else
    echo "  ⚠️  Discord Webhook URL が空 → スキップ"
  fi
else
  echo "  ⚠️  ~/.kpop_discord_webhook なし → Discord通知スキップ"
fi

echo ""
echo "========================================"
echo " ✅ 日次レポート完了"
echo " 成功: ${SUCCESS}件 / 停止: ${STOPPED}件 / 総実行: ${TOTAL}回"
echo " 保存先: $REPORT_DIR/${TODAY_KEY}_daily.md"
echo "========================================"
