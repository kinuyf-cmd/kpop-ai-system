#!/usr/bin/env bash
# ホームページの twitter:card を summary → summary_large_image に揃える。
# 記事側(general.defaultCardType)は既に summary_large_image だが、
# twitter.homePage.cardType が "summary" に明示上書きされており、
# トップを X でシェアすると画像が小さく表示される。これを是正する。
#
# AIOSEO 4.9.x: aioseo_options は二重エンコードJSON。setup_og_default.sh と同方式。
# 安全策: (1)適用前に option をバックアップ (2)二重デコード→1キーのみ変更→二重エンコードで
#         元の保存形式を厳密再現 (3)dry-run で 変更前/変更後 を表示。
#   確認: sudo bash setup_twitter_home_largecard.sh
#   適用: sudo APPLY=1 bash setup_twitter_home_largecard.sh
set -uo pipefail
WP="sudo -u www-data wp --path=/var/www/wp_stg"
BK=/home/aiuser/.kpop_recovery
APPLY="${APPLY:-0}"
echo "=== twitter:home large-card 設定: $([ "$APPLY" = 1 ] && echo APPLY || echo DRY-RUN) ==="

RAW_FILE=$(mktemp /tmp/aioseo_raw.XXXXXX.json)
$WP option get aioseo_options --format=json > "$RAW_FILE" 2>/dev/null || true
echo "  option 取得バイト長: $(wc -c < "$RAW_FILE")"

if [ "$APPLY" = 1 ]; then
  ts=$(date +%Y%m%d_%H%M%S)
  cp "$RAW_FILE" "$BK/aioseo_options.backup_$ts.json"
  echo "  バックアップ: $BK/aioseo_options.backup_$ts.json"
fi

RAW_FILE="$RAW_FILE" python3 - > /tmp/aioseo_payload.txt <<'PY'
import sys,os,json
raw=open(os.environ["RAW_FILE"]).read()

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

tw=d.setdefault("social",{}).setdefault("twitter",{})
hp=tw.setdefault("homePage",{})
before=hp.get("cardType")
sys.stderr.write(f"  [前] twitter.homePage.cardType={before!r}\n")
if before == "summary_large_image":
    sys.stderr.write("  既に summary_large_image。変更不要。\n"); print("NOCHANGE"); sys.exit(0)
hp["cardType"]="summary_large_image"
sys.stderr.write("  [後] twitter.homePage.cardType='summary_large_image'\n")

inner=json.dumps(d,ensure_ascii=False,separators=(',',':'))
out=json.dumps(inner) if depth==2 else inner
print(out)
PY

PAYLOAD=$(cat /tmp/aioseo_payload.txt)
if [ "$PAYLOAD" = "NOCHANGE" ]; then
  echo "  変更不要(既に large card)。"; rm -f /tmp/aioseo_payload.txt "$RAW_FILE"; exit 0
fi
if [ "$PAYLOAD" = "ABORT" ] || [ -z "$PAYLOAD" ]; then
  echo "  ✗ ペイロード生成失敗。適用しない。"; rm -f /tmp/aioseo_payload.txt "$RAW_FILE"; exit 1
fi

if [ "$APPLY" = 1 ]; then
  printf '%s' "$PAYLOAD" | $WP option update aioseo_options --format=json 2>/dev/null \
    && echo "  → aioseo_options 更新成功" || echo "  ✗ 更新失敗"
  $WP cache flush >/dev/null 2>&1 || true
else
  echo "  (DRY-RUN: twitter.homePage.cardType を summary_large_image に更新予定)"
fi
rm -f /tmp/aioseo_payload.txt "$RAW_FILE"
echo "確認: curl -s https://www.kpopjournal.tokyo/ | grep -i 'twitter:card'"
