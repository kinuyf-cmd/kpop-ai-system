#!/usr/bin/env bash
# popup の実数を post_type/status 別に確認(read-only)。
WP="sudo -u www-data wp --path=/var/www/wp_stg"
echo "--- post_type 一覧(登録済みCPT) ---"
$WP post-type list --fields=name,label 2>/dev/null | head -20
echo "--- popup 系の件数(複数候補) ---"
for pt in popup popups popup_store kpop_popup tribe_events; do
  c=$($WP post list --post_type="$pt" --post_status=publish --format=count 2>/dev/null || echo "ERR")
  echo "  post_type=$pt publish: $c"
done
echo "--- /category/popup/ は category なのか CPT archive なのか ---"
$WP term list category --fields=term_id,name,slug,count 2>/dev/null | grep -i popup
echo "--- popup category の投稿(post_type=post & category=popup) ---"
$WP post list --post_type=post --category_name=popup --post_status=publish --format=count 2>/dev/null
