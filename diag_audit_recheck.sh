#!/usr/bin/env bash
# 前回監査の数字を正しいフィルタで裏取り(read-only)。
WP="sudo -u www-data wp --path=/var/www/wp_stg"
echo "--- publish 投稿の総数(post_type=post) ---"
echo "  post(publish): $($WP post list --post_type=post --post_status=publish --format=count 2>/dev/null)"
echo "  page(publish): $($WP post list --post_type=page --post_status=publish --format=count 2>/dev/null)"
echo "--- popup category 25件の featured image 有無 ---"
nopic=0; total=0
for id in $($WP post list --post_type=post --category_name=popup --post_status=publish --field=ID 2>/dev/null); do
  total=$((total+1))
  t=$($WP post meta get "$id" _thumbnail_id 2>/dev/null || echo "")
  [ -z "$t" ] && nopic=$((nopic+1))
done
echo "  popup記事 $total件 中 featured無: $nopic 件"
echo "--- 通常記事(popup以外)の featured 有無サンプル ---"
for id in $($WP post list --post_type=post --post_status=publish --field=ID --posts_per_page=10 2>/dev/null); do
  t=$($WP post meta get "$id" _thumbnail_id 2>/dev/null || echo "なし")
  echo "    post $id: thumbnail=$t"
done
