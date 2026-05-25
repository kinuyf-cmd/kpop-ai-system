#!/usr/bin/env bash
# deploy_shortcodes.sh — 誕生日/イベント枠をトップ等でも出すショートコードを有効化。
#   [kpop_birthday] [kpop_events] [kpop_birthday_tomorrow] を登録し、Custom HTML widget で
#   ショートコード実行を有効化(widget_text/widget_custom_html_content に do_shortcode)。
#   配置(トップのサイドバーに貼る)は WP管理画面 or 別途 widget編集で行う(本scriptは登録のみ)。
#   owner 実行: sudo bash tools/sidebar/deploy_shortcodes.sh
set -uo pipefail
THEME="/var/www/wp_stg/wp-content/themes/generatepress-kpop"
SRC="$(cd "$(dirname "$0")" && pwd)"
FUNC="$THEME/functions.php"
TS="$(date +%s)"
fail(){ echo "[FATAL] $1"; exit 1; }
[ -f "$SRC/sidebar_shortcodes.php" ] || fail "ソース欠落"
command -v php >/dev/null && { php -l "$SRC/sidebar_shortcodes.php" >/dev/null || fail "shortcode php構文NG"; }

echo "=== shortcode ファイル配置 ==="
cp "$SRC/sidebar_shortcodes.php" "$THEME/widgets/sidebar_shortcodes.php"
echo "  配置: $THEME/widgets/sidebar_shortcodes.php"

echo "=== functions.php に require 追加(冪等)==="
if grep -q "sidebar_shortcodes.php" "$FUNC"; then
  echo "  既存(skip)"
else
  cp "$FUNC" "$FUNC.bak.$TS"
  line="$(grep -nE "require.*events_widget\.php" "$FUNC" | head -1 | cut -d: -f1)"
  [ -z "$line" ] && line="$(grep -nE "require.*today_birthday\.php" "$FUNC" | head -1 | cut -d: -f1)"
  [ -z "$line" ] && fail "require基準行が見つからない"
  tmpl="$(sed -n "${line}p" "$FUNC" | sed -E 's/(events_widget|today_birthday)\.php/sidebar_shortcodes.php/')"
  awk -v ln="$line" -v ins="$tmpl" 'NR==ln{print;print ins;next}{print}' "$FUNC" > "$FUNC.tmp" && mv "$FUNC.tmp" "$FUNC"
  echo "  require追加(L$line直後)"
  command -v php >/dev/null && { php -l "$FUNC" >/dev/null || { cp "$FUNC.bak.$TS" "$FUNC"; fail "functions.php構文NG→ロールバック"; }; }
fi
echo "  functions.php OK"
echo ""
echo "=== 次の手順(トップのサイドバーに貼る)==="
echo "  WP管理画面 → 外観 → ウィジェット → サイドバー(sidebar-1)に"
echo "  「カスタムHTML」ウィジェットを追加し、内容に次を貼り付け:"
echo "      [kpop_birthday]"
echo "      [kpop_events]"
echo "  (保存後トップのサイドバーに誕生日枠・イベント枠が表示される)"
echo "=== 完了 ==="
