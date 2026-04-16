#!/bin/bash
# ============================================================
# 経営企画部 週次会議（毎週水曜 22:00 JST）
# 部署長: ルギア
# 参加: ルギア、ポリゴン
# 主旨: 週中KPIレビュー・パフォーマンス分析・経営判断支援
# ============================================================
set -uo pipefail

BASE="$(cd "$(dirname "$0")/.." && pwd)"
source "$BASE/lib/meeting_helper.sh"
source "$BASE/env_loader.sh" 2>/dev/null || true

REPORTS="$HOME/ai_company/reports/analytics/$(date '+%Y%m%d')"
mkdir -p "$REPORTS"

TODAY=$(date '+%Y年%m月%d日')
echo "=== 経営企画部会議 開始: $TODAY ==="

# 直近7日の勝率・CTR・刺さり
ANALYTICS_DATA=$(python3 - <<'PYEOF'
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone
JST = timezone(timedelta(hours=9))
now = datetime.now(JST)
cutoff = now - timedelta(days=7)
base = Path("/home/aiuser/kpop-ai-system/logs")

# title_performance
perf = base / "title_performance.jsonl"
wins = losses = 0
if perf.exists():
    for line in perf.read_text(errors="replace").splitlines():
        try:
            r = json.loads(line.strip())
            if r.get("result") == "win": wins += 1
            elif r.get("result") == "lose": losses += 1
        except: pass
total = wins + losses
wr = f"{wins/total*100:.0f}%" if total else "N/A"

# 刺さり品質（gardevoir）
hook = base / "hook_scores.jsonl"
hook_scores = []
if hook.exists():
    for line in hook.read_text(errors="replace").splitlines()[-50:]:
        try:
            r = json.loads(line.strip())
            hook_scores.append(r.get("score", 0))
        except: pass
avg_hook = sum(hook_scores)/len(hook_scores) if hook_scores else 0

print(f"【タイトル勝率（直近7日）】win {wins} / lose {losses} / 勝率 {wr}")
print(f"【刺さりスコア（直近50件平均）】{avg_hook:.2f} / 10")
print(f"【刺さりスコア分布】最高 {max(hook_scores) if hook_scores else 0} / 最低 {min(hook_scores) if hook_scores else 0}")
PYEOF
)

safe_claude porygon "
あなたはポリゴン（データ分析）です。経営企画部会議で週中KPIレビューしてください。

【分析データ】
${ANALYTICS_DATA}

出力形式：
【担当】porygon
【KPIトレンド】（勝率・CTR・PV）
【ボトルネックTOP3】
【来週検証すべき仮説】
" "$REPORTS/porygon.md"

safe_claude wobbuffet "
あなたはソーナンス（読者ニーズ分析）です。
直近の読者行動（検索クエリ・滞在時間・離脱）からニーズ変化を報告してください。

出力形式：
【担当】wobbuffet
【ニーズ変化】
【未カバーの読者ニーズ】
" "$REPORTS/wobbuffet.md"

safe_claude gardevoir_hook_critic "
あなたはサーナイト（刺さり品質ゲート）です。
直近のタイトル刺さり品質トレンドを報告してください。

出力形式：
【担当】gardevoir
【刺さりスコア傾向】
【低スコア原因】
【改善案】
" "$REPORTS/gardevoir.md"

safe_claude lugia "
あなたはルギア（COO・経営企画部長）です。経営企画部の知見からCOO視点で来週の戦略提案を作成してください。

【ポリゴン】
$(cat "$REPORTS/porygon.md")

【ソーナンス】
$(cat "$REPORTS/wobbuffet.md")

【サーナイト】
$(cat "$REPORTS/gardevoir.md")

出力形式：
【担当】lugia
【戦略提案】（数字ベース）
【実行すべきA/Bテスト】
【週次改善会議（月曜）への引き継ぎ事項】
" "$REPORTS/lugia.md"

MSG="📊 経営企画部会議 ($TODAY) — 部署長: ルギア

$(cat "$REPORTS/lugia.md" | head -c 1500)"

meeting_discord_post "seo_insights" "$MSG"

echo "✅ 経営企画部会議 完了: $REPORTS"
