#!/usr/bin/env bash
# AIOSEO ソーシャル既定 og:image 設定の現状を read-only 確認(変更なし)。
# 実行: sudo bash audit_aioseo_social.sh
set -uo pipefail
WP="sudo -u www-data wp --path=/var/www/wp_stg"

echo "===== AIOSEO ソーシャル設定(aioseo_options) ====="
# AIOSEO は options テーブルの 'aioseo_options' に JSON で持つ
$WP option get aioseo_options --format=json 2>/dev/null \
  | python3 -c "import sys,json
try:
  d=json.load(sys.stdin)
  soc=d.get('social',{})
  fb=soc.get('facebook',{}); 
  gen=fb.get('general',{}) if isinstance(fb,dict) else {}
  print('  social.facebook.general.defaultImageSourcePosts:', gen.get('defaultImageSourcePosts'))
  print('  social.facebook.general.defaultImagePosts      :', gen.get('defaultImagePosts'))
  hp=fb.get('homePage',{}) if isinstance(fb,dict) else {}
  print('  social.facebook.homePage.image                 :', hp.get('image'))
  tw=soc.get('twitter',{})
  print('  social.twitter.general.defaultImageSource      :', (tw.get('general',{}) or {}).get('defaultImageSourcePosts'))
except Exception as e:
  print('  parse不可(キー構造が違う可能性):',e)
" 2>&1 | head -20
echo "--- 生JSONの og/image 関連キーを grep(構造確認用) ---"
$WP option get aioseo_options 2>/dev/null | grep -oE '"(defaultImage[A-Za-z]*|defaultImageSource[A-Za-z]*|ogImage|image)":"[^"]*"' | sort -u | head -15

echo
echo "===== カスタムロゴ / site_icon の attachment ====="
echo "custom_logo ID: $($WP option get site_logo 2>/dev/null || $WP theme mod get custom_logo 2>/dev/null || echo '(なし)')"
clogo=$($WP option get site_logo 2>/dev/null || echo "")
[ -n "$clogo" ] && [ "$clogo" != "0" ] && echo "  logo URL: $($WP post get "$clogo" --field=guid 2>/dev/null)"
echo "uploads内のロゴ/OGP候補画像(1200x630系):"
$WP post list --post_type=attachment --fields=ID,post_title,guid 2>/dev/null | grep -iE 'logo|ogp|og-|brand|1200|default' | head -10
