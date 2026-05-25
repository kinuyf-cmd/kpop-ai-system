#!/usr/bin/env bash
# import_logos3.sh
#   Wikidata P154 で本人確定取得した3組のロゴ(batch_logos3/<pid>_logo.png)を冪等import。
#   90 BIGBANG / 265 &TEAM / 266 TREASURE(全 Public Domain)。
#   logo_image + _logo_image=field_logo_image を両方セット、logo_credit も投入(CC/PD帰属表示)。
#   import_logos2_verified.sh と同一ロジック・DIR のみ batch_logos3。
#   owner 実行: sudo -u www-data bash /home/aiuser/.kpop_recovery/import_logos3.sh
set -euo pipefail
WP="wp --path=/var/www/wp_stg"
DIR="/home/aiuser/.kpop_recovery/batch_logos3"
CRED="$DIR/import_credits.json"
is_num(){ [[ "$1" =~ ^[0-9]+$ ]]; }

n=0; skip=0
echo "================ P154検証済みロゴ import (batch_logos3) ================"
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
