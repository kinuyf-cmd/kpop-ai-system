#!/usr/bin/env python3
"""全記事サムネ汚染フルスキャン (one-off audit, 2026-05-10)

WP REST API は max per_page=100、page * per_page <= 10000 制限。
14記事/page 単位で全696記事をスキャン。
"""
import os, sys, json, urllib.request, tempfile
sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from dotenv import load_dotenv
load_dotenv('/home/aiuser/kpop-ai-system/.env')
from lib.thumbnail_source_resolver import _is_shorts_thumbnail
from PIL import Image

PER_PAGE = 100
OUTPUT = '/tmp/full_scan_results.json'


def fetch_all_posts():
    posts = []
    page = 1
    while True:
        url = (f'https://www.kpopjournal.tokyo/wp-json/wp/v2/posts'
               f'?per_page={PER_PAGE}&page={page}'
               f'&_fields=id,title,slug,featured_media,date')
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'kpj-scan/1.0'})
            d = json.loads(urllib.request.urlopen(req, timeout=20).read())
            if not d:
                break
            posts.extend(d)
            print(f"  page {page}: {len(d)} posts (total fetched: {len(posts)})")
            if len(d) < PER_PAGE:
                break
            page += 1
        except Exception as e:
            print(f"  page {page} err: {e}")
            break
    return posts


def get_thumb_url(media_id: int) -> str:
    try:
        url = f'https://www.kpopjournal.tokyo/wp-json/wp/v2/media/{media_id}?_fields=source_url'
        req = urllib.request.Request(url, headers={'User-Agent': 'kpj-scan/1.0'})
        d = json.loads(urllib.request.urlopen(req, timeout=8).read())
        return d.get('source_url', '')
    except Exception:
        return ''


def check_thumb(post: dict) -> dict:
    pid = post['id']
    fm = post.get('featured_media', 0)
    if not fm:
        return {'pid': pid, 'status': 'no_thumb', 'date': post.get('date', '')}
    thumb_url = get_thumb_url(fm)
    if not thumb_url:
        return {'pid': pid, 'status': 'media_404', 'date': post.get('date', '')}
    try:
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tf:
            with urllib.request.urlopen(thumb_url, timeout=12) as r:
                tf.write(r.read())
            path = tf.name
        try:
            img = Image.open(path).convert('RGB')
            w, h = img.size
            issues = []
            if h > w:
                issues.append(f'portrait_{w}x{h}')
            if w < 300 or h < 200:
                issues.append(f'too_small_{w}x{h}')
            if _is_shorts_thumbnail(path):
                issues.append('shorts')
            return {
                'pid': pid, 'title': post['title']['rendered'][:60],
                'slug': post['slug'], 'thumb_url': thumb_url,
                'date': post.get('date', '')[:10],
                'media_id': fm,
                'issues': issues,
                'status': 'contaminated' if issues else 'clean',
            }
        finally:
            os.unlink(path)
    except Exception as e:
        return {'pid': pid, 'status': f'err:{str(e)[:50]}', 'date': post.get('date', '')}


def main():
    print("=== Full Thumbnail Contamination Scan ===")
    posts = fetch_all_posts()
    print(f"total posts: {len(posts)}")

    results = []
    contaminated = []
    for i, p in enumerate(posts):
        r = check_thumb(p)
        results.append(r)
        if r.get('status') == 'contaminated':
            contaminated.append(r)
        if (i + 1) % 50 == 0:
            print(f"  scanned {i+1}/{len(posts)}, contaminated so far: {len(contaminated)}")

    print(f"\n=== RESULT ===")
    print(f"total scanned: {len(results)}")
    print(f"contaminated:  {len(contaminated)}")

    # Group by issue type
    by_issue = {}
    for c in contaminated:
        for iss in c.get('issues', []):
            key = iss.split('_')[0]
            by_issue[key] = by_issue.get(key, 0) + 1
    print(f"breakdown: {by_issue}")

    with open(OUTPUT, 'w', encoding='utf-8') as f:
        json.dump({
            'total': len(results), 'contaminated_count': len(contaminated),
            'breakdown': by_issue,
            'contaminated': contaminated,
        }, f, ensure_ascii=False, indent=2)
    print(f"saved: {OUTPUT}")


if __name__ == '__main__':
    main()
