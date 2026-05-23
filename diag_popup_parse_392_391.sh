#!/usr/bin/env bash
# READ-ONLY: popup 392 / 391 の popup_detail(ACF prose)を取り出し、
# parser に通して A(丸ごと) と B(特典句のみ・コンマ分割で前置き除去) を並べて見せる。
# DB書き込みなし。392/391判断をオーナーが「実物 verbatim」で下すための材料。
#
#   sudo -u www-data bash diag_popup_parse_392_391.sh
#
set -euo pipefail
WP="sudo -u www-data wp --path=/var/www/wp_stg"
PARSER="python3 lib/popup_reservation_benefit_parser.py"

for PID in 392 391 606 595; do
  echo "=================== popup ID=$PID ==================="
  TITLE=$($WP post get "$PID" --field=post_title 2>/dev/null || echo "(取得失敗)")
  echo "title: $TITLE"
  echo "--- popup_detail (ACF prose, verbatim) ---"
  DETAIL=$($WP post meta get "$PID" popup_detail 2>/dev/null || echo "")
  if [ -z "$DETAIL" ]; then
    echo "(popup_detail 空 — 別キーの可能性。メタ一覧:)"
    $WP post meta list "$PID" --fields=meta_key 2>/dev/null | grep -iE 'detail|本文|prose|content' || true
  else
    printf '%s\n' "$DETAIL"
  fi
  echo "--- 現状の popup_reservation / popup_benefit (DB既存値) ---"
  echo "reservation: $($WP post meta get "$PID" popup_reservation 2>/dev/null || echo '')"
  echo "benefit    : $($WP post meta get "$PID" popup_benefit 2>/dev/null || echo '')"
  echo "--- parser 出力 [A=丸ごと verbatim] ---"
  printf '%s' "$DETAIL" | $PARSER
  echo "===================================================="
  echo
done
echo "※ A=parser出力そのまま。B=特典句の直前コンマで分割し前置き(コレクション展開/限定販売 等)を落とす案。"
echo "  Bを採る場合も verbatim維持・捏造ゼロ。392/391は同基準で統一する。"
