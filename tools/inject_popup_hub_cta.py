#!/usr/bin/env python3
"""既存popup記事に「開催中の全ポップアップ情報はこちら」CTAを挿入するワンショットスクリプト"""
import json
import os
import sys
import urllib.request
import base64
from dotenv import load_dotenv

load_dotenv()

WP_USER = os.getenv('WP_USER', '')
WP_PASS = os.getenv('WP_PASS', '')
AUTH = base64.b64encode(f"{WP_USER}:{WP_PASS}".encode()).decode()
WP = "https://www.kpopjournal.tokyo"

POPUP_HUB_CTA = (
    '<div class="kpj-popup-hub-cta" style="margin:30px 0 20px;padding:16px 20px;'
    'background:linear-gradient(135deg,#fff0f3,#f8f0ff);border-radius:12px;'
    'text-align:center;border:1px solid #ffd6e0;">'
    '<p style="margin:0;font-size:1.05em;font-weight:700;">'
    '<a href="https://www.kpopjournal.tokyo/popup/" '
    'style="color:#FF1B6B;text-decoration:none;">'
    '\u2728 開催中の全ポップアップ情報はこちら \u2728</a></p></div>'
)


def get_popup(post_id):
    url = f"{WP}/wp-json/wp/v2/popup/{post_id}?_fields=id,content,title"
    req = urllib.request.Request(url, headers={'Authorization': f'Basic {AUTH}'})
    return json.loads(urllib.request.urlopen(req, timeout=30).read())


def update_popup(post_id, new_content):
    body = json.dumps({'content': new_content}).encode()
    req = urllib.request.Request(
        f"{WP}/wp-json/wp/v2/popup/{post_id}",
        data=body, method='POST',
        headers={'Authorization': f'Basic {AUTH}', 'Content-Type': 'application/json'})
    r = json.loads(urllib.request.urlopen(req, timeout=30).read())
    return r.get('id')


def inject_cta(content):
    if 'kpj-popup-hub-cta' in content:
        return content, False
    disclaimer_pat = '<p class="kpj-disclaimer">'
    if disclaimer_pat in content:
        return content.replace(disclaimer_pat, POPUP_HUB_CTA + '\n' + disclaimer_pat, 1), True
    return content.rstrip() + '\n' + POPUP_HUB_CTA, True


def main():
    post_ids = [int(x) for x in sys.argv[1:]]
    if not post_ids:
        print("Usage: python3 inject_popup_hub_cta.py <post_id> [post_id ...]")
        return

    updated = 0
    skipped = 0
    for pid in post_ids:
        try:
            p = get_popup(pid)
            content = p.get('content', {}).get('rendered', '') if isinstance(p.get('content'), dict) else p.get('content', '')
            title = p.get('title', {}).get('rendered', '') if isinstance(p.get('title'), dict) else ''
            new_content, changed = inject_cta(content)
            if not changed:
                print(f"  [{pid}] already has CTA, skip")
                skipped += 1
                continue
            update_popup(pid, new_content)
            print(f"  [{pid}] OK - CTA inserted ({title[:40]})")
            updated += 1
        except Exception as e:
            print(f"  [{pid}] ERROR: {e}")

    print(f"\n完了: {updated}件更新, {skipped}件スキップ")


if __name__ == '__main__':
    main()
