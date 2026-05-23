#!/usr/bin/env bash
WP="sudo -u www-data wp --path=/var/www/wp_stg"
# popup 1件の本文から kpop-citation-cta ブロックを抽出
pid=396
content=$($WP post get $pid --field=post_content 2>/dev/null)
echo "--- post_content 内の citation-cta 前後(200字) ---"
echo "$content" | grep -oE '.{80}kpop-citation-cta.{300}' | head -1
echo
echo "--- CTA を囲む要素のクラス/タグ ---"
echo "$content" | grep -oE '<[a-z]+[^>]*kpop-citation-cta[^>]*>' | head -2
echo "--- 本文末尾(CTA が末尾か、後に何かあるか)---"
echo "$content" | tail -c 600
