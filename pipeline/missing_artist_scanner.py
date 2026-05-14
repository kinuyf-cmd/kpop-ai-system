#!/usr/bin/env python3
"""直近 publish 済記事から、artist は検出されるが
  - WP category (parent=26) も
  - config/artist_profiles/{slug}.json も
無い artist を見つけて pending queue に追加する。

Cron: 30 0 * * * (日次 JST 00:30)
"""
from __future__ import annotations
import json
import os
import re
import sys
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, '/home/aiuser/kpop-ai-system')

from lib.pending_artist_queue import append as queue_append
from lib.x_post_templates import KNOWN_ARTISTS

WP_API = 'https://www.kpopjournal.tokyo/wp-json/wp/v2'
PROFILE_DIR = Path('/home/aiuser/kpop-ai-system/config/artist_profiles')
PRIORITY_PY = Path('/home/aiuser/kpop-ai-system/pipeline/profile_wiki_builder.py')

# slug 用に許可される単純文字 (frontend SLUG_NORMALIZE と整合)
_NAME_TO_SLUG_OVERRIDE = {
    'BLACKPINK': 'blackpink',
    'NewJeans': 'newjeans',
    'fromis_9': 'fromis9',
    'fromis9': 'fromis9',
    '(G)I-DLE': 'gidle',
    'LE SSERAFIM': 'le-sserafim',
    'Stray Kids': 'stray-kids',
    'BIGBANG': 'big-bang',
    'BoA': 'boa',
    'KISS OF LIFE': 'kiss-of-life',
    'BABYMONSTER': 'babymonster',
    'BOYNEXTDOOR': 'boynextdoor',
    'KATSEYE': 'katseye',
    'ZEROBASEONE': 'zerobaseone',
    'Hearts2Hearts': 'hearts2hearts',
    'ALLDAY PROJECT': 'allday-project',
    'MONSTA X': 'monsta-x',
    'Red Velvet': 'red-velvet',
    'THE BOYZ': 'the-boyz',
    'Super Junior': 'super-junior',
    'P1Harmony': 'p1harmony',
}


def name_to_slug(name: str) -> str:
    if name in _NAME_TO_SLUG_OVERRIDE:
        return _NAME_TO_SLUG_OVERRIDE[name]
    s = name.lower().replace(' ', '-')
    s = re.sub(r'[^a-z0-9-]', '', s)
    return s.strip('-')


# frontend src/lib/artistSlugs.ts と同じ。WP-natural slug → profile-canonical slug
_WP_SLUG_TO_PROFILE = {
    'black-pink': 'blackpink',
    'new-jeans': 'newjeans',
    'fromis-9': 'fromis9',
    'g-idle': 'gidle',
}


def get_idol_child_categories() -> dict[str, dict]:
    """parent=26 子カテゴリ。key は profile slug 正規化後 (WP-natural は変換)。"""
    out: dict[str, dict] = {}
    page = 1
    while True:
        url = f'{WP_API}/categories?parent=26&per_page=100&page={page}&hide_empty=false'
        try:
            with urllib.request.urlopen(url, timeout=15) as r:
                data = json.loads(r.read())
        except Exception as e:
            print(f'  category fetch error: {e}', file=sys.stderr)
            break
        if not data:
            break
        for c in data:
            norm = _WP_SLUG_TO_PROFILE.get(c['slug'], c['slug'])
            out[norm] = c
        if len(data) < 100:
            break
        page += 1
    return out


def get_recent_posts(hours: int = 24) -> list[dict]:
    """直近 N 時間の publish 済 post を取得 (title のみ、最大 100)。"""
    after = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    qs = urllib.parse.urlencode({
        'after': after,
        'per_page': 100,
        'status': 'publish',
        '_fields': 'id,title,date,slug',
    })
    url = f'{WP_API}/posts?{qs}'
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f'  posts fetch error: {e}', file=sys.stderr)
        return []


def detect_known_artists(text: str) -> list[str]:
    """テキストから KNOWN_ARTISTS list 中の artist 名を抽出。
    - 単語境界マッチ (英字)
    - 韓国語/日本語名はそのまま部分一致
    - 3文字未満は除外
    """
    if not text:
        return []
    found = []
    seen = set()
    for name in KNOWN_ARTISTS:
        if name in seen or len(name) < 3:
            continue
        seen.add(name)
        if re.search(r'[A-Za-z]', name):
            pat = r'(?<![A-Za-z])' + re.escape(name) + r'(?![A-Za-z])'
            if re.search(pat, text):
                found.append(name)
        else:
            if name in text:
                found.append(name)
    return found


def main(hours: int = 24):
    posts = get_recent_posts(hours)
    print(f'recent publish posts ({hours}h): {len(posts)}')

    cats = get_idol_child_categories()
    cat_slugs = set(cats.keys())
    print(f'WP idol-child categories: {len(cat_slugs)}')

    profile_slugs = {p.stem for p in PROFILE_DIR.glob('*.json')}
    print(f'profile JSON slugs: {len(profile_slugs)}')

    queued = 0
    seen_artists: set[str] = set()
    for p in posts:
        title = re.sub(r'<[^>]+>', '', p['title']['rendered'])
        for artist in detect_known_artists(title):
            if artist in seen_artists:
                continue
            seen_artists.add(artist)
            slug = name_to_slug(artist)
            if not slug:
                continue
            miss_cat = slug not in cat_slugs
            miss_profile = slug not in profile_slugs
            if not miss_cat and not miss_profile:
                continue
            reason = f'detected in post {p["id"]} title; missing: '
            reason += ','.join(
                [k for k, v in (('category', miss_cat), ('profile', miss_profile)) if v]
            )
            ok = queue_append(
                artist_name=artist,
                source_post_id=p['id'],
                reason=reason,
                missing_category=miss_cat,
                missing_profile=miss_profile,
            )
            if ok:
                queued += 1
                print(f'  + queued: {artist} (slug={slug}, miss_cat={miss_cat}, miss_profile={miss_profile})')
            else:
                print(f'  - dedup: {artist} already pending')

    print(f'\n=== scan done: {queued} new pending entries ===')


if __name__ == '__main__':
    hours = 24
    if len(sys.argv) > 1:
        try:
            hours = int(sys.argv[1])
        except ValueError:
            pass
    main(hours)
