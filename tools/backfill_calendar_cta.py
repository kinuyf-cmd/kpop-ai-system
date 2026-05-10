#!/usr/bin/env python3
"""既存記事に release-calendar CTA + profile inline link を一発backfill

過去N日 (default 30) の記事をfetchし、未挿入のものにのみ
- inject_profile_inline_links() で本文中の初出artist名を /artist-{slug}/ にlink化
- maybe_inject_calendar_cta() で末尾にCTA box挿入

冪等性: comeback-calendar-cta div が既にあるpostはskip。
"""
from __future__ import annotations
import os, sys, json, urllib.request, base64, time, argparse
from datetime import datetime, timedelta, timezone

sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from dotenv import load_dotenv
load_dotenv('/home/aiuser/kpop-ai-system/.env')

from lib.comeback_calendar_inject import inject_profile_inline_links, maybe_inject_calendar_cta, ARTIST_SLUG_MAP

WP_USER = os.getenv('WP_USER', '')
WP_PASS = os.getenv('WP_PASS', '')
AUTH = base64.b64encode(f"{WP_USER}:{WP_PASS}".encode()).decode()
JST = timezone(timedelta(hours=9))


def detect_artist_in_title(title: str) -> str:
    """タイトルから既知artist名を検出 (CTA用)"""
    t = title.lower()
    for artist in sorted(ARTIST_SLUG_MAP.keys(), key=lambda x: -len(x)):
        if artist.lower() in t:
            return artist
    return ''


def fetch_posts(after_date: str, per_page: int = 50) -> list[dict]:
    """指定日時以降のpostをfetch"""
    posts = []
    page = 1
    while True:
        url = (f'https://www.kpopjournal.tokyo/wp-json/wp/v2/posts'
               f'?after={after_date}&per_page={per_page}&page={page}'
               f'&_fields=id,slug,title,content,date&orderby=date&order=desc')
        req = urllib.request.Request(url, headers={'Authorization': f'Basic {AUTH}'})
        try:
            r = urllib.request.urlopen(req, timeout=20)
            chunk = json.loads(r.read())
        except Exception as e:
            print(f"fetch err: {e}")
            break
        if not chunk:
            break
        posts.extend(chunk)
        if len(chunk) < per_page:
            break
        page += 1
        if page > 10:  # safety
            break
    return posts


def update_post_content(post_id: int, content: str) -> bool:
    url = f'https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/{post_id}'
    req = urllib.request.Request(
        url, data=json.dumps({'content': content}).encode(), method='POST',
        headers={'Authorization': f'Basic {AUTH}', 'Content-Type': 'application/json'})
    try:
        urllib.request.urlopen(req, timeout=20)
        return True
    except Exception as e:
        print(f"  update err: {e}")
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--days', type=int, default=30)
    ap.add_argument('--limit', type=int, default=200)
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--revalidate', action='store_true', default=True)
    args = ap.parse_args()

    after = (datetime.now(JST) - timedelta(days=args.days)).strftime('%Y-%m-%dT%H:%M:%S')
    print(f"Fetching posts after {after}...", flush=True)
    posts = fetch_posts(after)
    print(f"  found {len(posts)} posts", flush=True)
    if args.limit:
        posts = posts[:args.limit]

    updated = 0; skipped = 0; errored = 0
    paths_to_revalidate = []
    for p in posts:
        pid = p['id']
        title = p['title']['rendered']
        content = p['content']['rendered']

        if 'comeback-calendar-cta' in content:
            skipped += 1
            continue

        artist = detect_artist_in_title(title)
        # inline link注入
        new_content = inject_profile_inline_links(content)
        # CTA注入
        new_content = maybe_inject_calendar_cta(new_content, artist=artist)

        if new_content == content:
            skipped += 1
            continue

        if args.dry_run:
            print(f"  DRY [{pid}] {title[:40]} (artist={artist})")
            updated += 1
            continue

        if update_post_content(pid, new_content):
            print(f"  ✓ [{pid}] {title[:40]} (artist={artist or '-'})", flush=True)
            updated += 1
            paths_to_revalidate.append(f'/{p["slug"]}/')
        else:
            errored += 1

        time.sleep(0.3)  # rate limit

    print(f"\nDone: updated={updated}, skipped={skipped}, errored={errored}")

    # Revalidate Next.js cache
    if args.revalidate and paths_to_revalidate and not args.dry_run:
        print(f"\nRevalidating {len(paths_to_revalidate)} paths...")
        try:
            from lib.frontend_cache import purge_paths
            # batch 20件ずつ
            for i in range(0, len(paths_to_revalidate), 20):
                batch = paths_to_revalidate[i:i+20]
                r = purge_paths(batch)
                print(f"  batch {i}: success={r.get('success')}")
        except Exception as e:
            print(f"  revalidate err: {e}")


if __name__ == '__main__':
    main()
