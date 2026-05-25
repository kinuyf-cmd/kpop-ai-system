#!/usr/bin/env bash
# import_logo_fix.sh — 監査で問題判定したロゴを差し替え(logo_image)。
#   batch_logo_fix/<pid>_logo.png を import → logo_image + logo_credit を「上書き」。
#   既存の壊れたロゴを置換するため、import_logos3.sh と違い既存値があっても更新する
#   (冪等性は同一ファイル再importで重複attachmentを作らないよう、既存ロゴと内容が変われば置換)。
#   _thumbnail_id の二重行トラップと同様 logo_image も meta update で1行に保つ。
#   owner 実行: sudo -u www-data bash /home/aiuser/kpop-ai-system/tools/idol_wiki/import_logo_fix.sh
set -euo pipefail
WP="wp --path=/var/www/wp_stg"
DIR="/home/aiuser/.kpop_recovery/batch_logo_fix"
CRED="$DIR/import_credits.json"
jget(){ python3 -c "import json,sys;d=json.load(open('$CRED'));print(d.get('$1',{}).get('$2',''))" 2>/dev/null || true; }

n=0
echo "================ 問題ロゴ差し替え import (batch_logo_fix) ================"
for f in "$DIR"/*_logo.png; do
  [ -e "$f" ] || continue
  pid="$(basename "$f" _logo.png)"
  att="$($WP media import "$f" --porcelain)"
  $WP post meta update "$pid" logo_image "$att" >/dev/null
  $WP post meta update "$pid" _logo_image field_logo_image >/dev/null
  cr="$(jget "$pid" credit)"
  if [ -n "$cr" ]; then
    $WP post meta update "$pid" logo_credit "$cr" >/dev/null
    $WP post meta update "$pid" _logo_credit field_logo_credit >/dev/null
  fi
  echo "  [ok]   post $pid logo_image=$att cr=[$cr]"
  n=$((n+1))
done
echo "  差し替え $n 件"

echo ""
echo "================ 検証 ================"
for f in "$DIR"/*_logo.png; do
  pid="$(basename "$f" _logo.png)"
  v="$($WP post meta get "$pid" logo_image 2>/dev/null || true)"
  c="$($WP post meta get "$pid" logo_credit 2>/dev/null || true)"
  echo "  $pid logo_image=$v credit=[$c]"
done
echo "================ 完了 ================"
