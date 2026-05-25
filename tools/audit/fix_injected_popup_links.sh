#!/usr/bin/env bash
# fix_injected_popup_links.sh — K-POP速報記事の本文に誤注入された無関係 popup リンク
#   (例: 「単一メディア速報…」免責文末尾に癒着した "Favori Gel ファボリゲル 韓国ジェルネイル" 等)
#   を全該当記事から除去する。RED TEAM監査(2026-05-25)で12記事に混入を検出。
#
#   方式: 各記事の post_content から、免責文に続く <a href=".../popup-...">…</a>(無関係)を削除。
#   安全策: dry-run 既定。--apply で実行。実行前に各記事を wp post get で .bak エクスポート。
#   owner 実行: sudo -u www-data bash tools/perf/fix_injected_popup_links.sh        # dry-run
#               sudo -u www-data bash tools/perf/fix_injected_popup_links.sh --apply
set -uo pipefail
WP="wp --path=/var/www/wp_stg"
APPLY="${1:-}"
BAKDIR="/home/aiuser/.kpop_recovery/inject_link_backup_$(date +%Y%m%d_%H%M%S)"

# 監査で検出した12 slug(/tmp/audit/inject_hits.json 由来)。slug で post を引く。
SLUGS=(
  akmu-circle-chart-triple-crown
  illits-wonhee-drinking-criticism
  itzy-morocco-mawazine-headliner
  le-sserafim-new-album-pureflow
  mami-matsu-silent-voices-cannes-award
  monsta-x-keyhun-lazy-day-debut
  nmixx-heavy-serenade-m-countdown
  seventeen-fanmeeting-kyocera-dome
  seventeen-japan-live-broadcast-180000
  stray-kids-seungmin-governors-ball-absence
  treasure-if-i-mini4th-album
  txt-youngjoon-girlgroup-cover-debate
)

[ "$APPLY" = "--apply" ] && mkdir -p "$BAKDIR"
echo "================ 誤注入 popup リンク除去 ($([ "$APPLY" = "--apply" ] && echo APPLY || echo DRY-RUN)) ================"
fixed=0; skipped=0
for slug in "${SLUGS[@]}"; do
  pid="$($WP post list --post_type=post --name="$slug" --field=ID 2>/dev/null | head -1)"
  if [ -z "$pid" ]; then echo "  [skip] slug未検出: $slug"; skipped=$((skipped+1)); continue; fi
  content="$($WP post get "$pid" --field=post_content 2>/dev/null)"
  # 除去対象: 免責文に続く「 <a ...popup-...>…(ジェルネイル等)…</a>」を、リンクと直前の空白ごと削除。
  # 免責文(単一メディア速報…可能性があります。)自体は保持する。
  new="$(printf '%s' "$content" | python3 -c '
import sys,re
c=sys.stdin.read()
# 免責文の直後に癒着した無関係popupリンク(同段落内)を除去
pat=re.compile(r"(変更される可能性があります。)\s*<a href=\"https://www\.kpopjournal\.tokyo/popup-[^\"]+\"[^>]*>[^<]*</a>")
c2=pat.sub(r"\1", c)
sys.stdout.write(c2)
')"
  if [ "$new" = "$content" ]; then echo "  [no-match] post $pid ($slug) 対象リンクなし"; skipped=$((skipped+1)); continue; fi
  if [ "$APPLY" = "--apply" ]; then
    printf '%s' "$content" > "$BAKDIR/${pid}_${slug}.html"   # バックアップ
    printf '%s' "$new" | $WP post update "$pid" --post_content=- >/dev/null && echo "  [fixed] post $pid ($slug)" && fixed=$((fixed+1))
  else
    echo "  [would-fix] post $pid ($slug)  (注入リンク1件除去予定)"
    fixed=$((fixed+1))
  fi
done
echo "  対象 $fixed / skip $skipped"
[ "$APPLY" = "--apply" ] && echo "  バックアップ: $BAKDIR"
[ "$APPLY" != "--apply" ] && echo "  ※ dry-run。実行は末尾に --apply を付けて再実行。"
echo "================ 完了 ================"
