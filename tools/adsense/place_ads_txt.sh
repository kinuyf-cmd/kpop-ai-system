#!/usr/bin/env bash
# place_ads_txt.sh — AdSense の ads.txt をサイトルートに設置する。
#   内容: google.com, pub-5968839599715792, DIRECT, f08c47fec0942fa0(本番稼働中のca-pub-と一致確認済)。
#   既存 ads.txt は無し(本番で404確認済)→ 新規作成。
#   nginx は location / の try_files $uri が先頭=物理ファイルを WP より先に静的配信するため、
#   ルートに置くだけで /ads.txt が配信される(追加設定不要)。
#   owner 実行: sudo bash tools/adsense/place_ads_txt.sh
set -uo pipefail
ROOT="/var/www/wp_stg"
SRC="$(cd "$(dirname "$0")" && pwd)/ads.txt"
DST="$ROOT/ads.txt"

[ -f "$SRC" ] || { echo "[FATAL] ソース ads.txt が無い: $SRC"; exit 1; }
[ -d "$ROOT" ] || { echo "[FATAL] サイトルートが無い: $ROOT"; exit 1; }

echo "================ ads.txt 設置 ================"
if [ -f "$DST" ]; then
  echo "  既存 ads.txt あり → 退避バックアップ"
  cp "$DST" "$DST.bak.$(date +%s)"
  # 既存に同じ行が無ければ追記(Google指示: 既存があれば貼り付け=追記)
  if grep -q "pub-5968839599715792" "$DST"; then
    echo "  既に pub-5968839599715792 の行あり → 変更なし(冪等)"
  else
    cat "$SRC" >> "$DST"; echo "  既存に追記しました"
  fi
else
  cp "$SRC" "$DST"; echo "  新規作成: $DST"
fi
# WordPress(www-data)が配信できるよう所有権・パーミッション
chown www-data:www-data "$DST" 2>/dev/null || true
chmod 644 "$DST"

echo ""
echo "================ 検証 ================"
echo "--- ファイル内容 ---"; cat "$DST"
echo "--- 配信確認(静的に200/text/plainで返るか)---"
sleep 1
curl -s -o /dev/null -w "  https://www.kpopjournal.tokyo/ads.txt → HTTP %{http_code} / %{content_type}\n" "https://www.kpopjournal.tokyo/ads.txt"
echo "  期待: HTTP 200 / text/plain。404なら nginx が静的配信していない(要 location 確認)。"
echo "================ 完了 ================"
