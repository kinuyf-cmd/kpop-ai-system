#!/bin/bash
set -e

HOUR=$(date '+%H')
TODAY_JP=$(date '+%Y年%m月%d日')

# 時間帯別コンテンツ指示
if [ "$HOUR" -ge 6 ] && [ "$HOUR" -lt 9 ]; then
  CONTENT_FOCUS="美容・スキンケア・韓国コスメ系のSEO記事（朝の検索需要が高い）"
  CONTENT_TYPE="beauty"
elif [ "$HOUR" -ge 9 ] && [ "$HOUR" -lt 12 ]; then
  CONTENT_FOCUS="K-POP最新速報・カムバック・ツアー情報"
  CONTENT_TYPE="breaking"
elif [ "$HOUR" -ge 12 ] && [ "$HOUR" -lt 15 ]; then
  CONTENT_FOCUS="チャート・ランキング・音楽番組結果"
  CONTENT_TYPE="chart"
elif [ "$HOUR" -ge 15 ] && [ "$HOUR" -lt 18 ]; then
  CONTENT_FOCUS="K-POP速報・アーティスト最新ニュース"
  CONTENT_TYPE="breaking"
elif [ "$HOUR" -ge 18 ] && [ "$HOUR" -lt 21 ]; then
  CONTENT_FOCUS="韓国ドラマ・配信視聴ガイド・旅行・ソウル情報"
  CONTENT_TYPE="drama_travel"
else
  CONTENT_FOCUS="K-POP深夜速報・グローバルニュース"
  CONTENT_TYPE="breaking"
fi

echo "[$HOUR時] コンテンツタイプ: $CONTENT_TYPE ($CONTENT_FOCUS)"

# トレンド取得
TRENDS_JSON=$(python3 ~/google_metrics/fetch_trends.py 2>/dev/null || echo '{"combined":[]}')
TREND_KEYWORDS=$(echo "$TRENDS_JSON" | python3 -c "
import json, sys
d = json.load(sys.stdin)
kw = d.get('combined', [])
print(', '.join(kw[:8]) if kw else 'なし')
")

cd ~ && claude --allowedTools WebSearch --agent deoxys_kpop -p "
今日は${TODAY_JP}です。

【今の時間帯に合わせたコンテンツ方針】
$CONTENT_FOCUS

【今日のトレンドキーワード（参考）】
$TREND_KEYWORDS

上記の方針とトレンドを踏まえて、今最も需要があるK-POP記事を1本書いてください。

【出力形式・絶対厳守】
1行目：タイトル文字列のみ
2行目：空行
3行目以降：<h2>から始まるHTML本文のみ
末尾に「※本記事は${TODAY_JP}時点の情報です」を明記
" > reports/0_breaking.md && bash ~/kpop_pipeline.sh 2>&1 | tail -10
