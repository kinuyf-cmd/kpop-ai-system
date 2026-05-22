#!/usr/bin/env bash
# POST-LAUNCH AUDIT 用 read-only wp-cli 調査(変更なし)。
# 実行: sudo bash audit_wpcli_readonly.sh
set -uo pipefail
WP="sudo -u www-data wp --path=/var/www/wp_stg"

echo "===== 項目2: site_icon (ファビコン本体) ====="
echo "site_icon ID: $($WP option get site_icon 2>/dev/null || echo '(未設定)')"
sid=$($WP option get site_icon 2>/dev/null || true)
[ -n "${sid:-}" ] && [ "$sid" != "0" ] && echo "  icon URL: $($WP post get "$sid" --field=guid 2>/dev/null)"

echo
echo "===== 項目1: popup CPT のサムネ有無 ====="
echo "popup 投稿一覧(publish):"
$WP post list --post_type=popup --post_status=publish --fields=ID,post_title --format=table 2>/dev/null | head -30
echo "--- 各 popup の _thumbnail_id ---"
for id in $($WP post list --post_type=popup --post_status=publish --field=ID 2>/dev/null); do
  t=$($WP post meta get "$id" _thumbnail_id 2>/dev/null || echo "")
  echo "  popup $id: thumbnail=${t:-なし}"
done

echo
echo "===== 項目3補足: 投稿総数とメタ充足(全公開記事のmeta description有無) ====="
echo "publish 記事数: $($WP post list --post_type=post --post_status=publish --format=count 2>/dev/null)"
echo "AIOSEO meta description 欠落記事(_aioseo_description 空):"
miss=0
for id in $($WP post list --post_type=post --post_status=publish --field=ID 2>/dev/null); do
  d=$($WP post meta get "$id" _aioseo_description 2>/dev/null || echo "")
  [ -z "$d" ] && { echo "  ID $id: meta desc なし"; miss=$((miss+1)); }
done
echo "  欠落合計: $miss 件"

echo
echo "===== 項目5補足: KPI 朝バッチが拾う投稿数(本日) ====="
echo "本日(2026-05-22)公開記事: $($WP post list --post_type=post --post_status=publish --after='2026-05-22 00:00' --format=count 2>/dev/null)"
