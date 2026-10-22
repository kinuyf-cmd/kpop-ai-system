#!/bin/bash
# php8.3-fpm(WordPress=kpopjournal.tokyo/stg)を自分の場所の外から隔離する。
# 2026-10-22 owner決定・golfport T1 依頼。sudo bash で実行。失敗時は自動で元に戻す。
#   - pool: open_basedir を WP ルート + 一時/セッションのみに、外部コマンド系関数を無効化
#   - systemd: ProtectHome=yes(/home を見えなくする)/ProtectSystem=full/PrivateTmp/NoNewPrivileges
# 前提: テーマ functions.php は sidebar_ad.json をテーマ同梱の写しから読む(deploy 済)。
set -u
POOL=/etc/php/8.3/fpm/pool.d/www.conf
DROPIN_DIR=/etc/systemd/system/php8.3-fpm.service.d
DROPIN=$DROPIN_DIR/hardening.conf
THEME=/var/www/wp_stg/wp-content/themes/generatepress-kpop
REPO=/home/aiuser/kpop-ai-system
TS=$(date +%Y%m%d_%H%M%S)
URLS="https://www.kpopjournal.tokyo/ https://www.kpopjournal.tokyo/category/popup/ https://www.kpopjournal.tokyo/?s=IVE https://www.kpopjournal.tokyo/wp-json/wp/v2/posts?per_page=1"

[ "$(id -u)" -eq 0 ] || { echo "sudo bash で実行してください"; exit 1; }

check_site() {
  local ok=0 u code
  for u in $URLS; do
    case "$u" in *\?*) sep='&' ;; *) sep='?' ;; esac
    code=$(curl -s -o /dev/null -w '%{http_code}' "${u}${sep}nc=$TS" 2>/dev/null)
    [ "$code" = 200 ] || { echo "  NG $code $u"; ok=1; continue; }
    echo "  OK $code $u"
  done
  # サイドバーA8広告(素材を読めているか)
  local a8; a8=$(curl -s "https://www.kpopjournal.tokyo/?nc=$TS" | grep -c 'a8.net')
  echo "  A8広告リンク数: $a8 (適用前は3)"; [ "$a8" -ge 1 ] || ok=1
  return $ok
}

rollback() {
  echo "!! 失敗 → 元に戻します"
  cp -a "$POOL.bak_$TS" "$POOL"
  rm -f "$DROPIN"
  systemctl daemon-reload
  systemctl restart php8.3-fpm
  check_site; exit 1
}

echo "== 0. 適用前の確認"; check_site || { echo "適用前から異常。中止"; exit 1; }

echo "== 1. 広告素材の写しをテーマへ"
install -o www-data -g www-data -m 0644 "$REPO/config/affiliate/sidebar_ad.json" "$THEME/sidebar_ad.json"

echo "== 2. pool 設定"
cp -a "$POOL" "$POOL.bak_$TS"
sed -i '/^; kpop-hardening BEGIN/,/^; kpop-hardening END/d' "$POOL"
cat >> "$POOL" <<'EOF'
; kpop-hardening BEGIN (2026-10-22)
php_admin_value[open_basedir] = /var/www/wp_stg/:/tmp/:/var/lib/php/sessions/:/usr/share/php/
php_admin_value[disable_functions] = exec,passthru,shell_exec,system,proc_open,popen,pcntl_exec
; kpop-hardening END
EOF

echo "== 3. systemd drop-in"
mkdir -p "$DROPIN_DIR"
cat > "$DROPIN" <<'EOF'
# kpop-hardening (2026-10-22): WordPress が破られても /home・/root 等を読ませない
[Service]
ProtectHome=yes
ProtectSystem=full
PrivateTmp=yes
NoNewPrivileges=yes
EOF

echo "== 4. 構文チェック → 再起動"
php-fpm8.3 -t || rollback
systemctl daemon-reload
systemctl restart php8.3-fpm || rollback
sleep 2

echo "== 5. 適用後の確認"
check_site || rollback
echo "  有効値:"; systemctl show php8.3-fpm -p ProtectHome -p ProtectSystem -p PrivateTmp -p NoNewPrivileges
echo "== 差分(pool)"; diff "$POOL.bak_$TS" "$POOL"
echo "== 完了。戻すとき: cp $POOL.bak_$TS $POOL && rm $DROPIN && systemctl daemon-reload && systemctl restart php8.3-fpm"
