#!/usr/bin/env bash
# 20件 featured無 popup の真因切り分け(read-only)。
# popup_source_url(ACF)有無 / 出典og:image取得可否 / uploadsに画像残存か。
WP="sudo -u www-data wp --path=/var/www/wp_stg"
echo "=== featured無 popup の出典URL + 画像状況 ==="
n=0
for id in $($WP post list --post_type=post --category_name=popup --post_status=publish --field=ID 2>/dev/null); do
  t=$($WP post meta get "$id" _thumbnail_id 2>/dev/null || echo "")
  [ -n "$t" ] && continue   # featured有はスキップ
  n=$((n+1))
  [ $n -gt 5 ] && continue  # サンプル5件だけ詳細
  src=$($WP post meta get "$id" popup_source_url 2>/dev/null || echo "")
  title=$($WP post get "$id" --field=post_title 2>/dev/null | head -c 36)
  echo "--- popup ID=$id : $title"
  echo "    popup_source_url: ${src:-★なし}"
  # 本文の出典リンクからも(ACF空のフォールバック)
  if [ -z "$src" ]; then
    blink=$($WP post get "$id" --field=post_content 2>/dev/null | grep -oE 'kpop-citation-source[^>]*href="[^"]*"' | grep -oE 'https?://[^"]*' | head -1)
    echo "    本文出典リンク: ${blink:-なし}"
    src="$blink"
  fi
  # 出典のog:image取得可否
  if [ -n "$src" ]; then
    ogimg=$(curl -s --max-time 12 -A "Mozilla/5.0" "$src" 2>/dev/null | grep -ioE 'property="og:image" content="[^"]*"' | head -1 | grep -oE 'https?://[^"]*')
    echo "    出典og:image: ${ogimg:-取得不可}"
  fi
done
echo "(featured無 合計: 上のループで詳細5件/総20件想定)"
echo
echo "=== uploads に popup 由来画像が残存しているか(紐付け切れの可能性) ==="
echo "popup/buzzlab/seongsu を含む attachment 数:"
$WP post list --post_type=attachment --field=post_title 2>/dev/null | grep -icE 'popup|buzzlab|seongsu|meenderi|sylvanian'
echo "uploads 配下の画像総数(参考):"
$WP db query "SELECT COUNT(*) FROM wp_posts WHERE post_type='attachment';" --skip-column-names 2>/dev/null
