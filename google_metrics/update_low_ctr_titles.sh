#!/bin/bash
set -e

BASE="$HOME/google_metrics"
METRICS_JSON="$BASE/metrics_yesterday.json"
TMP_LOW="$BASE/low_ctr_pages.json"
TMP_OUT="$BASE/auto_title_updates.log"

WP_API="https://www.kpopjournal.tokyo/wp-json/wp/v2/posts"
WP_USER="${WP_USER:-kpop-bot}"
DISCORD_WEBHOOK="$DISCORD_WEBHOOK"

echo "" > "$TMP_OUT"

# 低CTRページ抽出
python3 "$BASE/find_low_ctr_pages.py" < "$METRICS_JSON" > "$TMP_LOW"

COUNT=$(python3 - << 'PY' "$TMP_LOW"
import json, sys
with open(sys.argv[1], "r", encoding="utf-8") as f:
    data = json.load(f)
print(len(data))
PY
)

if [ "$COUNT" -eq 0 ]; then
  echo "低CTR改善対象なし" | tee -a "$TMP_OUT"
  exit 0
fi

python3 - << 'PY' "$TMP_LOW" > /tmp/low_ctr_pages_list.txt
import json, sys
with open(sys.argv[1], "r", encoding="utf-8") as f:
    data = json.load(f)
for item in data:
    print(item["page"])
PY

while IFS= read -r PAGE; do
  [ -z "$PAGE" ] && continue

  echo "=== PAGE: $PAGE ===" | tee -a "$TMP_OUT"

  # slug 抽出
  SLUG=$(python3 - << 'PY' "$PAGE"
import sys
page = sys.argv[1].strip()
page = page.rstrip("/")
slug = page.split("/")[-1]
print(slug)
PY
)

  # WPから投稿取得
  POST_JSON=$(curl -s -K "$HOME/.wp_auth" "$WP_API?slug=$SLUG")
  POST_ID=$(python3 - << 'PY' "$POST_JSON"
import sys, json
data = json.loads(sys.argv[1])
if isinstance(data, list) and len(data) > 0:
    print(data[0].get("id",""))
else:
    print("")
PY
)

  OLD_TITLE=$(python3 - << 'PY' "$POST_JSON"
import sys, json
data = json.loads(sys.argv[1])
if isinstance(data, list) and len(data) > 0:
    print(data[0].get("title",{}).get("rendered",""))
else:
    print("")
PY
)

  if [ -z "$POST_ID" ] || [ -z "$OLD_TITLE" ]; then
    echo "投稿取得失敗: $PAGE" | tee -a "$TMP_OUT"
    continue
  fi

  # 新タイトル生成（2026-04-16 Round8: 必須4要素を明記して score_title_ctr.py の8点以上狙い）
  NEW_TITLE=$(claude -p "
あなたはK-POPメディアのCTR改善担当です。既存タイトルを CTR が上がる形に書き換えよ。

【4つの必須要素 — すべて1つのタイトルに含めよ】
① 数字（例: 3週連続 / 641,000 / 2026 / 15形態 / 500万人）
② 固有名詞（BTS / BLACKPINK / aespa / 番組名 / イベント名 — 元タイトルから継承OK）
③ 感情語・強ワード（衝撃 / 異常 / ついに / まさか / 完全 / 暴露 / 制覇 / 快挙 / 神 / 解禁 / 首位 から1つ）
④ 対比構造（→ / vs / から / なのに / 空白 / 復帰 / 崩壊 / 逆転 / 週連続 / 年ぶり / 一転 / 塗替 から1つ）

【プロセス】
1. 内部で3案考える
2. 4要素すべてを含む案のうち、最もクリックされやすい1案を選ぶ
3. 4要素揃う案がない場合でも、最低3要素は含めよ

【制約】
- 26〜40文字（長すぎない、短すぎない）
- 誇張や釣り表現（爆速！絶対！神回確定！など）は禁止
- 記号の乱用禁止（「！！」「？？」禁止）
- 説明文・前置き・案番号一切出力禁止
- 出力は新タイトル本体1行のみ

既存タイトル:
$OLD_TITLE
" | tail -n 1)

  if [ -z "$NEW_TITLE" ]; then
    echo "新タイトル生成失敗: $PAGE" | tee -a "$TMP_OUT"
    continue
  fi

  # 新タイトル採点
  SCORE_JSON=$(python3 "$BASE/score_title_ctr.py" "$NEW_TITLE")
  PASS=$(python3 - << 'PY' "$SCORE_JSON"
import sys, json
data = json.loads(sys.argv[1])
print("YES" if data.get("pass") else "NO")
PY
)
  SCORE=$(python3 - << 'PY' "$SCORE_JSON"
import sys, json
data = json.loads(sys.argv[1])
print(data.get("score",0))
PY
)

  # 同一タイトル回避
  if [ "$OLD_TITLE" = "$NEW_TITLE" ]; then
    echo "同一タイトルのためスキップ: $OLD_TITLE" | tee -a "$TMP_OUT"
    continue
  fi

  # スコア条件（2026-04-16 Round8: 二段階判定）
  #   score >= 8 本採用 / score >= 6 仮採用 / それ以下 reject
  TIER=$(python3 -c "import json,sys; print(json.loads(sys.argv[1]).get('tier','reject'))" "$SCORE_JSON")
  case "$TIER" in
    full)
      echo "新タイトル本採用: $NEW_TITLE (score=$SCORE tier=full)" | tee -a "$TMP_OUT"
      ;;
    provisional)
      echo "新タイトル仮採用: $NEW_TITLE (score=$SCORE tier=provisional)" | tee -a "$TMP_OUT"
      ;;
    *)
      echo "新タイトル弱いのでスキップ: $NEW_TITLE (score=$SCORE tier=reject)" | tee -a "$TMP_OUT"
      continue
      ;;
  esac

  # バックアップ保存
  echo "POST_ID=$POST_ID" >> "$TMP_OUT"
  echo "OLD_TITLE=$OLD_TITLE" >> "$TMP_OUT"
  echo "NEW_TITLE=$NEW_TITLE" >> "$TMP_OUT"

  UPDATE_JSON=$(python3 - << 'PY' "$NEW_TITLE"
import sys, json
print(json.dumps({"title": sys.argv[1]}, ensure_ascii=False))
PY
)

  RESP=$(curl -s -X POST "$WP_API/$POST_ID" \
    -K "$HOME/.wp_auth" \
    -H "Content-Type: application/json" \
    -d "$UPDATE_JSON")

  UPDATED=$(python3 - << 'PY' "$RESP"
import sys, json
try:
    data = json.loads(sys.argv[1])
    print(data.get("title",{}).get("rendered",""))
except Exception:
    print("")
PY
)

  if [ -n "$UPDATED" ]; then
    echo "更新成功: $OLD_TITLE -> $UPDATED" | tee -a "$TMP_OUT"

    # Discord通知（webhook未設定時は skip。set -e を止める）
    if [ -n "$DISCORD_WEBHOOK" ]; then
      python3 - << PY || true
import requests, json
webhook = """$DISCORD_WEBHOOK"""
msg = """✏️ タイトル自動更新\nページ: $PAGE\n旧: $OLD_TITLE\n新: $UPDATED\nスコア: $SCORE"""
try:
    if webhook:
        requests.post(webhook, json={"content": msg[:1900]}, timeout=20)
except Exception as e:
    print(f"discord notify skip: {e}")
PY
    fi
  else
    echo "更新失敗: $PAGE" | tee -a "$TMP_OUT"
  fi

done < /tmp/low_ctr_pages_list.txt
