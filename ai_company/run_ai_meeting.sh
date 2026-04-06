#!/bin/bash
set -e

BASE="$HOME/ai_company"
REPORTS="$BASE/reports"
mkdir -p "$REPORTS"

echo "=== 1. 戦略会議 ==="

claude --dangerously-skip-permissions --agent butterfree -p "
あなたはトレンド責任者です。
今日のK-POPトレンドを5つ抽出してください。

出力形式：
【担当】butterfree
【結論】
【詳細】
【課題】
【提案】
【優先度】
" > "$REPORTS/butterfree_report.md"

claude --dangerously-skip-permissions --agent lapras -p "
あなたはSEO責任者です。
以下のレポートを読み、検索流入の観点で評価してください。

$(cat "$REPORTS/butterfree_report.md")

出力形式：
【担当】lapras
【結論】
【詳細】
【課題】
【提案】
【優先度】
" > "$REPORTS/lapras_report.md"

claude --dangerously-skip-permissions --agent mimikyu -p "
あなたは競合分析責任者です。
以下を読み、競合上の弱点と勝ち筋を出してください。

$(cat "$REPORTS/butterfree_report.md")

出力形式：
【担当】mimikyu
【結論】
【詳細】
【課題】
【提案】
【優先度】
" > "$REPORTS/mimikyu_report.md"

claude --dangerously-skip-permissions --agent jirachi_kpop -p "
あなたは未来予測責任者です。
以下を踏まえて、今後バズるテーマを予測してください。

$(cat "$REPORTS/butterfree_report.md")

出力形式：
【担当】jirachi
【結論】
【詳細】
【課題】
【提案】
【優先度】
" > "$REPORTS/jirachi_report.md"

echo "=== 2. 編集長の意思決定 ==="

claude --dangerously-skip-permissions --agent mewtwo -p "
あなたは編集長です。
以下の各部門レポートを読んで、今日の最終判断を出してください。

$(cat "$REPORTS/butterfree_report.md")

$(cat "$REPORTS/lapras_report.md")

$(cat "$REPORTS/mimikyu_report.md")

$(cat "$REPORTS/jirachi_report.md")

出力形式：
【担当】mewtwo
【今日の重要ポイントTOP3】
【今やるべきアクション（優先度付き）】
【無駄な作業・削るべきもの】
【次に伸ばすジャンル】
【異常検知】
【deoxysへの指示】
【metamonへの指示】
【meowthへの指示】
" > "$REPORTS/mewtwo_decision.md"

echo "=== 3. 制作指示を分配 ==="

python3 - << 'PY'
from pathlib import Path
base = Path.home() / "ai_company" / "reports"
decision = (base / "mewtwo_decision.md").read_text()

def extract_section(text, header):
    lines = text.splitlines()
    out = []
    capture = False
    for line in lines:
        if line.strip().startswith(header):
            capture = True
            continue
        if capture and line.startswith("【") and not line.strip().startswith(header):
            break
        if capture:
            out.append(line)
    return "\n".join(out).strip()

(base / "deoxys_task.md").write_text(extract_section(decision, "【deoxysへの指示】"))
(base / "metamon_task.md").write_text(extract_section(decision, "【metamonへの指示】"))
(base / "meowth_task.md").write_text(extract_section(decision, "【meowthへの指示】"))
print("task files created")
PY

echo "=== 4. 制作部が実行 ==="

claude --dangerously-skip-permissions --agent deoxys_kpop -p "
あなたは速報記事担当です。
以下の編集長指示に従って記事を作成してください。

$(cat "$REPORTS/deoxys_task.md")

出力形式：
1行目：タイトル
2行目以降：HTML本文
" > "$REPORTS/deoxys_output.md"

claude --dangerously-skip-permissions --agent metamon_kpop -p "
あなたはCTR改善担当です。
以下の記事をCTR重視で改善してください。

編集長指示:
$(cat "$REPORTS/metamon_task.md")

記事:
$(cat "$REPORTS/deoxys_output.md")

出力形式：
1行目：タイトル
2行目以降：HTML本文
" > "$REPORTS/metamon_output.md"

claude --dangerously-skip-permissions --agent meowth -p "
あなたは収益責任者です。
以下の記事に最適な収益導線を提案してください。

編集長指示:
$(cat "$REPORTS/meowth_task.md")

記事:
$(cat "$REPORTS/metamon_output.md")

出力形式：
【担当】meowth
【結論】
【詳細】
【課題】
【提案】
【優先度】
" > "$REPORTS/meowth_output.md"

echo "=== 5. 分析部が振り返り ==="

claude --dangerously-skip-permissions --agent porygon -p "
あなたは分析責任者です。
今日のAI会議と制作結果を見て、改善点をまとめてください。

$(cat "$REPORTS/mewtwo_decision.md")

$(cat "$REPORTS/deoxys_output.md")

$(cat "$REPORTS/metamon_output.md")

$(cat "$REPORTS/meowth_output.md")

出力形式：
【担当】porygon
【結論】
【詳細】
【課題】
【提案】
【優先度】
" > "$REPORTS/porygon_review.md"

echo "✅ AI会社会議 完了"
echo "保存先: $REPORTS"

# Discord送信（#daily-ceo-report チャネル）
MEETING_SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
source "$MEETING_SCRIPT_DIR/lib/discord_channels.sh" 2>/dev/null || true
MEETING_WEBHOOK=$(get_discord_webhook "daily_ceo_report" 2>/dev/null || echo "")
[ -z "$MEETING_WEBHOOK" ] && MEETING_WEBHOOK="${DISCORD_WEBHOOK:-}"
if [ -z "$MEETING_WEBHOOK" ] && [ -f ~/.kpop_discord_webhook ]; then
  MEETING_WEBHOOK=$(cat ~/.kpop_discord_webhook | tr -d '[:space:]')
fi

if [ -n "$MEETING_WEBHOOK" ]; then
  SUMMARY="🏢 AI日次運営会議 完了 ($(date '+%Y-%m-%d %H:%M'))"
  if [ -f "$REPORTS/porygon_review.md" ]; then
    REVIEW=$(head -c 1500 "$REPORTS/porygon_review.md")
    MSG="${SUMMARY}"$'\n\n'"${REVIEW}"
  else
    MSG="$SUMMARY"
  fi
  curl -s -o /dev/null -X POST "$MEETING_WEBHOOK" \
    -H "Content-Type: application/json" \
    -d "$(python3 -c "import json,sys; print(json.dumps({'content': sys.argv[1][:1950]}))" "$MSG")" 2>/dev/null
  echo "✅ Discord送信完了"
fi
