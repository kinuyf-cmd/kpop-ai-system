#!/usr/bin/env python3
"""
T1-1 Fix C: WP raw content から不要なAdSenseブロックを一括除去
Next.jsフロントエンドが独自にAdSenseを配置するため、WP content内のAdSenseは不要。
"""
import requests, re, os, json

def load_env():
    env = {}
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.env')) as f:
        for line in f:
            line = line.strip()
            if '=' in line and not line.startswith('#'):
                k, v = line.split('=', 1)
                env[k] = v.strip().strip('"').strip("'")
    return env

_env = load_env()
AUTH = (_env['WP_USER'], _env['WP_PASS'])
WP = 'https://www.kpopjournal.tokyo/wp-json/wp/v2'

# Patterns to strip from raw content
AD_PATTERNS = [
    # wp:html wrapped ad blocks
    r'<!-- wp:html -->\s*<div class="kpopj-ad[^"]*"[^>]*>[\s\S]*?</div>\s*<!-- /wp:html -->\s*',
    # Standalone kpopj-ad divs
    r'<div class="kpopj-ad[^"]*"[^>]*>[\s\S]*?</div>\s*',
    # ins.adsbygoogle + script
    r'<ins\s+class="adsbygoogle"[^>]*>[\s\S]*?</ins>\s*(?:<script>[^<]*adsbygoogle[^<]*</script>)?\s*',
    # Orphaned adsbygoogle scripts
    r'<script>\s*\(adsbygoogle\s*=\s*window\.adsbygoogle\s*\|\|\s*\[\]\)\.push\(\{\}\);\s*</script>\s*',
]

posts = []
page = 1
while True:
    r = requests.get(f'{WP}/posts', auth=AUTH, timeout=30,
                     params={'per_page': 50, 'page': page, 'context': 'edit', 'status': 'publish'})
    if r.status_code != 200: break
    d = r.json()
    if not d: break
    posts.extend(d)
    page += 1

print(f"Posts to process: {len(posts)}")
modified = 0

for post in posts:
    pid = post['id']
    raw = post['content']['raw']
    original_ads = raw.count('adsbygoogle') + raw.count('kpopj-ad')

    if original_ads == 0:
        continue

    cleaned = raw
    for pat in AD_PATTERNS:
        cleaned = re.sub(pat, '', cleaned, flags=re.IGNORECASE)

    # Clean up excessive whitespace left behind
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)

    remaining_ads = cleaned.count('adsbygoogle') + cleaned.count('kpopj-ad')

    if cleaned != raw:
        r = requests.post(f'{WP}/posts/{pid}', auth=AUTH,
                          json={'content': cleaned}, timeout=30)
        if r.status_code == 200:
            modified += 1
            title = post['title']['raw'][:50]
            print(f"  OK  ID={pid} ads:{original_ads}->{remaining_ads} | {title}")
        else:
            print(f"  FAIL ID={pid} HTTP {r.status_code}")

print(f"\nTotal modified: {modified}")
