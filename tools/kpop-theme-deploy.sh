#!/bin/bash
# kpop-theme-deploy — リポジトリの子テーマファイルを本番(wp_stg)へ配置する
# 専用ラッパー(2026-05-25)。kpop-wp-rw.sh のファイル版。
#
# 安全境界:
#   - 配置元はリポジトリの themes/generatepress-kpop/ 配下のみ
#   - 配置先は /var/www/wp_stg/wp-content/themes/generatepress-kpop/ 配下のみ
#   - 許可拡張子は .php / .css のみ(任意ファイル配置・本体破壊を防ぐ)
#   - パストラバーサル(..)とサブディレクトリを拒否(直下のみ)
#   - .php は配置前に php -l 構文チェック、失敗なら配置しない
#   - 配置先を timestamp 付きで自動バックアップしてから上書き
#   - 所有者を www-data:www-data に設定
#
# .sh 拡張子なので既存の /usr/local/sbin/kpop/*.sh NOPASSWD ルールで無人実行可。
# 設置: sudo install -o root -g root -m 755 \
#         /home/aiuser/kpop-ai-system/tools/kpop-theme-deploy.sh \
#         /usr/local/sbin/kpop/kpop-theme-deploy.sh
# 使い方: sudo -n /usr/local/sbin/kpop/kpop-theme-deploy.sh functions.php
#         sudo -n /usr/local/sbin/kpop/kpop-theme-deploy.sh content-single.php category-popup.php
set -euo pipefail

SRC_DIR=/home/aiuser/kpop-ai-system/themes/generatepress-kpop
DST_DIR=/var/www/wp_stg/wp-content/themes/generatepress-kpop
BAK_DIR=/var/www/wp_stg/wp-content/themes/.kpop_theme_backups

if [ "$#" -eq 0 ]; then
  echo "usage: kpop-theme-deploy <themeファイル名...> (例: functions.php)"; exit 2
fi

mkdir -p "$BAK_DIR"
ts="$(date +%Y%m%d_%H%M%S)"
deployed=0

for name in "$@"; do
  # --- パス安全性: 直下のファイル名のみ。/ や .. を拒否 ---
  case "$name" in
    */*|*..*|"") echo "[DENY] 不正なファイル名: '$name'(サブディレクトリ/.. 不可)"; exit 3 ;;
  esac
  # --- 拡張子: .php / .css のみ ---
  case "$name" in
    *.php|*.css) : ;;
    *) echo "[DENY] 許可されない拡張子: '$name'(.php/.css のみ)"; exit 3 ;;
  esac

  src="$SRC_DIR/$name"
  dst="$DST_DIR/$name"

  if [ ! -f "$src" ]; then echo "[ERR] 配置元が存在しない: $src"; exit 4; fi

  # --- .php は構文チェック ---
  if [[ "$name" == *.php ]]; then
    if ! php -l "$src" >/dev/null 2>&1; then
      echo "[DENY] PHP構文エラーのため配置中止: $name"; php -l "$src"; exit 5
    fi
  fi

  # --- 既存をバックアップ ---
  if [ -f "$dst" ]; then
    cp -p "$dst" "$BAK_DIR/${name}.${ts}.bak"
  fi

  # --- 配置 + 所有者設定 ---
  install -o www-data -g www-data -m 644 "$src" "$dst"
  echo "[OK] deployed: $name  (md5=$(md5sum "$dst" | cut -d' ' -f1))"
  deployed=$((deployed+1))
done

echo "[done] $deployed file(s) deployed. backups in $BAK_DIR (ts=$ts)"
