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

read -r TOTAL SUCCESS RATE <<< "$(python3 - <<EOF
import json
from datetime import datetime, timedelta
cutoff = datetime.now() - timedelta(hours=$HOURS)
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
WEBHOOK=$(get_discord_webhook "alerts" 2>/dev/null || get_discord_webhook "daily_ceo_report" 2>/dev/null || echo "")

if [ -z "$WEBHOOK" ]; then
  echo "WARN: webhook未設定で公開率${RATE}%(${SUCCESS}/${TOTAL})のアラートを送信できません" >&2
  exit 0
fi

MSG=$(cat <<EOF
{"content":"🚨 **公開率低下アラート** (直近${HOURS}h)\n公開率 **${RATE}%** (${SUCCESS}/${TOTAL}) — 閾値${THRESHOLD}%を下回りました。\nfactcheck cache汚染/ゲート過剰/ソース品質低下を確認してください。\n調査: \`python3 -c \\\"import json,collections; c=collections.Counter();\\\"\` で reason 集計"}
EOF
)

curl -sS -X POST -H "Content-Type: application/json" -d "$MSG" "$WEBHOOK" >/dev/null
echo "alert sent: rate=${RATE}% (${SUCCESS}/${TOTAL})"
