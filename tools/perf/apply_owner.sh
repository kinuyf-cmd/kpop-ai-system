#!/usr/bin/env bash
# apply_owner.sh — 本番テーマCSSの最適化を owner が1コマンドで適用する。
#   貼り付け時の改行分断を避けるため、複数手順を1スクリプトに集約。
#   実行: sudo bash tools/perf/apply_owner.sh
#   (① WebPコピーは適用済み。② nginx統合は config 確認が要るため本スクリプト対象外)
set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
CSS="/var/www/wp_stg/wp-content/themes/generatepress-kpop/style.css"
PATCH="$REPO/tools/perf/a11y_contrast_patch.css"

[ -f "$CSS" ]   || { echo "[FATAL] style.css が見つかりません: $CSS"; exit 1; }
[ -f "$PATCH" ] || { echo "[FATAL] patch が見つかりません: $PATCH"; exit 1; }

echo "================ ③ 子テーマ CSS minify ================"
python3 "$REPO/tools/perf/minify_theme_css.py" "$CSS"

echo ""
echo "================ ④ 矢印コントラスト堅牢化(末尾追記) ================"
# 冪等: 既に追記済みなら重複させない
if grep -q "a11y_contrast_patch" "$CSS" 2>/dev/null; then
  echo "  既に適用済み(マーカー検出)。スキップ。"
else
  {
    echo ""
    echo "/* ==== a11y_contrast_patch (applied $(date +%F)) ==== */"
    cat "$PATCH"
  } >> "$CSS"
  echo "  追記完了。"
fi

echo ""
echo "================ 検証 ================"
SZ=$(wc -c < "$CSS")
echo "  style.css 現在 $((SZ/1024))KB"
echo "  patchマーカー: $(grep -c 'a11y_contrast_patch' "$CSS") 箇所"
# WP がテーマヘッダを失っていないか(Theme Name 必須)
grep -q "Theme Name" "$CSS" && echo "  テーマヘッダ: 保持 OK" || echo "  ⚠️ テーマヘッダ消失!.bak から復旧を"
echo ""
echo "  CSS反映が見えない時は ?ver= の filemtime バストを確認(memory: stg-css-cache-bust-filemtime)。"
echo "  残: ② nginx WebP透過配信(tools/perf/webp_nginx.conf を kpopjournal.conf に統合)。"
echo "================ 完了 ================"
