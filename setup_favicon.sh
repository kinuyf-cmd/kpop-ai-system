#!/usr/bin/env bash
# favicon(site_icon)のみを設定する。AIOSEO 構造に非依存(wp option site_icon)。
# ブランドアイコン: assets/brand/favicon-512.png (512x512)
#   確認: sudo bash setup_favicon.sh
#   適用: sudo APPLY=1 bash setup_favicon.sh
set -uo pipefail
WP="sudo -u www-data wp --path=/var/www/wp_stg"
DIR="$(cd "$(dirname "$0")" && pwd)/assets/brand"
APPLY="${APPLY:-0}"
echo "=== favicon 設定: $([ "$APPLY" = 1 ] && echo APPLY || echo DRY-RUN) ==="

echo "現在 site_icon: $($WP option get site_icon 2>/dev/null || echo 0)"
# 既存 import 済みか(タイトルで照合)
FAV_ID=$($WP post list --post_type=attachment --s='KPOP JOURNAL Favicon' --field=ID 2>/dev/null | head -1 || true)
if [ -z "$FAV_ID" ]; then
  if [ "$APPLY" = 1 ]; then
    FAV_ID=$($WP media import "$DIR/favicon-512.png" --title="KPOP JOURNAL Favicon" --porcelain 2>/dev/null)
    echo "  favicon import -> ID=$FAV_ID"
  else
    echo "  (DRY-RUN: favicon-512.png を import 予定)"
  fi
else
  echo "  既存 favicon attachment ID=$FAV_ID を再利用"
fi

if [ "$APPLY" = 1 ] && [ -n "${FAV_ID:-}" ]; then
  $WP option update site_icon "$FAV_ID" >/dev/null && echo "  → site_icon=$FAV_ID 設定"
  $WP cache flush >/dev/null 2>&1 || true
else
  echo "  (DRY-RUN: site_icon=<favicon ID> に設定予定)"
fi
echo "確認: curl -s https://www.kpopjournal.tokyo/ | grep -iE 'rel=.icon|site_icon|favicon'"
