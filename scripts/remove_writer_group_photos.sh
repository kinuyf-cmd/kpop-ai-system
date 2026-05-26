#!/usr/bin/env bash
# 不要な「Gemini生成の全員まとめ写真」(同一画像を8回アップした attachment)を削除する。
# 各ライター投稿の featured 解除 → メディア(attachment)削除。削除前にファイルを退避。
# DB/メディアは www-data 所有のため **オーナー実行(sudo)**。
#
# 対象: writer CPT 投稿の featured image(= Gemini集合写真)。
# 事前確認済み: 本文/他記事での参照は 0 件、各 attachment は writer 投稿に1対1。
#
# 使い方(オーナー):  sudo bash scripts/remove_writer_group_photos.sh
set -euo pipefail
WP_CLI="${WP_CLI:-wp}"
WP_PATH="${WP_PATH:-/var/www/wp_stg}"
UPLOADS="${UPLOADS:-/var/www/wp_stg/wp-content/uploads}"
BACKUP="/home/aiuser/kpop-ai-system/backups/writer_group_photos_$(date +%Y%m%d_%H%M%S)"

echo "== Gemini全員まとめ写真の削除 =="
mkdir -p "$BACKUP"

# writer 投稿の featured attachment を収集
IDS=$(sudo -u www-data "$WP_CLI" --path="$WP_PATH" post list --post_type=writer --post_status=any --field=ID)
ATTACHES=()
for id in $IDS; do
  fid=$(sudo -u www-data "$WP_CLI" --path="$WP_PATH" post meta get "$id" _thumbnail_id 2>/dev/null || true)
  if [ -n "${fid:-}" ]; then
    ATTACHES+=("$fid")
    # featured 解除(ヒーローはプレースホルダに戻る)
    sudo -u www-data "$WP_CLI" --path="$WP_PATH" post meta delete "$id" _thumbnail_id >/dev/null
    echo "  writer $id: featured($fid) 解除"
  fi
done

# attachment の実ファイルを退避してから削除
for fid in "${ATTACHES[@]}"; do
  f=$(sudo -u www-data "$WP_CLI" --path="$WP_PATH" eval "echo get_attached_file($fid);" 2>/dev/null || true)
  if [ -n "${f:-}" ] && [ -f "$f" ]; then
    cp -a "$f" "$BACKUP/" 2>/dev/null || true
  fi
  # --force で完全削除(ゴミ箱を経由しない attachment)
  sudo -u www-data "$WP_CLI" --path="$WP_PATH" post delete "$fid" --force >/dev/null
  echo "  attachment $fid 削除(退避済み)"
done

echo "退避先: $BACKUP"
echo "== 完了。/writers/{key}/ がプレースホルダ表示に戻ったか確認してください =="
