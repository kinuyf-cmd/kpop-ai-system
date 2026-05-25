#!/usr/bin/env bash
# clear_bad_hero.sh — 誤取得ヒーロー画像をクリア。
#   102 PLAVE = Wikidata誤マッチ(QID Q2105115=スロベニアの村Plave)で村の風景写真を取得していた。
#   PLAVEは仮想アイドルでフリーの実写真が無いためクリア(プレースホルダに戻る=村写真より正しい)。
#   _thumbnail_id と hero_credit を削除。template は featured 無しなら頭文字プレースホルダ表示。
#   owner 実行: sudo -u www-data bash /home/aiuser/kpop-ai-system/tools/idol_wiki/clear_bad_hero.sh
set -euo pipefail
WP="wp --path=/var/www/wp_stg"
PIDS=(102)

echo "================ 誤取得ヒーロー クリア ================"
for pid in "${PIDS[@]}"; do
  before="$($WP post meta get "$pid" _thumbnail_id 2>/dev/null || true)"
  $WP post meta delete "$pid" _thumbnail_id || echo "    !! _thumbnail_id delete失敗 pid=$pid"
  $WP post meta delete "$pid" hero_credit   || true
  after="$($WP post meta get "$pid" _thumbnail_id 2>/dev/null || true)"
  echo "  [clear] post $pid : _thumbnail_id $before -> '${after:-(空)}'"
done
echo "================ 完了 ================"
