#!/bin/bash
# ============================================================
# 週次改善サイクル（毎週月曜 06:30）
# ポリゴン（データ分析）→ ルギア（戦略改善）→ Discord配信
# ============================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/env_loader.sh"

TODAY=$(date '+%Y年%m月%d日')
REPORTS_DIR="$HOME/weekly_reviews"
mkdir -p "$REPORTS_DIR"
REPORT_FILE="$REPORTS_DIR/review_$(date '+%Y%m%d').md"

echo "=== 週次改善サイクル開始: $TODAY ==="

# [1] ポリゴン: パフォーマンス分析
echo "=== [1] ポリゴン: 週次パフォーマンス分析 ==="

# 直近7日間のアーカイブデータを集計
ARCHIVE_STATS=$(python3 - <<'PY'
import os, json, glob
from datetime import datetime, timedelta

base = os.path.expanduser("~/kpop_archives")
cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y%m%d")
total = 0; success = 0; stopped = 0
titles = []

for d in sorted(glob.glob(f"{base}/*/")):
    dirname = os.path.basename(d.rstrip("/"))
    if dirname[:8] < cutoff:
        continue
    total += 1
    summary = os.path.join(d, "summary.txt")
    if os.path.exists(summary):
        with open(summary) as f:
            content = f.read()
        if "投稿OK" in content:
            success += 1
            for line in content.split("\n"):
                if line.startswith("タイトル"):
                    titles.append(line.split(":", 1)[-1].strip()[:50])
        else:
            stopped += 1

rate = (success * 100 // total) if total else 0
print(f"実行回数: {total}")
print(f"成功: {success} / 停止: {stopped} / 成功率: {rate}%")
print(f"投稿記事:")
for t in titles[-10:]:
    print(f"  - {t}")
PY
)

# メトリクスファイルを読み込み
METRICS=""
if [ -f "$SCRIPT_DIR/google_metrics/metrics_yesterday.json" ]; then
  METRICS=$(cat "$SCRIPT_DIR/google_metrics/metrics_yesterday.json")
fi

PORYGON_REPORT=$(claude --agent porygon -p "
今日は${TODAY}です。直近1週間のパフォーマンスを分析せよ。

【パイプライン実行結果】
${ARCHIVE_STATS}

【アクセスデータ（直近）】
${METRICS:-データなし}

分析観点：
1. パイプライン成功率のトレンド（改善/悪化）
2. 記事テーマの偏り（速報ばかりか？カテゴリバランスは？）
3. 停止原因の傾向（どのエージェントで止まっているか）
4. PV・検索流入の傾向
5. 改善が必要なエージェントの特定
" 2>/dev/null || echo "ポリゴン分析失敗")

echo "$PORYGON_REPORT" > "$REPORTS_DIR/porygon_$(date '+%Y%m%d').md"
echo "  ✓ ポリゴン分析完了"

# [2] ルギア: 戦略改善
echo "=== [2] ルギア: 週次戦略レビュー ==="
LUGIA_REPORT=$(claude --agent lugia -p "
今日は${TODAY}です。ポリゴンの分析レポートを読み、来週の戦略を決定せよ。

【ポリゴンの分析レポート】
${PORYGON_REPORT}

来週の重点テーマ・改善すべきエージェント・やめるべきこと・強化すべきカテゴリを決定せよ。
" 2>/dev/null || echo "ルギア戦略失敗")

# レポート保存
cat > "$REPORT_FILE" << EOF
# 週次改善レポート: $TODAY

## ポリゴン分析
${PORYGON_REPORT}

---

## ルギア戦略
${LUGIA_REPORT}
EOF

echo "  ✓ ルギア戦略完了"

# [2.5] 自律改善: ルギアの指示を構造化して自動適用
echo "=== [2.5] 自律改善エンジン: ディレクティブ更新 ==="
echo "$LUGIA_REPORT" | python3 "$SCRIPT_DIR/lib/auto_improve.py" extract 2>/dev/null && {
  echo "  ✓ config/auto_directives.json 更新完了"
} || {
  echo "  ⚠️ ディレクティブ抽出スキップ"
}

# 勝ちワードも更新
python3 "$SCRIPT_DIR/lib/auto_improve.py" update-titles 2>/dev/null || true

echo "  保存先: $REPORT_FILE"

# [3] Discord配信（#weekly-board-report）
source "$SCRIPT_DIR/lib/discord_channels.sh" 2>/dev/null || true
WEBHOOK=$(get_discord_webhook "weekly_board_report" 2>/dev/null || echo "")
[ -z "$WEBHOOK" ] && WEBHOOK="${DISCORD_WEBHOOK:-}"

if [ -n "$WEBHOOK" ]; then
  SUMMARY="📊 週次改善レポート ($TODAY)\n\n"
  SUMMARY+=$(echo "$LUGIA_REPORT" | head -c 1800)
  curl -s -o /dev/null -X POST "$WEBHOOK" \
    -H "Content-Type: application/json" \
    -d "$(python3 -c "import json,sys; print(json.dumps({'content': sys.argv[1][:1950]}))" "$SUMMARY")" 2>/dev/null
  echo "  ✓ Discord送信完了"
fi

echo "=== 週次改善サイクル完了 ==="
