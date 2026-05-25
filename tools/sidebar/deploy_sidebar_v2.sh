#!/usr/bin/env bash
# deploy_sidebar_v2.sh — トップサイドバー仕上げ(2026-05-25 オーナー指示):
#   ① 人気記事 placeholder → [kpop_popular](WPP実データ)
#   ② Today's Chart placeholder → [kpop_chart](チャートcategory実記事)
#   ③ カムバック予定 widget 削除
#   ④ 誕生日/イベント枠 UI磨き(sidebar_polish.css 追記)
#   shortcode定義更新(chart/popular追加)も反映。wp widget経由・冪等・直接渡し。
#   owner 実行: sudo bash tools/sidebar/deploy_sidebar_v2.sh
set -uo pipefail
THEME="/var/www/wp_stg/wp-content/themes/generatepress-kpop"
SRC="$(cd "$(dirname "$0")" && pwd)"
WP="wp --path=/var/www/wp_stg"
SB="sidebar-1"
CSS="$THEME/style.css"
TS="$(date +%s)"
fail(){ echo "[FATAL] $1"; exit 1; }

echo "================ ① shortcode定義更新(chart/popular 追加版)================"
command -v php >/dev/null && { php -l "$SRC/sidebar_shortcodes.php" >/dev/null || fail "shortcode php構文NG"; }
cp "$SRC/sidebar_shortcodes.php" "$THEME/widgets/sidebar_shortcodes.php"
echo "  更新: widgets/sidebar_shortcodes.php"

echo ""
echo "================ ② UI磨きCSS追記(冪等)================"
if grep -q "kpop-birthday-list .kpop-birthday-item" "$CSS"; then
  echo "  polish CSS 既存(skip)"
else
  cp "$CSS" "$CSS.bak.$TS"
  { echo ""; cat "$SRC/sidebar_polish.css"; } >> "$CSS"
  echo "  sidebar_polish.css 追記"
fi

echo ""
echo "================ ③ widget 更新(人気記事/チャート 実データ化)================"
# 現widget一覧から title でターゲットを探して content を shortcode に置換
maplist="$($WP widget list "$SB" --format=json 2>/dev/null)"
upd(){ # $1=title一致パターン $2=shortcode $3=ラベル
  local id; id="$(printf '%s' "$maplist" | python3 -c "import sys,json,re; d=json.load(sys.stdin); print(next((w['id'] for w in d if re.search(r'''$1''', w['options'].get('title',''))), ''))" 2>/dev/null)"
  if [ -n "$id" ]; then
    $WP widget update "$id" --title="" --content="$2" >/dev/null && echo "  ✅ $3: $id → $2"
  else echo "  [warn] $3: 対象widget($1)見つからず"; fi
}
upd "人気記事|人気"        "[kpop_popular]" "人気記事"
upd "Today.?s Chart|チャート" "[kpop_chart]"   "Today's Chart"

echo ""
echo "================ ④ カムバック予定 widget 削除 ================"
cb_id="$(printf '%s' "$maplist" | python3 -c "import sys,json,re; d=json.load(sys.stdin); print(next((w['id'] for w in d if 'カムバック' in w['options'].get('title','')), ''))" 2>/dev/null)"
if [ -n "$cb_id" ]; then
  $WP widget deactivate "$cb_id" >/dev/null 2>&1 && echo "  ✅ カムバック予定 削除(deactivate): $cb_id" || \
  $WP widget delete "$cb_id" >/dev/null 2>&1 && echo "  ✅ カムバック予定 削除(delete): $cb_id" || \
  echo "  [warn] カムバック予定 削除失敗: $cb_id"
else echo "  カムバック予定 widget 見つからず(既に削除済?)"; fi

echo ""
echo "================ 検証 ================"
$WP widget list "$SB" --fields=id,position,options --format=table 2>&1 | head -10
echo "  → 人気記事=[kpop_popular]/チャート=[kpop_chart]/カムバック消滅 を確認。トップ再読込で表示確認。"
echo "================ 完了 ================"
