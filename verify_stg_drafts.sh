#!/usr/bin/env bash
# 速報DRAFT 4件(ID 398-401)を wp-cli で read-only 検証。
# 実行: sudo bash verify_stg_drafts.sh
set -euo pipefail
WP="sudo -u www-data wp --path=/var/www/wp_stg"
for id in 398 399 400 401; do
  echo "===== post $id ====="
  $WP post get "$id" --field=post_status | sed 's/^/  status: /'
  $WP post get "$id" --field=post_title  | sed 's/^/  title : /'
  # 本文の健全性: 文字数 / H2数 / 出典URL有無 / schema有無 / inline color有無
  body=$($WP post get "$id" --field=post_content)
  echo "  本文字数(HTML込): ${#body}"
  echo "  H2数            : $(grep -o '<h2>' <<<"$body" | wc -l)"
  echo "  出典soompiURL   : $(grep -c 'soompi.com/article' <<<"$body") 箇所"
  echo "  NewsArticle JSON-LD: $(grep -c 'NewsArticle' <<<"$body") 箇所"
  echo "  inline color/bg : $(grep -oE 'style="[^"]*(color|background):' <<<"$body" | wc -l) 箇所(0が正)"
  echo "  メタdesc(AIOSEO): $($WP post meta get "$id" _aioseo_description 2>/dev/null | head -c 60)..."
done
echo
echo "== 公開状態の安全確認(全てdraftであるべき) =="
$WP post list --post_status=publish --post_type=post --fields=ID,post_title --format=count 2>/dev/null | sed 's/^/  現在のpublish記事数: /'
