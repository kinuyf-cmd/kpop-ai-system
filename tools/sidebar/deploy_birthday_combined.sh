#!/usr/bin/env bash
# deploy_birthday_combined.sh — 誕生日カード統合(2026-05-26)の widgets/ ファイルを配置。
#   ・today_birthday.php       … 統合レンダラー kpop_render_birthday_combined() を追加
#   ・sidebar_shortcodes.php   … [kpop_birthday] を統合版に / サムネ版 chart・popular
# どちらも widgets/ サブディレクトリ配下のため owner 実行が必要(無人配置不可)。
# 構文チェック→.bak退避→配置。functions.php / style.css は別途 kpop-theme-deploy 済み。
# owner 実行: sudo bash tools/sidebar/deploy_birthday_combined.sh
set -uo pipefail
THEME="/var/www/wp_stg/wp-content/themes/generatepress-kpop"
SRC="$(cd "$(dirname "$0")" && pwd)"
TS="$(date +%Y%m%d_%H%M%S)"
fail(){ echo "[FATAL] $1"; exit 1; }

for f in today_birthday.php sidebar_shortcodes.php; do
  [ -f "$SRC/$f" ] || fail "ソース欠落: $SRC/$f"
  if command -v php >/dev/null; then
    php -l "$SRC/$f" >/dev/null || fail "PHP構文NG: $f"
  fi
done

for f in today_birthday.php sidebar_shortcodes.php; do
  dst="$THEME/widgets/$f"
  [ -f "$dst" ] && cp -p "$dst" "$dst.bak.$TS"
  cp "$SRC/$f" "$dst"
  chown www-data:www-data "$dst" 2>/dev/null || true
  echo "[OK] 配置: $dst  (md5=$(md5sum "$dst" | cut -d' ' -f1))"
done
echo "[done] 誕生日統合 widgets 配置完了(backup ts=$TS)"
