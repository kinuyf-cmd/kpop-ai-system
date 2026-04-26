"""draft自動publish — 品質ゲートPASS記事を自動公開 (毎時20分)"""
import requests, os, json, re, sys
sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from dotenv import load_dotenv
load_dotenv('/home/aiuser/kpop-ai-system/.env')
from datetime import datetime
from lib.full_audit_engine import full_audit

AUTH = (os.getenv('WP_USER', ''), os.getenv('WP_PASS', ''))

def main():
    all_drafts = []
    for page in range(1, 5):
        r = requests.get(
            f'https://www.kpopjournal.tokyo/wp-json/wp/v2/posts?status=draft&per_page=100&page={page}&_embed=true',
            auth=AUTH, timeout=20)
        if r.status_code != 200 or not isinstance(r.json(), list) or not r.json():
            break
        all_drafts.extend(r.json())

    if not all_drafts:
        print(f"[{datetime.now().isoformat()}] draft: 0件")
        return

    pub = rew = err = 0
    for d in all_drafts:
        pid = d['id']
        try:
            issues = full_audit(d, 'post')
            high = sum(1 for i in issues if i.get('severity') == 'high')
            content = d.get('content', {}).get('rendered', '')
            plain = re.sub(r'<[^>]+>', '', content).strip()
            if high < 3 and len(plain) >= 150:
                u = requests.post(
                    f'https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/{pid}',
                    json={'status': 'publish'}, auth=AUTH, timeout=15)
                if u.status_code == 200:
                    pub += 1
            else:
                rew += 1
        except:
            err += 1

    print(f"[{datetime.now().isoformat()}] draft={len(all_drafts)} publish={pub} rewrite={rew} err={err}")

if __name__ == '__main__':
    main()
