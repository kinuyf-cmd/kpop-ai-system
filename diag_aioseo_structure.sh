#!/usr/bin/env bash
# AIOSEO の og:image 既定がどのキーに入るかを read-only で確定する(変更なし)。
# 実行: sudo bash diag_aioseo_structure.sh
# 機密は出ない(AIOSEO options に認証値は無い)。
set -uo pipefail
WP="sudo -u www-data wp --path=/var/www/wp_stg"

echo "===== 1. aioseo_options が取得できるか / 型 ====="
RAW=$($WP option get aioseo_options --format=json 2>&1 || true)
echo "  先頭120字: $(printf '%s' "$RAW" | head -c 120)"
echo "  バイト長: $(printf '%s' "$RAW" | wc -c)"

echo
echo "===== 2. social 配下のキー構造(image 関連を全列挙) ====="
printf '%s' "$RAW" | python3 -c "
import sys,json
try:
    d=json.load(sys.stdin)
except Exception as e:
    print('  JSONパース不可:',e); sys.exit(0)
if not isinstance(d,dict):
    print('  トップが dict でない:',type(d).__name__); sys.exit(0)
def walk(o,path=''):
    if isinstance(o,dict):
        for k,v in o.items():
            p=f'{path}.{k}' if path else k
            if isinstance(v,(dict,list)): walk(v,p)
            else:
                kl=k.lower()
                if any(s in kl for s in ('image','source','og','twitter','default')):
                    print(f'  {p} = {repr(v)[:80]}')
    elif isinstance(o,list):
        for i,v in enumerate(o[:3]): walk(v,f'{path}[{i}]')
print('--- image/source/og/default を含むキー ---')
walk(d.get('social',{}),'social')
print('--- social 直下のトップキー ---')
print('  ', list(d.get('social',{}).keys()))
fb=d.get('social',{}).get('facebook',{})
if isinstance(fb,dict):
    print('--- social.facebook 直下 ---')
    print('  ', list(fb.keys()))
    for sub in ('general','homePage'):
        if sub in fb and isinstance(fb[sub],dict):
            print(f'  social.facebook.{sub} keys:', list(fb[sub].keys()))
"

echo
echo "===== 3. AIOSEO 専用テーブル(wp_aioseo_posts)に og_image カラムがあるか ====="
$WP db query "SHOW COLUMNS FROM wp_aioseo_posts LIKE 'og_image%';" 2>/dev/null || echo "  (テーブル無し or 参照不可)"

echo
echo "===== 4. AIOSEO バージョン ====="
$WP plugin get all-in-one-seo-pack --field=version 2>/dev/null || $WP plugin list 2>/dev/null | grep -i aioseo || echo "  (取得不可)"
