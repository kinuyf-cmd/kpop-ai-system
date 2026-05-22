#!/usr/bin/env bash
# AIOSEO ソーシャル既定 og:image を設定(記事=featured優先/fallback既定、home=既定)。
# AIOSEO 4.9.x: aioseo_options は二重エンコードJSON(option get は文字列を返す)。
# 安全策: (1)適用前に option を /home/aiuser/.kpop_recovery にバックアップ
#         (2)二重デコード→マージ→二重エンコードで元の保存形式を厳密再現
#         (3)dry-run で 変更前/変更後 を必ず表示
#   確認: sudo bash setup_og_default.sh
#   適用: sudo APPLY=1 bash setup_og_default.sh
set -uo pipefail
WP="sudo -u www-data wp --path=/var/www/wp_stg"
DIR="$(cd "$(dirname "$0")" && pwd)/assets/brand"
BK=/home/aiuser/.kpop_recovery
APPLY="${APPLY:-0}"
echo "=== og:image 既定設定: $([ "$APPLY" = 1 ] && echo APPLY || echo DRY-RUN) ==="

# OG画像 import / 既存再利用
OG_ID=$($WP post list --post_type=attachment --s='KPOP JOURNAL OG Default' --field=ID 2>/dev/null | head -1 || true)
if [ -z "$OG_ID" ]; then
  if [ "$APPLY" = 1 ]; then
    OG_ID=$($WP media import "$DIR/og-default.png" --title="KPOP JOURNAL OG Default" --porcelain 2>/dev/null)
    echo "  OG画像 import -> ID=$OG_ID"
  else
    OG_ID=""; echo "  (DRY-RUN: og-default.png を import 予定)"
  fi
else
  echo "  既存 OG画像 attachment ID=$OG_ID を再利用"
fi
OG_URL=""
[ -n "$OG_ID" ] && OG_URL=$($WP post get "$OG_ID" --field=guid 2>/dev/null || echo "")
[ -z "$OG_URL" ] && OG_URL="https://www.kpopjournal.tokyo/wp-content/uploads/OG-DEFAULT(import後に確定)"
echo "  既定 og:image URL: $OG_URL"

# option を --format=json で取得(diagで実証: 二重エンコードJSON文字列が返る、9537B)
RAW=$($WP option get aioseo_options --format=json 2>/dev/null || true)
echo "  option 取得バイト長: $(printf '%s' "$RAW" | wc -c)"

# バックアップ(適用時のみ)
if [ "$APPLY" = 1 ]; then
  ts=$(date +%Y%m%d_%H%M%S)
  printf '%s' "$RAW" > "$BK/aioseo_options.backup_$ts.json"
  echo "  バックアップ: $BK/aioseo_options.backup_$ts.json"
fi

printf '%s' "$RAW" | OG_URL="$OG_URL" APPLY="$APPLY" python3 - > /tmp/aioseo_payload.txt <<'PY'
import sys,os,json
raw=sys.stdin.read()
og=os.environ["OG_URL"]; apply=os.environ["APPLY"]=="1"

# 二重デコード: option値が「JSON文字列」なら2回、生dictなら1回
def decode(r):
    try:
        x=json.loads(r)
    except Exception as e:
        sys.stderr.write(f"  ✗ 1st json.loads 失敗: {e}\n"); return None,0
    if isinstance(x,str):
        try:
            return json.loads(x),2
        except Exception as e:
            sys.stderr.write(f"  ✗ 2nd json.loads 失敗: {e}\n"); return None,0
    return x,1

d,depth=decode(raw)
if not isinstance(d,dict):
    sys.stderr.write("  ✗ dict 化できず。中断。\n"); print("ABORT"); sys.exit(0)
sys.stderr.write(f"  デコード深度: {depth}(2=二重エンコード)\n")

soc=d.setdefault("social",{}); fb=soc.setdefault("facebook",{}); gen=fb.setdefault("general",{})
hp=fb.setdefault("homePage",{})
# 変更前
sys.stderr.write(f"  [前] defaultImageSourcePosts={gen.get('defaultImageSourcePosts')!r} defaultImagePosts={gen.get('defaultImagePosts')!r} homePage.image={hp.get('image')!r}\n")
# 変更: 記事=featured優先・fallback既定 / home=既定 / twitterはOG継承
gen["defaultImageSourcePosts"]="featured"
gen["defaultImagePosts"]=og
hp["image"]=og; hp.setdefault("imageType","custom")
tw=soc.setdefault("twitter",{}); twg=tw.setdefault("general",{}); twg["useOgData"]=True
sys.stderr.write(f"  [後] defaultImageSourcePosts='featured' defaultImagePosts='{og}' homePage.image='{og}' twitter.useOgData=True\n")

# 再エンコード: depth=2 なら inner(JSON文字列)を1段ラップ → wp --format=json が1段デコードしてDB格納
inner=json.dumps(d,ensure_ascii=False,separators=(',',':'))
out=json.dumps(inner) if depth==2 else inner
print(out)
PY

PAYLOAD=$(cat /tmp/aioseo_payload.txt)
if [ "$PAYLOAD" = "ABORT" ] || [ -z "$PAYLOAD" ]; then
  echo "  ✗ ペイロード生成失敗。適用しない。"; rm -f /tmp/aioseo_payload.txt; exit 1
fi

if [ "$APPLY" = 1 ]; then
  # --format=json で書く: wp が1段デコード → DBにはJSON文字列(元の保存形式)が入る
  printf '%s' "$PAYLOAD" | $WP option update aioseo_options --format=json 2>/dev/null \
    && echo "  → aioseo_options 更新成功" || echo "  ✗ 更新失敗"
  $WP cache flush >/dev/null 2>&1 || true
else
  echo "  (DRY-RUN: 上記[後]の値で更新予定。元形式=二重エンコードを厳密再現)"
fi
rm -f /tmp/aioseo_payload.txt
echo "確認: curl -s https://www.kpopjournal.tokyo/stayc-2026-fan-concert-tour-stay-closer/ | grep -i og:image"
