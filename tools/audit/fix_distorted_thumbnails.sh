#!/usr/bin/env bash
# fix_distorted_thumbnails.sh — 旧 smart_crop の小画像強制stretchで歪んでいた2記事のサムネを、
#   修正済みコードで再生成した比率保持版(thumb_regen/)に差し替える。
#   boynextdoor-riize-kstyle-party (post 1464): 出典650x433→16:9クリーンcrop
#   rin-6-months-comeback-new-song-ai-joa (post 1411): 出典530x742ポスター→fit+pad(歪みゼロ)
#   方式: 新画像を media import → featured(_thumbnail_id)差し替え。冪等。直接渡しのみ。
#   owner 実行: sudo -u www-data bash tools/audit/fix_distorted_thumbnails.sh
set -uo pipefail
WP="wp --path=/var/www/wp_stg"
DIR="$(cd "$(dirname "$0")" && pwd)/thumb_regen"
is_num(){ [[ "$1" =~ ^[0-9]+$ ]]; }

# slug : 画像ファイル
declare -A MAP=(
  [boynextdoor-riize-kstyle-party]="$DIR/boynextdoor_new.jpg"
  [rin-6-months-comeback-new-song-ai-joa]="$DIR/rin_new.jpg"
)

echo "================ 歪みサムネ差し替え(2記事)================"
for slug in "${!MAP[@]}"; do
  f="${MAP[$slug]}"
  pid="$($WP post list --post_type=post --name="$slug" --field=ID 2>/dev/null | head -1)"
  [ -z "$pid" ] && { echo "  [skip] slug未検出: $slug"; continue; }
  [ -f "$f" ]   || { echo "  [skip] 画像なし: $f"; continue; }
  old="$($WP post meta get "$pid" _thumbnail_id 2>/dev/null || true)"
  att="$($WP media import "$f" --porcelain 2>/dev/null)"
  if ! is_num "$att"; then echo "  [FAIL] $slug: media import失敗"; continue; fi
  $WP post meta update "$pid" _thumbnail_id "$att" >/dev/null
  echo "  [ok] $slug (post=$pid) 旧featured=$old → 新=$att"
done

echo ""
echo "================ 検証 ================"
for slug in "${!MAP[@]}"; do
  pid="$($WP post list --post_type=post --name="$slug" --field=ID 2>/dev/null | head -1)"
  tid="$($WP post meta get "$pid" _thumbnail_id 2>/dev/null || true)"
  guid="$($WP post get "$tid" --field=guid 2>/dev/null || true)"
  echo "  $slug → featured=$tid ($(basename "$guid"))"
done
echo "================ 完了 ================"
