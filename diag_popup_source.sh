#!/usr/bin/env bash
# popup記事の出典URL所在を調査(read-only)。
WP="sudo -u www-data wp --path=/var/www/wp_stg"
echo "--- featured無 popup の最初の1件を特定 ---"
PID=""
for id in $($WP post list --post_type=post --category_name=popup --post_status=publish --field=ID 2>/dev/null); do
  t=$($WP post meta get "$id" _thumbnail_id 2>/dev/null || echo "")
  [ -z "$t" ] && { PID=$id; break; }
done
echo "  対象 popup ID=$PID"
echo "--- メタ一覧(出典/source/url 系を探す) ---"
$WP post meta list "$PID" --fields=meta_key,meta_value 2>/dev/null | grep -iE 'source|url|出典|reference|cite|origin|link|og' | head -20
echo "  (上が空なら本文中の出典リンクを見る)"
echo "--- 本文中の出典リンク/引用元(末尾の引用元 a href) ---"
$WP post get "$PID" --field=post_content 2>/dev/null | grep -oE 'href="https?://[^"]*"' | grep -viE 'kpopjournal' | head -8
echo "--- 全メタキー(出典がどのキーか全体把握) ---"
$WP post meta list "$PID" --fields=meta_key 2>/dev/null | head -30
