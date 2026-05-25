#!/usr/bin/env bash
# clear_bad_logos2.sh — 監査第3弾(全グループロゴ目視)で発見した本体外ロゴ2件をクリア。
#   293 SISTAR = 「SISTAR Showtime」リアリティ番組ロゴ(グループロゴでない)。
#   297 VIXX   = 「VIXX LR」サブユニット(Leo+Ravi)ロゴ(VIXX本体でない)。
#   いずれもCommons/P154にフリーの正規グループロゴが無いためクリア(オーナー方針踏襲)。
#   template はロゴ空なら枠を出さない設計。ヒーロー写真は残る。
#   owner 実行: sudo -u www-data bash /home/aiuser/kpop-ai-system/tools/idol_wiki/clear_bad_logos2.sh
set -euo pipefail
WP="wp --path=/var/www/wp_stg"
PIDS=(293 297)

echo "================ 本体外ロゴ クリア(第3弾) ================"
for pid in "${PIDS[@]}"; do
  before="$($WP post meta get "$pid" logo_image 2>/dev/null || true)"
  $WP post meta delete "$pid" logo_image  || echo "    !! logo_image delete失敗 pid=$pid"
  $WP post meta delete "$pid" _logo_image || true
  $WP post meta delete "$pid" logo_credit  || true
  $WP post meta delete "$pid" _logo_credit || true
  after="$($WP post meta get "$pid" logo_image 2>/dev/null || true)"
  echo "  [clear] post $pid : $before -> '${after:-(空)}'"
done
echo "================ 完了 ================"
