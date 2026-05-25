#!/usr/bin/env bash
# fix_advertise_email.sh — /advertise/ ページ(ID 1405)の問い合わせメールを
#   kinu.yf@gmail.com → kpopjournal.biz@gmail.com に置換する。
#   出現3箇所(mailto link href + 表示テキスト + <form action="mailto:...">)を一括置換。
#   ?subject= パラメータ・フォーム構造は保持。Python で literal 置換しSQLは使わない。
#   post_content更新は直接渡し(stdin piping 禁止=本文破壊事故の教訓)。backupは/tmp。
#   owner 実行: sudo -u www-data bash tools/config/fix_advertise_email.sh
set -uo pipefail
WP="wp --path=/var/www/wp_stg"
PID=1405
OLD="kinu.yf@gmail.com"
NEW="kpopjournal.biz@gmail.com"

echo "================ /advertise/ メール置換 ================"
content="$($WP post get "$PID" --field=post_content 2>/dev/null)"
if [ -z "$content" ]; then echo "[FATAL] post $PID の content取得失敗"; exit 1; fi
before="$(printf '%s' "$content" | grep -c "$OLD" || true)"
echo "  置換前: '$OLD' 出現 $before 箇所"
if [ "$before" = "0" ]; then echo "  既に $OLD は無し(置換済み or 不在)→ 終了"; exit 0; fi

# /tmp にバックアップ(www-data書込可)
bak="/tmp/advertise_1405_backup_$(date +%s).html"
printf '%s' "$content" > "$bak"; echo "  backup: $bak"

# literal 置換(mailto/表示テキスト/form action 全て同一文字列なので一括)
new="$(printf '%s' "$content" | python3 -c "import sys; sys.stdout.write(sys.stdin.read().replace('$OLD','$NEW'))")"
after_old="$(printf '%s' "$new" | grep -c "$OLD" || true)"
after_new="$(printf '%s' "$new" | grep -c "$NEW" || true)"

# 直接渡しで更新
$WP post update "$PID" --post_content="$new" >/dev/null && echo "  ✅ /advertise/ 更新"

echo ""
echo "================ 検証 ================"
v="$($WP post get "$PID" --field=post_content 2>/dev/null)"
echo "  旧アドレス残存: $(printf '%s' "$v" | grep -c "$OLD" || true) 箇所(0が正)"
echo "  新アドレス: $(printf '%s' "$v" | grep -c "$NEW" || true) 箇所(=置換前の出現数 $before)"
echo "  ?subject= 保持: $(printf '%s' "$v" | grep -c 'subject=' || true)(1以上が正)"
echo "  form action 保持: $(printf '%s' "$v" | grep -c 'action="mailto:' || true)(1が正)"
echo "================ 完了 ================"
