#!/bin/bash
# publish_rate_alert.sh — 公開率<30%でDiscord urgent通知 (2026-05-28 G対応)
#
# 過去6時間の auto_article_processed.jsonl を集計し、公開率(<30%)時にアラート。
# CTA混入汚染や新たな品質ゲート過剰など、朝ブリーフ前に気付けるよう自走させる。
#
# cron推奨: 3時間ごと (0 */3 * * *)

set -euo pipefail
cd "$(dirname "$0")/.."

THRESHOLD=30
HOURS=6

read -r TOTAL SUCCESS RATE <<< "$(HOURS="$HOURS" python3 - <<'EOF'
import json, os
from datetime import datetime, timedelta
hours = int(os.environ.get('HOURS', '6'))
cutoff = datetime.now() - timedelta(hours=hours)
total = succ = 0
with open('data/auto_article_processed.jsonl') as f:
    for line in f:
        try: r = json.loads(line)
        except: continue
        ts = r.get('ts','')
        try: t = datetime.fromisoformat(ts)
        except: continue
        if t < cutoff: continue
        k = r.get('kind','')
        if k in ('breaking','original'): succ += 1; total += 1
        elif k == 'breaking_blocked': total += 1
rate = (100*succ//total) if total else 100
print(total, succ, rate)
EOF
)"

# サンプル不足時はskip(夜間/早朝)
if [ "$TOTAL" -lt 10 ]; then
  exit 0
fi

if [ "$RATE" -ge "$THRESHOLD" ]; then
  exit 0
fi

source lib/discord_channels.sh 2>/dev/null || true
# 2026-07-15: 未定義キー "alerts" (config に不在→daily_ceo にフォールバック) を廃し、
# 公開率低下は緊急枠 urgent_errors へ直接送る。
WEBHOOK=$(get_discord_webhook "urgent_errors" 2>/dev/null || echo "")

if [ -z "$WEBHOOK" ]; then
  echo "WARN: webhook未設定で公開率${RATE}%(${SUCCESS}/${TOTAL})のアラートを送信できません" >&2
  exit 0
fi

MSG=$(cat <<EOF
{"content":"🚨 **公開率低下アラート** (直近${HOURS}h)\n公開率 **${RATE}%** (${SUCCESS}/${TOTAL}) — 閾値${THRESHOLD}%を下回りました。\nfactcheck cache汚染/ゲート過剰/ソース品質低下を確認してください。"}
EOF
)

curl -sS -X POST -H "Content-Type: application/json" -d "$MSG" "$WEBHOOK" >/dev/null
echo "alert sent: rate=${RATE}% (${SUCCESS}/${TOTAL})"
