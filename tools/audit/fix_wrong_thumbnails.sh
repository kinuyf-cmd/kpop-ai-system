#!/usr/bin/env bash
# fix_wrong_thumbnails.sh — RED TEAM監査で無関係/不適切と判定した4記事のサムネ(featured image)を
#   検証済みの正しい画像に差し替える。owner 実行。
#
#   判定(2026-05-25 目視 + 出典検証):
#     treasure-if-i           : 白ドレス女性(別人) → OSEN本記事のNEW WAVE公式アルバム画像
#     le-sserafim-pureflow    : 空港の男性(別Gr)   → Sports Chosun 5人コンセプト写真(本人)
#     akmu-circle             : 別男性Grコラージュ  → Idol Wiki AKMU メンバー写真(att 1305)
#     txt-youngjoon           : "HOP OFF.."卑語焼込 → Idol Wiki TXT メンバー写真(att 234)
#       ※ txt/akmu の出典(Koreaboo/Soompi)og:imageは卑語/コラージュで再取得不可 → Idol Wiki流用
#
#   方式: treasure/le-sserafim は新画像をmedia import→featured設定。akmu/txt は既存att を featured設定。
#   冪等: 現featuredが既に目的attなら skip。差し替え前に旧featured idを記録。
#   owner 実行: sudo -u www-data bash tools/audit/fix_wrong_thumbnails.sh
set -uo pipefail
WP="wp --path=/var/www/wp_stg"
DIR="$(cd "$(dirname "$0")" && pwd)/thumb_fix"
LOG="/home/aiuser/.kpop_recovery/thumb_fix_$(date +%Y%m%d_%H%M%S).log"
is_num(){ [[ "$1" =~ ^[0-9]+$ ]]; }

pid_of(){ $WP post list --post_type=post --name="$1" --field=ID 2>/dev/null | head -1; }

set_featured(){  # $1=post_id $2=att_id $3=label
  local pid="$1" att="$2" label="$3"
  local cur; cur="$($WP post meta get "$pid" _thumbnail_id 2>/dev/null || true)"
  echo "  [$label] post=$pid 旧featured=$cur → 新=$att" | tee -a "$LOG"
  if [ "$cur" = "$att" ]; then echo "    (既に設定済 skip)"; return; fi
  $WP post meta update "$pid" _thumbnail_id "$att" >/dev/null && echo "    ✅ 差し替え完了"
}

import_and_set(){  # $1=slug $2=file $3=label  → import file as media, set featured
  local slug="$1" file="$2" label="$3"
  local pid; pid="$(pid_of "$slug")"
  [ -z "$pid" ] && { echo "  [$label] slug未検出: $slug"; return; }
  [ -f "$file" ] || { echo "  [$label] 画像ファイルなし: $file"; return; }
  local att; att="$($WP media import "$file" --porcelain 2>/dev/null)"
  is_num "$att" || { echo "  [$label] media import失敗"; return; }
  set_featured "$pid" "$att" "$label"
}

echo "================ 無関係サムネ差し替え(4記事)================" | tee "$LOG"
import_and_set "treasure-if-i-mini4th-album"        "$DIR/treasure_new.jpg"   "treasure"
import_and_set "le-sserafim-new-album-pureflow"     "$DIR/lesserafim_new.jpg" "le-sserafim"
# akmu / txt は Idol Wiki 既存attを流用
A_PID="$(pid_of akmu-circle-chart-triple-crown)";        [ -n "$A_PID" ] && set_featured "$A_PID" 1305 "akmu"
T_PID="$(pid_of txt-youngjoon-girlgroup-cover-debate)";  [ -n "$T_PID" ] && set_featured "$T_PID" 234  "txt"

echo "" | tee -a "$LOG"
echo "================ 検証 ================" | tee -a "$LOG"
for slug in treasure-if-i-mini4th-album le-sserafim-new-album-pureflow akmu-circle-chart-triple-crown txt-youngjoon-girlgroup-cover-debate; do
  pid="$(pid_of "$slug")"
  tid="$($WP post meta get "$pid" _thumbnail_id 2>/dev/null || true)"
  echo "  $slug → featured=$tid" | tee -a "$LOG"
done
echo "  ログ: $LOG"
echo "================ 完了 ================"
