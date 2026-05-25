#!/usr/bin/env bash
# import_solo_hero.sh — ステージ済みソロ本人写真(<pid>_hero.jpg)を冪等で stg に featured import。
#   import_group_hero.sh と同一ロジック・DIR のみ batch_solo_hero。
#   media import → _thumbnail_id meta update(set-thumbnail二重行トラップ回避) → hero_credit + alt。
#   owner 実行: sudo -u www-data bash /home/aiuser/kpop-ai-system/tools/idol_wiki/import_solo_hero.sh
set -euo pipefail
WP="wp --path=/var/www/wp_stg"
DIR="/home/aiuser/.kpop_recovery/batch_solo_hero"
CRED="$DIR/import_credits.json"
is_num(){ [[ "$1" =~ ^[0-9]+$ ]]; }
jget(){ python3 -c "import json,sys;d=json.load(open('$CRED'));print(d.get('$1',{}).get('$2',''))" 2>/dev/null || true; }

n=0; skip=0
echo "================ ソロ本人写真 featured import (batch_solo_hero) ================"
for f in "$DIR"/*_hero.jpg; do
  [ -e "$f" ] || continue
  pid="$(basename "$f" _hero.jpg)"
  ex="$($WP post meta get "$pid" _thumbnail_id 2>/dev/null || true)"
  if is_num "$ex" && [ "$ex" != "0" ]; then echo "  [skip] post $pid featured (att $ex)"; skip=$((skip+1)); continue; fi
  att="$($WP media import "$f" --porcelain)"
  $WP post meta update "$pid" _thumbnail_id "$att" >/dev/null
  alt="$(jget "$pid" alt)"
  [ -n "$alt" ] && $WP post meta update "$att" _wp_attachment_image_alt "$alt" >/dev/null
  cr="$(jget "$pid" credit)"
  [ -n "$cr" ] && $WP post meta update "$pid" hero_credit "$cr" >/dev/null
  echo "  [ok]   post $pid featured=$att  cr=[$cr]"
  n=$((n+1))
done
echo "  import $n / skip $skip"

echo ""
echo "================ 検証サマリ ================"
for f in "$DIR"/*_hero.jpg; do
  [ -e "$f" ] || continue
  pid="$(basename "$f" _hero.jpg)"
  v="$($WP post meta get "$pid" _thumbnail_id 2>/dev/null || true)"
  c="$($WP post meta get "$pid" hero_credit 2>/dev/null || true)"
  if is_num "$v" && [ "$v" != "0" ]; then echo "  $pid featured=$v credit=[$c] OK"; else echo "  $pid featured=MISSING"; fi
done
echo "================ 完了 ================"
