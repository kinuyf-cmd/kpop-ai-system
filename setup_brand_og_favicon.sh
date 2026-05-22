#!/usr/bin/env bash
# og:image 既定 + favicon(site_icon)を本番に設定する。
# ブランド画像: assets/brand/og-default.png (1200x630) / favicon-512.png (512x512)
#
# 【段階実行】まず dry-run で現状と変更計画を確認 → 問題なければ APPLY=1 で適用。
#   確認: sudo bash setup_brand_og_favicon.sh
#   適用: sudo APPLY=1 bash setup_brand_og_favicon.sh
#
# 本番稼働中のため、AIOSEO は DB直書きせず option get→Python安全マージ→option update。
# 既存の aioseo_options 他キーは保持(featured優先 fallback + 既定画像のみ変更)。
set -uo pipefail
WP="sudo -u www-data wp --path=/var/www/wp_stg"
DIR="$(cd "$(dirname "$0")" && pwd)/assets/brand"
APPLY="${APPLY:-0}"

echo "=== モード: $([ "$APPLY" = 1 ] && echo 'APPLY(適用)' || echo 'DRY-RUN(確認のみ)') ==="

# ---- 1. 画像を media に import(既存なら再利用) ----
import_media () {
  local file="$1" title="$2"
  local existing
  existing=$($WP post list --post_type=attachment --name="$(basename "${file%.*}")" --field=ID 2>/dev/null | head -1 || true)
  if [ -n "$existing" ]; then echo "$existing"; return; fi
  if [ "$APPLY" = 1 ]; then
    $WP media import "$file" --title="$title" --porcelain 2>/dev/null
  else
    echo "DRYRUN_ID"
  fi
}

echo "--- 画像 import ---"
OG_ID=$(import_media "$DIR/og-default.png" "KPOP JOURNAL OG Default")
echo "  og-default.png -> attachment ID=$OG_ID"
FAV_ID=$(import_media "$DIR/favicon-512.png" "KPOP JOURNAL Favicon")
echo "  favicon-512.png -> attachment ID=$FAV_ID"

# ---- 2. favicon (site_icon) ----
echo "--- site_icon(favicon) ---"
echo "  現在: $($WP option get site_icon 2>/dev/null || echo 0)"
if [ "$APPLY" = 1 ] && [ "$FAV_ID" != "DRYRUN_ID" ]; then
  $WP option update site_icon "$FAV_ID" >/dev/null && echo "  → site_icon=$FAV_ID に設定"
else
  echo "  (DRY-RUN: site_icon=$FAV_ID に設定予定)"
fi

# ---- 3. AIOSEO ソーシャル既定 og:image(安全マージ) ----
echo "--- AIOSEO social 既定 og:image ---"
CUR=$($WP option get aioseo_options --format=json 2>/dev/null || echo '{}')
OG_URL=$([ "$OG_ID" != "DRYRUN_ID" ] && $WP post get "$OG_ID" --field=guid 2>/dev/null || echo "<og-default URL>")
echo "  既定 og:image URL 予定: $OG_URL"

python3 - "$CUR" "$OG_URL" "$APPLY" <<'PY' > /tmp/aioseo_new.json
import sys,json
try:
    cur=json.loads(sys.argv[1]) if sys.argv[1].strip() else {}
except Exception:
    cur={}
if not isinstance(cur,dict):
    sys.stderr.write("  ✗ aioseo_options が dict として取得できない(空/失敗)。diag_aioseo_structure.sh で構造確認を先に。\n")
    cur={}
og_url=sys.argv[2]; apply=sys.argv[3]=="1"
soc=cur.setdefault("social",{})
fb=soc.setdefault("facebook",{})
gen=fb.setdefault("general",{})
# 投稿: featured優先(default)、無ければ既定画像
before={k:gen.get(k) for k in ("defaultImageSourcePosts","defaultImagePosts")}
gen["defaultImageSourcePosts"]="featured"   # featured image 優先
gen["defaultImagePosts"]=og_url             # fallback 既定画像
hp=fb.setdefault("homePage",{})
hp_before=hp.get("image")
hp["image"]=og_url                          # トップは既定画像
# twitter は facebook 設定を継承(useOgData)させる
tw=soc.setdefault("twitter",{}); twg=tw.setdefault("general",{})
twg["useOgData"]=True
sys.stderr.write(f"  変更前 posts: {before}\n  変更前 home.image: {hp_before}\n")
sys.stderr.write("  変更後: posts.source=featured / posts.fallback=既定 / home=既定 / twitter.useOgData=true\n")
print(json.dumps(cur,ensure_ascii=False))
PY

if [ "$APPLY" = 1 ]; then
  $WP option update aioseo_options "$(cat /tmp/aioseo_new.json)" --format=json >/dev/null \
    && echo "  → AIOSEO social 既定を更新" || echo "  ✗ AIOSEO 更新失敗(構造要確認)"
  $WP cache flush >/dev/null 2>&1 || true
else
  echo "  (DRY-RUN: 上記の変更を適用予定。生成JSON=/tmp/aioseo_new.json をレビュー可)"
fi
rm -f /tmp/aioseo_new.json

echo
echo "=== 完了。APPLY後の確認: ==="
echo "  curl -s https://www.kpopjournal.tokyo/stayc-2026-fan-concert-tour-stay-closer/ | grep og:image"
echo "  curl -s https://www.kpopjournal.tokyo/ | grep -E 'og:image|favicon|shortcut'"
