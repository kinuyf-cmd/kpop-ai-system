#!/usr/bin/env python3
"""
TIER 1-1 v2: AdSense配置数削減 - content.raw ベース
"""
import requests
import re
import os
import json
from datetime import datetime

def load_env():
    env = {}
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.env')
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if '=' in line and not line.startswith('#'):
                key, val = line.split('=', 1)
                val = val.strip().strip('"').strip("'")
                env[key] = val
    return env

_env = load_env()
AUTH = (_env.get('WP_USER', ''), _env.get('WP_PASS', ''))
WP_BASE = 'https://www.kpopjournal.tokyo/wp-json/wp/v2'
MAX_ADS = 5


def get_posts_raw():
    """context=edit で raw content を取得"""
    posts = []
    page = 1
    while True:
        r = requests.get(f'{WP_BASE}/posts', auth=AUTH, timeout=30,
                         params={'per_page': 50, 'page': page,
                                 'after': '2026-04-16T00:00:00',
                                 'context': 'edit',
                                 'status': 'publish'})
        if r.status_code != 200:
            break
        data = r.json()
        if not data:
            break
        posts.extend(data)
        page += 1
    return posts


def reduce_adsense_raw(raw_content):
    """raw content からAdSenseブロックを削減"""
    # Multiple patterns for AdSense blocks
    patterns = [
        # <!-- wp:html --> wrapped ads
        r'<!-- wp:html -->\s*<ins\s+class="adsbygoogle"[^>]*>[\s\S]*?</ins>\s*(?:<script>[\s\S]*?</script>)?\s*<!-- /wp:html -->',
        # Standalone ins + script
        r'<ins\s+class="adsbygoogle"[^>]*>[\s\S]*?</ins>\s*<script>\s*\(adsbygoogle[\s\S]*?</script>',
        # Just ins tags
        r'<ins\s+class="adsbygoogle"[^>]*>\s*</ins>',
    ]

    # Find all ad blocks
    ad_positions = []
    for pattern in patterns:
        for match in re.finditer(pattern, raw_content, re.IGNORECASE):
            # Check for overlap
            overlaps = False
            for start, end, _ in ad_positions:
                if match.start() < end and match.end() > start:
                    overlaps = True
                    break
            if not overlaps:
                ad_positions.append((match.start(), match.end(), match.group(0)))

    ad_positions.sort(key=lambda x: x[0])
    total_ads = len(ad_positions)

    if total_ads <= MAX_ADS:
        return raw_content, 0, total_ads

    # Keep only MAX_ADS evenly distributed
    if total_ads > 0:
        step = total_ads / (MAX_ADS + 1)
        keep_indices = set()
        for i in range(MAX_ADS):
            idx = int((i + 1) * step)
            if idx < total_ads:
                keep_indices.add(idx)
        # Ensure we have exactly MAX_ADS
        while len(keep_indices) < MAX_ADS and len(keep_indices) < total_ads:
            for i in range(total_ads):
                if i not in keep_indices:
                    keep_indices.add(i)
                    break
    else:
        keep_indices = set()

    # Remove non-kept ads (work backwards)
    result = raw_content
    for i in reversed(range(len(ad_positions))):
        if i not in keep_indices:
            start, end, _ = ad_positions[i]
            result = result[:start] + result[end:]

    removed = total_ads - len(keep_indices)
    return result, removed, total_ads


print("=" * 60)
print("TIER 1-1 v2: AdSense Reduction (raw content)")
print(f"Time: {datetime.now().isoformat()}")
print("=" * 60)

posts = get_posts_raw()
print(f"Fetched {len(posts)} published posts")

stats = {'modified': 0, 'failed': 0, 'skipped': 0, 'before': 0, 'after': 0}

for post in posts:
    pid = post['id']
    raw = post['content'].get('raw', '')
    title = post['title'].get('raw', '')[:50]

    new_raw, removed, original = reduce_adsense_raw(raw)
    stats['before'] += original

    if removed == 0:
        stats['skipped'] += 1
        stats['after'] += original
        continue

    new_count = original - removed
    stats['after'] += new_count

    r = requests.post(f'{WP_BASE}/posts/{pid}', auth=AUTH,
                      json={'content': new_raw}, timeout=30)
    if r.status_code == 200:
        stats['modified'] += 1
        print(f"  OK  ID={pid} {original}->{new_count} ads | {title}")
    else:
        stats['failed'] += 1
        print(f"  FAIL ID={pid} HTTP {r.status_code} | {title}")

n = max(len(posts), 1)
print(f"\n{'=' * 60}")
print(f"Modified: {stats['modified']}, Failed: {stats['failed']}, Skipped: {stats['skipped']}")
print(f"Avg ads: {stats['before']/n:.1f} -> {stats['after']/n:.1f}")
print(f"{'=' * 60}")

with open('/tmp/audit/tier1_adsense_v2_results.json', 'w') as f:
    json.dump(stats, f, indent=2)
