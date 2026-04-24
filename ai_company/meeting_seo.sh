#!/bin/bash
# ============================================================
# SEO分析部 週次会議（毎週木曜 22:00 JST）
# 部署長: ラプラス
# 参加: ラプラス、メタモン、ミミッキュ、バタフリー、カイリュー、イルミーゼ
# 主旨: 検索流入・キーワード・競合分析・CVR改善
# ============================================================
set -uo pipefail

BASE="$(cd "$(dirname "$0")/.." && pwd)"
source "$BASE/lib/meeting_helper.sh"
source "$BASE/env_loader.sh" 2>/dev/null || true

REPORTS="$HOME/ai_company/reports/seo/$(date '+%Y%m%d')"
mkdir -p "$REPORTS"

TODAY=$(date '+%Y年%m月%d日')
echo "=== SEO分析部会議 開始: $TODAY ==="

# Phase 4: 前週KPI自動注入
WEEKLY_KPI=$(weekly_kpi_brief seo)

SEO_DATA=$(python3 - <<'PYEOF'
import json
from pathlib import Path
base = Path("/home/aiuser/kpop-ai-system")
ym = base / "google_metrics/metrics_yesterday.json"
if ym.exists():
    try:
        d = json.loads(ym.read_text())
        print("【昨日のGSC指標】")
        print(f"  表示回数: {d.get('impressions','?')} / クリック: {d.get('clicks','?')}")
        print(f"  CTR: {d.get('ctr','?')} / 平均順位: {d.get('position','?')}")
    except Exception as e:
        print(f"metrics_yesterday 読込失敗: {e}")
else:
    print("【GSC指標】データなし")

# 直近7日の低CTR記事
low_ctr = base / "logs/low_ctr_articles.jsonl"
if low_ctr.exists():
    lines = low_ctr.read_text(errors="replace").splitlines()[-10:]
    print(f"\n【直近低CTR記事{len(lines)}件】")
    for line in lines:
        try:
            r = json.loads(line.strip())
            print(f"  [{r.get('ctr','?')}] {r.get('title','')[:50]}")
        except: pass
PYEOF
)

safe_claude lapras "
あなたはラプラス（CMO・SEO分析部長・SNS広報部管掌）です。SEO分析部会議を主催し、CMO視点でマーケティング戦略を統括してください。

【SEOデータ】
${SEO_DATA}

${WEEKLY_KPI}

出力形式：
【担当】lapras（部署長）
【週次SEO状況】（表示回数・CTR・順位のトレンド）
【狙い目キーワードTOP5】（検索ボリューム＋競合度）
【低CTR記事の再生プラン】
【部下への指示】（metamon/mimikyu/butterfreeへ）
" "$REPORTS/lapras.md"

safe_claude metamon_kpop "
あなたはメタモン（SEOリライト責任者）です。
低CTR記事のリライト優先リストを提示してください。

出力形式：
【担当】metamon
【リライト優先TOP5】
【タイトル改善方針】
" "$REPORTS/metamon.md"

safe_claude mimikyu "
あなたはミミッキュ（競合分析）です。
競合サイトの新規記事パターンを報告してください。

出力形式：
【担当】mimikyu
【競合の新動向】
【差別化余地】
" "$REPORTS/mimikyu.md"

safe_claude kairyu_kpop "
あなたはカイリュー（CVR・回遊最適化）です。
SEO流入後のCVR・回遊を報告してください。

出力形式：
【担当】kairyu
【直近CVR】
【離脱多発箇所】
【改善案】
" "$REPORTS/kairyu.md"

# 統合レポート
{
  echo "# SEO分析部 週次レポート ${TODAY}"
  echo "${SEO_DATA}"
  echo ""
  for f in lapras metamon mimikyu kairyu; do
    echo "## ${f}"
    cat "$REPORTS/${f}.md" 2>/dev/null
    echo ""
  done
} > "$REPORTS/seo_summary.md"

MSG="🔍 SEO分析部会議 ($TODAY)

$(cat "$REPORTS/lapras.md" | head -c 1500)"

meeting_discord_post "seo_insights" "$MSG"

echo "✅ SEO分析部会議 完了: $REPORTS"
