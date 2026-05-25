#!/usr/bin/env bash
# webp_convert.sh — 本番 uploads 配下の PNG/JPG に WebP 併設版を生成する(原本は削除しない)。
#   Lighthouse "Serve images in next-gen formats"(本番home実測で 373KiB節約、全homeで66%/2MB削減)対策。
#   .webp は元ファイルと同じパス(拡張子だけ .webp)に置き、nginx 側で Accept: image/webp の時に
#   透過配信する(webp_nginx.conf 参照)。HTML/テーマ変更は不要。
#   冪等: 既存 .webp が元より新しければスキップ。原本(png/jpg)は一切変更しない。
#   owner 実行: sudo -u www-data bash tools/perf/webp_convert.sh [UPLOADS_DIR]
set -euo pipefail
UPLOADS="${1:-/var/www/wp_stg/wp-content/uploads}"
Q=82

command -v cwebp >/dev/null 2>&1 || { echo "cwebp 未導入。'sudo apt-get install webp' か python3+Pillow 版を使ってください。"; PY=1; }

conv=0; skip=0; err=0
echo "================ WebP併設生成 (q=$Q) DIR=$UPLOADS ================"
while IFS= read -r -d '' f; do
  webp="${f%.*}.webp"
  # 冪等: webpが原本より新しければskip
  if [ -f "$webp" ] && [ "$webp" -nt "$f" ]; then skip=$((skip+1)); continue; fi
  if [ "${PY:-0}" = "1" ]; then
    python3 - "$f" "$webp" "$Q" <<'PYEOF'
import sys
from PIL import Image
src,dst,q=sys.argv[1],sys.argv[2],int(sys.argv[3])
try:
    Image.open(src).convert("RGB").save(dst,"WEBP",quality=q,method=6)
except Exception as e:
    print("ERR",src,e); sys.exit(1)
PYEOF
    rc=$?
  else
    cwebp -quiet -q "$Q" "$f" -o "$webp"; rc=$?
  fi
  if [ "$rc" = "0" ]; then conv=$((conv+1)); else err=$((err+1)); fi
done < <(find "$UPLOADS" -type f \( -iname '*.png' -o -iname '*.jpg' -o -iname '*.jpeg' \) -print0)

echo "  変換 $conv / skip(既存) $skip / エラー $err"
echo "  原本は無変更(.webp併設のみ)。次: webp_nginx.conf を nginx に取り込み reload。"
echo "================ 完了 ================"
