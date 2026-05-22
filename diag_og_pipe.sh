#!/usr/bin/env bash
# $RAW がどこで失われるか切り分け(read-only)。
# 実行: sudo bash diag_og_pipe.sh
set -uo pipefail
WP="sudo -u www-data wp --path=/var/www/wp_stg"

echo "=== A. option get を一時ファイルに直接保存(シェル変数を経由しない) ==="
$WP option get aioseo_options --format=json > /tmp/aioseo_raw.json 2>/dev/null
echo "  /tmp/aioseo_raw.json バイト長: $(wc -c < /tmp/aioseo_raw.json)"
echo "  先頭60字: $(head -c 60 /tmp/aioseo_raw.json)"

echo
echo "=== B. ファイルから直接 Python に食わせてデコード(変数経由しない) ==="
python3 - <<'PY'
import json
raw=open('/tmp/aioseo_raw.json').read()
print("  Pythonが読んだバイト長:", len(raw))
print("  先頭40字 repr:", repr(raw[:40]))
def decode(r):
    x=json.loads(r)
    return (json.loads(x),2) if isinstance(x,str) else (x,1)
try:
    d,depth=decode(raw)
    print("  デコード深度:", depth, "/ topキー:", list(d.keys())[:6] if isinstance(d,dict) else type(d).__name__)
    g=d.get("social",{}).get("facebook",{}).get("general",{})
    print("  [前] defaultImageSourcePosts:", repr(g.get("defaultImageSourcePosts")))
    print("  [前] defaultImagePosts:", repr(g.get("defaultImagePosts")))
    hp=d.get("social",{}).get("facebook",{}).get("homePage",{})
    print("  [前] homePage.image:", repr(hp.get("image")))
except Exception as e:
    print("  デコード失敗:", e)
PY

echo
echo "=== C. 変数経由 + printf の往路を再現(壊れるか確認) ==="
RAW=$($WP option get aioseo_options --format=json 2>/dev/null)
echo "  シェル変数 RAW のバイト長(wc): $(printf '%s' "$RAW" | wc -c)"
echo "  printf|python が受け取るバイト長:"
printf '%s' "$RAW" | python3 -c "import sys; d=sys.stdin.read(); print('   stdin len =', len(d)); print('   先頭40 repr:', repr(d[:40]))"
rm -f /tmp/aioseo_raw.json
