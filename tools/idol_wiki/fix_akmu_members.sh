#!/usr/bin/env bash
# fix_akmu_members.sh
#   AKMU(post 313)のスキーマ不整合(実2人組だが members=0)を修正し、
#   メンバー2名の本人写真(Wikidata P18確定)を import する。
#   データはWikidata/既存artist_summary由来=捏造なし。
#     - Lee Chan-hyuk(이찬혁, 1996-09-12, 兄, ボーカル/ギター/作詞作曲)
#     - Lee Su-hyun  (이수현, 1999-05-04, 妹, メインボーカル)
#   ACF member repeater フィールドキーは既存組(post 89)と同一構造:
#     members_N_member_{name,real_name,birthday,position,nationality,nickname,image}
#     画像コンパニオン _members_N_member_image = field_member_image
#   owner 実行: sudo -u www-data bash /home/aiuser/.kpop_recovery/fix_akmu_members.sh
set -euo pipefail
WP="wp --path=/var/www/wp_stg"
PID=313
DIR="/home/aiuser/.kpop_recovery/batch_akmu"
CRED="$DIR/manifest.json"
is_num(){ [[ "$1" =~ ^[0-9]+$ ]]; }

echo "================ AKMU(313) members=2 データ修正 ================"
# repeater 件数
$WP post meta update $PID members 2 >/dev/null
echo "  members = 2"

# --- member 0: Lee Chan-hyuk(兄) ---
$WP post meta update $PID members_0_member_name        "LEE CHAN-HYUK (이찬혁)" >/dev/null
$WP post meta update $PID members_0_member_real_name   "イ・チャンヒョク (Lee Chan-hyuk / 이찬혁)" >/dev/null
$WP post meta update $PID members_0_member_birthday    "19960912" >/dev/null
$WP post meta update $PID members_0_member_position    "ボーカル / ギター / 作詞作曲(兄・リーダー)" >/dev/null
$WP post meta update $PID members_0_member_nationality "韓国" >/dev/null
$WP post meta update $PID members_0_member_nickname    "プロデュース担当の実兄" >/dev/null
echo "  [0] Lee Chan-hyuk フィールド投入"

# --- member 1: Lee Su-hyun(妹) ---
$WP post meta update $PID members_1_member_name        "LEE SU-HYUN (이수현)" >/dev/null
$WP post meta update $PID members_1_member_real_name   "イ・スヒョン (Lee Su-hyun / 이수현)" >/dev/null
$WP post meta update $PID members_1_member_birthday    "19990504" >/dev/null
$WP post meta update $PID members_1_member_position    "メインボーカル(妹)" >/dev/null
$WP post meta update $PID members_1_member_nationality "韓国" >/dev/null
$WP post meta update $PID members_1_member_nickname    "圧倒的歌唱力の実妹" >/dev/null
echo "  [1] Lee Su-hyun フィールド投入"

echo ""
echo "================ メンバー写真 import (Wikidata P18) ================"
n=0; skip=0
for idx in 0 1; do
  f="$DIR/313_${idx}.png"
  [ -e "$f" ] || { echo "  [nofile] member $idx ($f)"; continue; }
  ex="$($WP post meta get $PID members_${idx}_member_image 2>/dev/null || true)"
  if is_num "$ex"; then echo "  [skip] member $idx (att $ex)"; skip=$((skip+1)); continue; fi
  att="$($WP media import "$f" --porcelain)"
  $WP post meta update $PID members_${idx}_member_image "$att" >/dev/null
  $WP post meta update $PID _members_${idx}_member_image field_member_image >/dev/null
  cr="$(python3 -c "import json;d=json.load(open('$CRED'));print(d.get('$idx',{}).get('credit',''))" 2>/dev/null || true)"
  if [ -n "$cr" ]; then
    $WP post meta update $PID members_${idx}_member_image_credit "$cr" >/dev/null || true
  fi
  echo "  [ok]   member $idx image = $att"
  n=$((n+1))
done
echo "  import $n / skip $skip"

echo ""
echo "================ 検証サマリ ================"
echo "  members count = $($WP post meta get $PID members)"
for idx in 0 1; do
  nm="$($WP post meta get $PID members_${idx}_member_name 2>/dev/null || true)"
  im="$($WP post meta get $PID members_${idx}_member_image 2>/dev/null || true)"
  echo "  [$idx] $nm  image=$im"
done
echo "================ 完了 ================"
