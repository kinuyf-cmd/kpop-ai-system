#!/bin/bash
set -e

BASE="$HOME/google_metrics"
LOG="$BASE/trends.log"
TODAY_JP=$(date '+%Y年%m月%d日')

echo "" >> "$LOG"
echo "=== $(date '+%Y-%m-%d %H:%M') ===" >> "$LOG"

# トレンド取得
TRENDS_JSON=$(python3 "$BASE/fetch_trends.py" 2>/dev/null || echo '{"combined":[]}')
TREND_KEYWORDS=$(echo "$TRENDS_JSON" | python3 -c "
import json, sys
d = json.load(sys.stdin)
keywords = d.get('combined', [])
print(', '.join(keywords[:10]) if keywords else 'なし')
")

echo "トレンドキーワード: $TREND_KEYWORDS" | tee -a "$LOG"

# トレンドを活かしてdeoxysに速報取得させる
cd ~ && claude --allowedTools WebSearch --agent deoxys_kpop -p "
今日は${TODAY_JP}です。

【今日の注目トレンドキーワード（日本）】
$TREND_KEYWORDS

上記のトレンドを参考にしながら、今最もホットなK-POP速報を1本書いてください。
トレンドキーワードが記事に自然に含まれると加点です。

【出力形式・絶対厳守】
1行目：タイトル文字列のみ
2行目：空行
3行目以降：<h2>から始まるHTML本文のみ
末尾に「※本記事は${TODAY_JP}時点の情報です」を明記
" > reports/0_breaking.md && bash ~/kpop_pipeline.sh 2>&1 | tail -10
