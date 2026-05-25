#!/usr/bin/env bash
# deploy_top_widgets.sh — トップ(sidebar-1)に誕生日枠・イベント枠を配置(ステップ2)。
#   オーナー方針: イベント=既存「1ヶ月以内のイベント」プレースホルダ(custom_html-3)を
#   [kpop_events] に置換、誕生日=新規Custom HTMLウィジェットを最上部に追加。
#   wp widget コマンド経由(シリアライズ配列の直SQL編集を避け安全)。
#   ショートコードは自前で box(タイトル付き)を出力するため、widget の title は空にして二重表示回避。
#   owner 実行: sudo -u www-data wp ... 形式。本scriptは sudo bash で。
set -uo pipefail
WP="wp --path=/var/www/wp_stg"
SB="sidebar-1"

echo "================ ① イベント枠: custom_html-3 を [kpop_events] に置換 ================"
# 既存 widget の content を [kpop_events] に、title を空に(shortcodeが箱+見出しを出すため)
if $WP widget update custom_html-3 --title="" --content="[kpop_events]" 2>&1; then
  echo "  ✅ custom_html-3 → [kpop_events]"
else
  echo "  [warn] update失敗。idが変わっている可能性→ list確認:"
  $WP widget list "$SB" --fields=name,id,position 2>&1 | grep -i "1ヶ月\|event\|custom_html-3" || true
fi

echo ""
echo "================ ② 誕生日枠: 新規Custom HTMLを最上部(position 1)に追加 ================"
# 既に追加済みか(content に kpop_birthday を含む widget があるか)冪等チェック
if $WP widget list "$SB" --format=json 2>/dev/null | grep -q "kpop_birthday"; then
  echo "  既に誕生日widget存在(skip)"
else
  # position 1 に Custom HTML を追加。title空(shortcodeが「今日の誕生日」見出しを出す)
  $WP widget add custom_html "$SB" 1 --title="" --content="[kpop_birthday]" 2>&1 && echo "  ✅ 誕生日widget追加(pos1)" || echo "  [FAIL] 誕生日widget追加失敗"
fi

echo ""
echo "================ 検証 ================"
$WP widget list "$SB" --fields=name,id,position,options --format=table 2>&1 | head -12
echo ""
echo "  ※ shortcode実行が有効(deploy_shortcodes.sh済)であること前提。"
echo "  トップを再読込し『今日の誕生日』『イベント』枠が表示されるか確認してください。"
echo "================ 完了 ================"
