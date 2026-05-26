#!/usr/bin/env bash
# ライター紹介ページ(writer CPT)を stg テーマへ反映する。
# テーマディレクトリは www-data 所有のため sudo が必要 = **オーナー実行**。
#
# 反映物:
#   - functions.php             (末尾に inc/writer-profiles.php の require を追加)
#   - inc/writer-profiles.php   (新規: CPT登録+JSON駆動描画+CSS)
#   - data/x_writer_personas.json (新規: テーマ同梱のライター定義)
#
# 使い方(オーナー):  sudo bash scripts/deploy_writer_pages_stg.sh
# 本番反映は stg 検証 OK 後、TARGET を本番テーマパスに変えて再実行。
set -euo pipefail

SRC="/home/aiuser/kpop-ai-system/themes/generatepress-kpop"
TARGET="${TARGET:-/var/www/wp_stg/wp-content/themes/generatepress-kpop}"
OWNER="www-data:www-data"

echo "== writer pages deploy =="
echo "SRC:    $SRC"
echo "TARGET: $TARGET"

if [ ! -d "$TARGET" ]; then
  echo "ERROR: target theme dir not found: $TARGET" >&2
  exit 1
fi

# PHP 構文チェック(壊れたまま反映しない)
php -l "$SRC/functions.php" >/dev/null
php -l "$SRC/inc/writer-profiles.php" >/dev/null

# バックアップ(functions.php のみ上書きのため)
ts=$(date +%Y%m%d_%H%M%S)
cp -a "$TARGET/functions.php" "$TARGET/functions.php.bak.$ts"
echo "backup: functions.php.bak.$ts"

# 反映
install -d -o www-data -g www-data "$TARGET/inc" "$TARGET/data"
cp -a "$SRC/functions.php"            "$TARGET/functions.php"
cp -a "$SRC/inc/writer-profiles.php"  "$TARGET/inc/writer-profiles.php"
cp -a "$SRC/data/x_writer_personas.json" "$TARGET/data/x_writer_personas.json"
chown -R "$OWNER" "$TARGET/inc" "$TARGET/data" "$TARGET/functions.php"
echo "copied 3 files + chown $OWNER"

# rewrite flush(/writers/ の 404 防止)。wp-cli パスは環境に合わせて。
WP_CLI="${WP_CLI:-wp}"
WP_PATH="${WP_PATH:-/var/www/wp_stg}"
if command -v "$WP_CLI" >/dev/null 2>&1; then
  sudo -u www-data "$WP_CLI" --path="$WP_PATH" rewrite flush || true
  echo "rewrite flushed"
  echo "-- writer 投稿(器)は init 時に自動シード。確認: --"
  sudo -u www-data "$WP_CLI" --path="$WP_PATH" post list --post_type=writer --fields=ID,post_name,post_status 2>/dev/null || true
else
  echo "NOTE: wp-cli 未検出。管理画面 設定>パーマリンク を保存して flush してください。"
fi

echo "== done. /writers/ と /writers/yui/ を確認してください =="
