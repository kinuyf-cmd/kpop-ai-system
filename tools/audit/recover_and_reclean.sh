#!/usr/bin/env bash
# recover_and_reclean.sh — 緊急復旧。fix_injected_popup_links.sh の stdin-piping バグ
#   ('--post_content=-' が literal '-' をセット)で12記事の本文が "-" に破壊された事故の復旧。
#   各記事を「破壊前の最新revision」から本文復元し、その後 popup リンクを正しい方法で再除去する。
#
#   破壊時刻=16:10台。それより前の最新revision(=破壊前の正本)から post_content を取得し、
#   wp post update --post_content="<value>"(直接渡し。stdin piping は使わない)で復元。
#   復元後、無関係 popup/コスメリンクのみ正規表現で除去(本文は保持)。
#   owner 実行: sudo -u www-data bash tools/audit/recover_and_reclean.sh
set -uo pipefail
WP="wp --path=/var/www/wp_stg"
# post_id を列挙(破壊された12記事)
PIDS=(660 1118 1073 1263 1296 1302 654 1245 1219 1080 1226 1157)

echo "================ 緊急復旧 + 再クリーン(12記事)================"
ok=0; fail=0
for pid in "${PIDS[@]}"; do
  # 破壊前の最新revision(post_date が 16:1 を含まない=破壊前)を1件取得
  rev="$($WP post list --post_type=revision --post_parent="$pid" --fields=ID,post_date --format=csv 2>/dev/null \
        | grep -vi '^ID' | grep -v ' 16:1' | head -1 | cut -d, -f1)"
  if [ -z "$rev" ]; then echo "  [skip] post $pid: 復旧元revision無し"; fail=$((fail+1)); continue; fi
  # 復旧元本文を取得
  orig="$($WP post get "$rev" --field=post_content 2>/dev/null)"
  if [ "${#orig}" -lt 100 ]; then echo "  [skip] post $pid: rev $rev も短い(${#orig}字)=復旧不可"; fail=$((fail+1)); continue; fi
  # popup/コスメ無関係リンクを除去(本文保持)
  cleaned="$(printf '%s' "$orig" | python3 -c '
import sys,re
c=sys.stdin.read()
pat=re.compile(
  r"\s*<a href=\"https://www\.kpopjournal\.tokyo/(?:popup-[^\"]+|[a-z0-9]*blackpink[^\"]*|twice[^\"]*)\"[^>]*>"
  r"[^<]*(?:ファボリゲル|ジェルネイル|コスメ|ガラス肌|ネイル|Gel|聖水)[^<]*</a>")
sys.stdout.write(pat.sub("", c))
')"
  # 直接渡しで更新(stdin piping は使わない=今回のバグ回避)
  if $WP post update "$pid" --post_content="$cleaned" >/dev/null 2>&1; then
    newlen="$($WP post get "$pid" --field=post_content 2>/dev/null | wc -c)"
    pdrop="$(printf '%s' "$cleaned" | grep -c 'popup-favorigel' || true)"
    echo "  [recovered] post $pid ← rev $rev  本文${#orig}→クリーン後 ${newlen}字  popup残=$pdrop"
    ok=$((ok+1))
  else
    echo "  [FAIL] post $pid: update失敗"; fail=$((fail+1))
  fi
done
echo "  復旧 $ok / 失敗 $fail"
echo "================ 検証 ================"
for pid in "${PIDS[@]}"; do
  len="$($WP post get "$pid" --field=post_content 2>/dev/null | wc -c)"
  pop="$($WP post get "$pid" --field=post_content 2>/dev/null | grep -c 'popup-favorigel' || true)"
  flag="OK"; [ "$len" -lt 100 ] && flag="🔴まだ破壊"; [ "$pop" -gt 0 ] && flag="🟡popup残存"
  echo "  post $pid: ${len}字 popup=$pop → $flag"
done
echo "================ 完了 ================"
