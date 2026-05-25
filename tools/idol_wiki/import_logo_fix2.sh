#!/usr/bin/env bash
# import_logo_fix2.sh — 監査第2弾(曲/ツアーロゴ誤取得)の差し替え。
#   aespa(64): 誤「Drama」曲ロゴ → 正「aespa」グループロゴ(PD, SM Entertainment、黒背景透明化済)。
#   batch_logo_fix2/<pid>_logo.png を import → logo_image + logo_credit 上書き。
#   owner 実行: sudo -u www-data bash /home/aiuser/kpop-ai-system/tools/idol_wiki/import_logo_fix2.sh
set -euo pipefail
WP="wp --path=/var/www/wp_stg"
DIR="/home/aiuser/.kpop_recovery/batch_logo_fix2"
CRED="$DIR/import_credits.json"
jget(){ python3 -c "import json,sys;d=json.load(open('$CRED'));print(d.get('$1',{}).get('$2',''))" 2>/dev/null || true; }

echo "================ 監査第2弾 ロゴ差し替え (batch_logo_fix2) ================"
for f in "$DIR"/*_logo.png; do
  [ -e "$f" ] || continue
  pid="$(basename "$f" _logo.png)"
  before="$($WP post meta get "$pid" logo_image 2>/dev/null || true)"
  att="$($WP media import "$f" --porcelain)"
  $WP post meta update "$pid" logo_image "$att" >/dev/null
  $WP post meta update "$pid" _logo_image field_logo_image >/dev/null
  cr="$(jget "$pid" credit)"
  if [ -n "$cr" ]; then
    $WP post meta update "$pid" logo_credit "$cr" >/dev/null
    $WP post meta update "$pid" _logo_credit field_logo_credit >/dev/null
  fi
  echo "  [ok] post $pid logo_image: $before -> $att  cr=[$cr]"
done
echo "================ 完了 ================"
