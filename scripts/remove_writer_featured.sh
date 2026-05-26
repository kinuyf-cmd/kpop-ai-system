#!/usr/bin/env bash
# ライター個別ページのヒーロー画像(featured image)を外す。
# wp-admin から各 writer 投稿に設定された「全員まとめ写真」を解除し、
# ヒーローをイニシャル+カラーのプレースホルダ表示に戻す。
# テーマ/DB は www-data 所有のため **オーナー実行(sudo)**。
#
# 使い方(オーナー):  sudo bash scripts/remove_writer_featured.sh
set -euo pipefail
WP_CLI="${WP_CLI:-wp}"
WP_PATH="${WP_PATH:-/var/www/wp_stg}"

echo "== writer featured image 解除 =="
# writer CPT の全投稿 ID を取得
IDS=$(sudo -u www-data "$WP_CLI" --path="$WP_PATH" post list --post_type=writer --post_status=any --field=ID)
for id in $IDS; do
  name=$(sudo -u www-data "$WP_CLI" --path="$WP_PATH" post get "$id" --field=post_title 2>/dev/null || echo "?")
  if sudo -u www-data "$WP_CLI" --path="$WP_PATH" post meta get "$id" _thumbnail_id >/dev/null 2>&1; then
    sudo -u www-data "$WP_CLI" --path="$WP_PATH" post meta delete "$id" _thumbnail_id
    echo "  ID $id ($name): featured 解除"
  else
    echo "  ID $id ($name): 元から未設定"
  fi
done
echo "== 完了。/writers/{key}/ がプレースホルダ表示に戻ったか確認してください =="
