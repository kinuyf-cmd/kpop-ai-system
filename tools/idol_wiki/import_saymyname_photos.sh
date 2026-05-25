#!/usr/bin/env bash
# import_saymyname_photos.sh
#   SAY MY NAME(pid 262)のメンバー個別ポートレート(photos_saymyname/262_<idx>.jpg)を冪等import。
#   取得元: saymyname_photos_fetch.py(kprofiles 経由 / 原権利 iNKODE 公式)。オーナーが著作権
#   リスク承知の上で採用した判断(2026-05-26)。Commons 限定ポリシーからの明示的逸脱。
#   メタ契約は import_photos2_verified.sh と同一:
#     - members_<idx>_member_image  = att_id
#     - _members_<idx>_member_image = field_member_image (ACFコンパニオンキー必須)
#     - members_<idx>_member_image_credit + _..._credit (出典文。誤情報防止のため枠ごとに付与)
#     - member_photo_credit (組1回・既存があれば尊重)
#   owner 実行: sudo -u www-data bash /home/aiuser/kpop-ai-system/tools/idol_wiki/import_saymyname_photos.sh
set -euo pipefail
WP="wp --path=/var/www/wp_stg"
DIR="/home/aiuser/.kpop_recovery/photos_saymyname"
MAN="$DIR/manifest.json"
CRED="$DIR/credits.json"
PID="262"
GROUP_CREDIT="メンバー写真: kprofiles.com 経由（原権利: SAY MY NAME 公式 / iNKODE）"
is_num(){ [[ "$1" =~ ^[0-9]+$ ]]; }

mapfile -t IDXS < <(python3 -c "
import json
m=json.load(open('$MAN'))
for x in m['$PID']:
    if x.get('available'): print(x['index'])
")

echo "================ SAY MY NAME メンバー写真 import (photos_saymyname) ================"
n=0; skip=0; nofile=0
for idx in "${IDXS[@]}"; do
  f="$DIR/${PID}_${idx}.jpg"; key="members_${idx}_member_image"
  if [ ! -f "$f" ]; then echo "  [nofile] $f"; nofile=$((nofile+1)); continue; fi
  ex="$($WP post meta get "$PID" "$key" 2>/dev/null || true)"
  if is_num "$ex"; then echo "  [skip] post $PID $key (att $ex)"; skip=$((skip+1)); continue; fi
  att="$($WP media import "$f" --post_id="$PID" --porcelain)"
  $WP post meta update "$PID" "$key" "$att" >/dev/null
  $WP post meta update "$PID" "_${key}" field_member_image >/dev/null
  cr="$(python3 -c "import json;d=json.load(open('$CRED'));print(d['$PID'].get('$idx',{}).get('credit',''))" 2>/dev/null || true)"
  if [ -n "$cr" ]; then
    $WP post meta update "$PID" "members_${idx}_member_image_credit" "$cr" >/dev/null
    $WP post meta update "$PID" "_members_${idx}_member_image_credit" field_member_image_credit >/dev/null
  fi
  echo "  [ok]   post $PID $key = $att"
  n=$((n+1))
done

# 組単位 credit(既存を尊重)
cur="$($WP post meta get "$PID" member_photo_credit 2>/dev/null || true)"
if [ -z "$cur" ]; then
  $WP post meta update "$PID" member_photo_credit "$GROUP_CREDIT" >/dev/null
  $WP post meta update "$PID" _member_photo_credit field_member_photo_credit >/dev/null
  echo "  [credit] member_photo_credit set"
else
  echo "  [credit] member_photo_credit 既存を尊重: $cur"
fi

echo "  import $n / skip $skip / nofile $nofile"
echo ""
echo "================ 検証サマリ(members_<idx>_member_image 設定済み) ================"
total="$($WP post meta get "$PID" members 2>/dev/null || echo 0)"
set_n=0
for i in $(seq 0 $((total-1))); do
  v="$($WP post meta get "$PID" "members_${i}_member_image" 2>/dev/null || true)"
  is_num "$v" && { set_n=$((set_n+1)); echo "  idx $i = $v OK"; } || echo "  idx $i = (none)"
done
echo "  post $PID : $set_n / $total メンバー写真設定済み"
echo "================ 完了 ================"
