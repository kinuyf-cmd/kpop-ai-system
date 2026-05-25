#!/usr/bin/env bash
# clear_bad_logos.sh — フリー差し替えロゴが存在しない不良ロゴ7件を空にする(オーナー決定 2026-05-26)。
#   写真混入6(269 izna/274 BADVILLAIN/275 QWER/284 Xdinary Heroes/286 AB6IX/287 Golden Child)
#   + 真っ黒1(301 Brown Eyed Girls) + 曲/ツアーロゴ誤取得でフリー正規ロゴ無し1(80 NCT=NEO CITY tour logo)。
#   template single-idol_artist.php は logo_image 空ならロゴ枠を出さない設計なので、
#   meta削除でクリーンに不良表示が消える(ヒーロー集合写真は残るのでページは成立)。
#   logo_image/_logo_image/logo_credit/_logo_credit を削除。attachment自体は他で参照され得るため残す。
#   owner 実行: sudo -u www-data bash /home/aiuser/kpop-ai-system/tools/idol_wiki/clear_bad_logos.sh
set -euo pipefail
WP="wp --path=/var/www/wp_stg"
PIDS=(269 274 275 284 286 287 301 80)

echo "================ 不良ロゴ クリア ================"
for pid in "${PIDS[@]}"; do
  before="$($WP post meta get "$pid" logo_image 2>/dev/null || true)"
  # エラーを握りつぶさず表示（前回は失敗が見えなかった）。値未存在のdeleteは警告のみなので継続。
  $WP post meta delete "$pid" logo_image  || echo "    !! logo_image delete失敗 pid=$pid"
  $WP post meta delete "$pid" _logo_image || true
  $WP post meta delete "$pid" logo_credit  || true
  $WP post meta delete "$pid" _logo_credit || true
  after="$($WP post meta get "$pid" logo_image 2>/dev/null || true)"
  echo "  [clear] post $pid : $before -> '${after:-(空)}'"
done

echo ""
echo "================ 検証(logo_image が空であること) ================"
for pid in "${PIDS[@]}"; do
  v="$($WP post meta get "$pid" logo_image 2>/dev/null || true)"
  [ -z "$v" ] && echo "  $pid logo_image=(空) OK" || echo "  $pid logo_image=$v 残存!"
done
echo "================ 完了 ================"
