#!/usr/bin/env bash
# set_contact_email.sh — 問い合わせ宛先を kpopjournal.biz@gmail.com に統一する。
#   ① WP管理者メール admin_email を更新(通知/システムメールの宛先)
#   ② /contact/ ページ(post 55)に公開問い合わせメールを掲載(現在は「準備中」placeholder)
#   現状: admin_email=kinu.yf@gmail.com / new_admin_email=kpopjournal.biz@gmail.com(変更保留中)。
#   wp option update は WordPress の確認メール承認ステップを省いて即時反映する(owner判断で実行)。
#   owner 実行: sudo -u www-data bash tools/config/set_contact_email.sh
set -uo pipefail
WP="wp --path=/var/www/wp_stg"
NEW="kpopjournal.biz@gmail.com"
PAGE_ID=55
PAGE_HTML="$(cd "$(dirname "$0")" && pwd)/contact_page.html"

echo "================ 問い合わせ宛先の変更 ================"

echo "--- ① WP管理者メール(admin_email)---"
cur="$($WP option get admin_email 2>/dev/null || true)"
echo "  現在: $cur"
if [ "$cur" = "$NEW" ]; then
  echo "  既に $NEW(変更なし)"
else
  $WP option update admin_email "$NEW" >/dev/null && echo "  ✅ admin_email → $NEW"
  # 保留中の new_admin_email をクリア(確認待ち状態を解消)
  $WP option delete new_admin_email >/dev/null 2>&1 && echo "  保留中 new_admin_email をクリア" || true
fi

echo ""
echo "--- ② /contact/ ページに公開問い合わせメール掲載 ---"
[ -f "$PAGE_HTML" ] || { echo "  [FATAL] $PAGE_HTML が無い"; exit 1; }
# 既存contentをバックアップ(www-data書込可の /tmp 配下=前回の権限教訓)
bak="/tmp/contact_page_55_backup_$(date +%s).html"
$WP post get "$PAGE_ID" --field=post_content > "$bak" 2>/dev/null && echo "  旧content backup: $bak"
# 直接渡しで更新(stdin piping は使わない=本文破壊事故の教訓)
newcontent="$(cat "$PAGE_HTML")"
$WP post update "$PAGE_ID" --post_content="$newcontent" >/dev/null && echo "  ✅ /contact/ 更新"

echo ""
echo "================ 検証 ================"
echo "  admin_email: $($WP option get admin_email 2>/dev/null)"
echo "  new_admin_email(保留): $($WP option get new_admin_email 2>/dev/null || echo '(なし=クリア済)')"
echo "  /contact/ にメール掲載: $($WP post get $PAGE_ID --field=post_content 2>/dev/null | grep -c "$NEW") 箇所"
echo "================ 完了 ================"
