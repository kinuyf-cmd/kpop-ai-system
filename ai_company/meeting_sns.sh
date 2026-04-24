#!/bin/bash
# ============================================================
# SNS広報部 週次会議（毎週土曜 10:00 JST）
# 部署長: ペルシアン
# 参加: ペルシアン、フリーザー
# 主旨: X(Twitter)投稿・SNS拡散・バズコンテンツ
# ============================================================
set -uo pipefail

BASE="$(cd "$(dirname "$0")/.." && pwd)"
source "$BASE/lib/meeting_helper.sh"
source "$BASE/env_loader.sh" 2>/dev/null || true

REPORTS="$HOME/ai_company/reports/sns/$(date '+%Y%m%d')"
mkdir -p "$REPORTS"

TODAY=$(date '+%Y年%m月%d日')
echo "=== SNS広報部会議 開始: $TODAY ==="

# Phase 4: 前週KPI自動注入
WEEKLY_KPI=$(weekly_kpi_brief sns)

SNS_DATA=$(python3 - <<'PYEOF'
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone
JST = timezone(timedelta(hours=9))
now = datetime.now(JST)
cutoff = now - timedelta(days=7)
base = Path("/home/aiuser/kpop-ai-system/logs")

# X投稿ログ
xlog = base / "x_post_history.jsonl"
posts = 0; successes = 0
titles = []
if xlog.exists():
    for line in xlog.read_text(errors="replace").splitlines():
        try:
            r = json.loads(line.strip())
            ts = r.get("ts","")
            try: t = datetime.fromisoformat(ts).astimezone(JST)
            except: continue
            if t < cutoff: continue
            posts += 1
            if r.get("status") == "posted":
                successes += 1
                titles.append(r.get("title","")[:50])
        except: pass

print(f"【直近7日X投稿】{posts}件 / 成功 {successes}件")
print("【投稿タイトル】")
for t in titles[-10:]:
    print(f"  - {t}")

# フェイルセーフ
xf = base / "x_failsafe.jsonl"
if xf.exists():
    events = [l for l in xf.read_text(errors="replace").splitlines() if l.strip()]
    print(f"【フェイルセーフ履歴】{len(events)}件")
PYEOF
)

safe_claude persian "
あなたはペルシアン（SNS広報部長）です。SNS広報部会議を主催してください。

【SNSデータ】
${SNS_DATA}

出力形式：
【担当】persian（部署長）
【週次X投稿サマリー】（投稿数・エンゲージメント）
【バズった投稿パターン分析】
【来週の投稿テーマ・時間帯戦略】
【部下フリーザーへの指示】
" "$REPORTS/persian.md"

safe_claude articuno "
あなたはフリーザー（SNSバズコンテンツ生成）です。
来週投稿すべきバズ候補コンテンツを3案提示してください。

出力形式：
【担当】articuno
【バズ候補TOP3】（フック文＋訴求軸）
【投稿タイミング推奨】
" "$REPORTS/articuno.md"

{
  echo "# SNS広報部 週次レポート ${TODAY}"
  echo "${SNS_DATA}"
  echo ""
  for f in persian articuno; do
    echo "## ${f}"
    cat "$REPORTS/${f}.md" 2>/dev/null
    echo ""
  done
} > "$REPORTS/sns_summary.md"

MSG="📢 SNS広報部会議 ($TODAY)

$(cat "$REPORTS/persian.md" | head -c 1500)"

meeting_discord_post "publishing_log" "$MSG"

echo "✅ SNS広報部会議 完了: $REPORTS"
