#!/bin/bash
# ============================================================
# 財務管理部 週次会議（毎週月曜 10:00 JST）
# 部署長: ニャース
# 参加: ニャース、カイリュー、ペルシアン
# 主旨: 週次収益レビュー・CVR/RPM・コスト／ROI
# ============================================================
set -uo pipefail

BASE="$(cd "$(dirname "$0")/.." && pwd)"
source "$BASE/lib/meeting_helper.sh"
source "$BASE/env_loader.sh" 2>/dev/null || true

REPORTS="$HOME/ai_company/reports/finance/$(date '+%Y%m%d')"
mkdir -p "$REPORTS"

TODAY=$(date '+%Y年%m月%d日')
echo "=== 財務部会議 開始: $TODAY ==="

# 直近7日の収益関連メトリクス
FINANCE_DATA=$(python3 - <<'PYEOF'
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone
JST = timezone(timedelta(hours=9))
now = datetime.now(JST)
cutoff = (now - timedelta(days=7)).strftime("%Y-%m-%d")
base = Path("/home/aiuser/kpop-ai-system")

# KPIポストから記事別PV/収益見込み
kpi = base / "logs/kpi_posts.jsonl"
total_pv = 0; total_posts = 0; by_cat = {}
if kpi.exists():
    for line in kpi.read_text(errors="replace").splitlines():
        try:
            r = json.loads(line.strip())
            if r.get("date","") >= cutoff:
                total_posts += 1
                pv = r.get("pv", 0) or 0
                total_pv += pv
                c = r.get("article_type", "unknown")
                by_cat[c] = by_cat.get(c, 0) + pv
        except: pass

# 昨日のGoogle Metrics
ym = base / "google_metrics/metrics_yesterday.json"
ym_data = ""
if ym.exists():
    try:
        d = json.loads(ym.read_text())
        ym_data = f"  昨日PV: {d.get('pageviews','?')} / 昨日CTR: {d.get('ctr','?')}"
    except: pass

print(f"【直近7日】投稿 {total_posts}本 / 総PV {total_pv}")
print("【カテゴリ別PV】")
for c, pv in sorted(by_cat.items(), key=lambda x: -x[1]):
    print(f"  {c}: {pv} PV")
print(f"【昨日メトリクス】")
print(ym_data if ym_data else "  データなし")
PYEOF
)

safe_claude meowth "
あなたはニャース（CFO・財務管理部長）です。財務管理部会議を主催し、CFO視点で週次収益を総括してください。

【財務データ】
${FINANCE_DATA}

出力形式：
【担当】meowth
【週次収益サマリー】（アフィリエイト＋AdSense別に推定）
【最も収益貢献したカテゴリ】
【収益未達の原因】（あれば）
【来週の打ち手TOP3】
" "$REPORTS/meowth.md"

safe_claude kairyu_kpop "
あなたはカイリュー（CVR・回遊最適化）です。
直近のCVR・滞在時間・回遊の問題点と改善案を報告してください。

出力形式：
【担当】kairyu
【CVR現状】
【離脱多発箇所】
【改善案TOP3】
" "$REPORTS/kairyu.md" || true

safe_claude persian "
あなたはペルシアン（SNS拡散・X投稿戦略）です。
X経由の流入と収益貢献を週次で評価してください。

出力形式：
【担当】persian
【Xからの流入数・CTR】
【バズった投稿パターン】
【収益観点の最適化案】
" "$REPORTS/persian.md"

# CEO（ミュウツー）承認
safe_claude mewtwo "
あなたはミュウツー（CEO）です。財務管理部の週次報告を受け、経営承認を行ってください。

${FINANCE_DATA}

【財務管理部長ニャース報告】
$(cat "$REPORTS/meowth.md")

【カイリュー報告】
$(cat "$REPORTS/kairyu.md" 2>/dev/null || echo "（報告なし）")

【ペルシアン報告】
$(cat "$REPORTS/persian.md")

出力形式：
【担当】mewtwo（CEO）
【週次P&L概況】
【収益目標達成率】（目標値に対する実績%）
【投資判断】（注力ジャンル・削減ジャンル）
【来週の財務KPI】
【オーナー報告事項】
" "$REPORTS/ceo_summary.md"

MSG="💰 財務管理部会議 ($TODAY) — 部署長: ニャース

$(cat "$REPORTS/ceo_summary.md" | head -c 1500)"

meeting_discord_post "sales_monetization" "$MSG"

echo "✅ 財務部会議 完了: $REPORTS"
