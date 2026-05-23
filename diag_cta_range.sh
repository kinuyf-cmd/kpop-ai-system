#!/usr/bin/env bash
WP="sudo -u www-data wp --path=/var/www/wp_stg"
pid=396
content=$($WP post get $pid --field=post_content 2>/dev/null)
echo "===== CTAブロックの開始マーカー(kpop-citation-cta の前) ====="
# citation-cta の手前300字(本文本体との境界を見る)
echo "$content" | python3 -c "
import sys,re
c=sys.stdin.read()
i=c.find('kpop-citation-cta')
# その<p>の開始タグまで遡る
pstart=c.rfind('<p',0,i)
print('--- CTA直前の本文末(境界の80字)---')
print(repr(re.sub(r'\s+',' ',c[max(0,pstart-160):pstart])[-160:]))
print()
print('--- CTAブロック全体(pstart〜本文末)の構造マーカー ---')
block=c[pstart:]
for tag in re.findall(r'<(\w+)[^>]*class=\"([^\"]*)\"', block):
    print('   <%s class=%s>' % tag)
print()
print('--- 末尾が kpj-disclosure で終わるか ---')
print('   末尾60字:', repr(c[-60:].strip()))
print('   CTAブロック開始offset:', pstart, '/ 本文長:', len(c))
"
echo
echo "===== 本文に <p class=kpop-citation-cta> は1箇所だけか(複数なら抽出注意) ====="
echo "$content" | grep -oc 'kpop-citation-cta'
