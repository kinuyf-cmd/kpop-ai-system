#!/usr/bin/env bash
# 誤って削除した各ライターのソロ写真を復元する。
# 退避フォルダ(backups/writer_group_photos_20260527_012859)の画像を再 import し、
# 画像内のライター名に基づいて正しい writer 投稿の featured image に設定する。
# DB/メディアは www-data 所有のため **オーナー実行(sudo)**。
#
# 経緯: remove_writer_group_photos.sh を「全員まとめ写真」と誤認して実行したが、
# 実体は各ライターのソロ写真(別々の画像)だった。退避済みファイルから復元する。
#
# 使い方(オーナー):  sudo bash scripts/restore_writer_solo_photos.sh
set -euo pipefail
WP_CLI="${WP_CLI:-wp}"
WP_PATH="${WP_PATH:-/var/www/wp_stg}"
SRC="${SRC:-/home/aiuser/kpop-ai-system/backups/writer_group_photos_20260527_012859}"

# ファイル(連番)→ writer 投稿ID の対応(画像内テキストで判定済み)
declare -A MAP=(
  ["Gemini_Generated_Image_jmtfu3jmtfu3jmtf-1-7-e1779812490420.jpg"]=2563   # ミナ
  ["Gemini_Generated_Image_jmtfu3jmtfu3jmtf-1-11-e1779812699783.jpg"]=2564  # ゆい
  ["Gemini_Generated_Image_jmtfu3jmtfu3jmtf-1-12-e1779812740976.jpg"]=2565  # のの
  ["Gemini_Generated_Image_jmtfu3jmtfu3jmtf-1-4-e1779812261738.jpg"]=2566   # さき
  ["Gemini_Generated_Image_jmtfu3jmtfu3jmtf-1-6-e1779812424558.jpg"]=2567   # はるか
  ["Gemini_Generated_Image_jmtfu3jmtfu3jmtf-1-8-e1779812585891.jpg"]=2568   # アヤ
  ["Gemini_Generated_Image_jmtfu3jmtfu3jmtf-1-9-e1779812634976.jpg"]=2569   # リカ
  ["Gemini_Generated_Image_jmtfu3jmtfu3jmtf-1-10-e1779812665996.jpg"]=2570  # ももか
)

echo "== ライターソロ写真の復元 =="
if [ ! -d "$SRC" ]; then
  echo "ERROR: 退避フォルダが見つかりません: $SRC" >&2
  exit 1
fi

for f in "${!MAP[@]}"; do
  pid="${MAP[$f]}"
  path="$SRC/$f"
  name=$(sudo -u www-data "$WP_CLI" --path="$WP_PATH" post get "$pid" --field=post_title 2>/dev/null || echo "?")
  if [ ! -f "$path" ]; then
    echo "  [skip] $name: 退避ファイル無し ($f)"
    continue
  fi
  # import して attachment ID を取得し、その writer の featured に設定
  aid=$(sudo -u www-data "$WP_CLI" --path="$WP_PATH" media import "$path" --post_id="$pid" --featured_image --porcelain 2>/dev/null || true)
  if [ -n "${aid:-}" ]; then
    echo "  [ok]   $name (writer $pid) <- attachment $aid"
  else
    echo "  [fail] $name: import 失敗 ($f)"
  fi
done

echo "== 完了。/writers/{key}/ にソロ写真が戻ったか確認してください =="
