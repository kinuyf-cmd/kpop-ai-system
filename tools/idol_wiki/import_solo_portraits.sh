#!/usr/bin/env bash
# import_solo_portraits.sh
#   ソロ24組の本人ポートレート(batch_solo_portraits/<pid>_logo.png, Wikidata P18確定)を
#   logo_image スロットへ冪等import。オーナー決定: ソロ(members=0)写真は logo_image に入れる。
#   logo_image + _logo_image=field_logo_image + logo_credit(CC帰属表示・必須)をセット。
#   import_logos2_verified.sh と同一ロジック・DIR のみ batch_solo_portraits。
#   owner 実行: sudo -u www-data bash /home/aiuser/.kpop_recovery/import_solo_portraits.sh
set -euo pipefail
WP="wp --path=/var/www/wp_stg"
DIR="/home/aiuser/.kpop_recovery/batch_solo_portraits"
CRED="$DIR/import_credits.json"
is_num(){ [[ "$1" =~ ^[0-9]+$ ]]; }

n=0; skip=0
echo "================ ソロ本人ポートレート import (batch_solo_portraits / Wikidata P18) ================"
for f in "$DIR"/*_logo.png; do
  [ -e "$f" ] || continue
  pid="$(basename "$f" _logo.png)"
  ex="$($WP post meta get "$pid" logo_image 2>/dev/null || true)"
  if is_num "$ex"; then echo "  [skip] post $pid logo (att $ex)"; skip=$((skip+1)); continue; fi
  att="$($WP media import "$f" --porcelain)"
  $WP post meta update "$pid" logo_image "$att" >/dev/null
  $WP post meta update "$pid" _logo_image field_logo_image >/dev/null
  cr="$(python3 -c "import json,sys;d=json.load(open('$CRED'));print(d.get('$pid',{}).get('credit',''))" 2>/dev/null || true)"
  if [ -n "$cr" ]; then
    $WP post meta update "$pid" logo_credit "$cr" >/dev/null
    $WP post meta update "$pid" _logo_credit field_logo_credit >/dev/null
  fi
  echo "  [ok]   post $pid logo_image = $att"
  n=$((n+1))
done
echo "  import $n / skip $skip"

echo ""
echo "================ 検証サマリ ================"
for f in "$DIR"/*_logo.png; do
  [ -e "$f" ] || continue
  pid="$(basename "$f" _logo.png)"
  v="$($WP post meta get "$pid" logo_image 2>/dev/null || true)"
  is_num "$v" && echo "  $pid logo=$v OK" || echo "  $pid logo=MISSING"
done
echo "================ 完了 ================"
