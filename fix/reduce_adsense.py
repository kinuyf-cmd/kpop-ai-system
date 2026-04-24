#!/usr/bin/env python3
"""
TIER 1-1: AdSense配置数を記事あたり最大5箇所に削減
AdSenseポリシー違反リスクへの緊急対応
"""
import requests
import re
import os
import json
from datetime import datetime

# WP credentials - read from .env directly
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
WP_USER = _env.get('WP_USER', '')
WP_PASS = _env.get('WP_PASS', '')
WP_BASE = 'https://www.kpopjournal.tokyo/wp-json/wp/v2'
AUTH = (WP_USER, WP_PASS)

MAX_ADS = 5  # Maximum ads per article

def get_all_recent_posts():
    """72時間以内の記事を取得"""
    posts = []
    page = 1
    while True:
        r = requests.get(
            f'{WP_BASE}/posts',
            params={
                'per_page': 50,
                'page': page,
                'after': '2026-04-16T00:00:00',
                'before': '2026-04-19T23:59:59',
                '_fields': 'id,title,content,status'
            },
            auth=AUTH,
            timeout=30
        )
        if r.status_code != 200:
            break
        data = r.json()
        if not data:
            break
        posts.extend(data)
        page += 1
    return posts


def reduce_adsense(content, max_ads=MAX_ADS):
    """AdSenseブロックをmax_ads箇所に削減"""
    # AdSense ins タグ + 関連する script タグのパターン
    # Pattern 1: <ins class="adsbygoogle"...></ins> + optional <script>
    ad_pattern = re.compile(
        r'(<ins\s+class="adsbygoogle"[^>]*>[\s\S]*?</ins>\s*'
        r'(?:<script>\s*\(adsbygoogle\s*=\s*window\.adsbygoogle\s*\|\|\s*\[\]\)\.push\(\{\}\);\s*</script>)?)',
        re.IGNORECASE
    )

    matches = list(ad_pattern.finditer(content))
    total_ads = len(matches)

    if total_ads <= max_ads:
        return content, 0, total_ads

    # Remove all ad blocks, track positions
    clean = ad_pattern.sub('', content)

    # Count paragraphs to determine insertion points
    p_tags = list(re.finditer(r'</p>', clean))
    num_paragraphs = len(p_tags)

    if num_paragraphs < 3:
        # Very short article - just 1 ad at the end
        target_count = 1
    elif num_paragraphs < 8:
        target_count = 2
    elif num_paragraphs < 15:
        target_count = 3
    else:
        target_count = min(max_ads, 5)

    # Calculate insertion positions (evenly spaced)
    if num_paragraphs > 0 and target_count > 0:
        step = num_paragraphs // (target_count + 1)
        positions = [step * (i + 1) for i in range(target_count)]
        positions = [p for p in positions if p < num_paragraphs]
    else:
        positions = []

    # Use the first ad block as template
    ad_template = matches[0].group(0) if matches else ''

    # Insert ads at calculated positions (work backwards to preserve indices)
    result = clean
    for pos_idx in reversed(sorted(positions)):
        if pos_idx < len(p_tags):
            insert_at = p_tags[pos_idx].end()
            result = result[:insert_at] + '\n' + ad_template + '\n' + result[insert_at:]

    removed = total_ads - len(positions)
    return result, removed, total_ads


def update_post_content(post_id, content):
    """WP REST APIで記事コンテンツを更新"""
    r = requests.post(
        f'{WP_BASE}/posts/{post_id}',
        auth=AUTH,
        json={'content': content},
        timeout=30
    )
    return r.status_code == 200, r.status_code


# Main execution
if __name__ == '__main__':
    print("=" * 60)
    print("TIER 1-1: AdSense Emergency Reduction")
    print(f"Time: {datetime.now().isoformat()}")
    print(f"Max ads per article: {MAX_ADS}")
    print("=" * 60)

    posts = get_all_recent_posts()
    print(f"\nFetched {len(posts)} posts")

    results = {
        'total_posts': len(posts),
        'modified': 0,
        'failed': 0,
        'skipped': 0,
        'total_ads_before': 0,
        'total_ads_after': 0,
        'details': []
    }

    for post in posts:
        pid = post['id']
        title = post['title']['rendered'][:50]
        content = post['content']['rendered']

        new_content, removed, original_count = reduce_adsense(content)
        results['total_ads_before'] += original_count

        if removed == 0:
            results['skipped'] += 1
            results['total_ads_after'] += original_count
            continue

        new_count = original_count - removed
        results['total_ads_after'] += new_count

        success, status_code = update_post_content(pid, new_content)
        if success:
            results['modified'] += 1
            print(f"  OK  ID={pid} {original_count} -> {new_count} ads | {title}")
            results['details'].append({
                'id': pid, 'before': original_count,
                'after': new_count, 'status': 'ok'
            })
        else:
            results['failed'] += 1
            print(f"  FAIL ID={pid} HTTP {status_code} | {title}")
            results['details'].append({
                'id': pid, 'before': original_count,
                'status': 'failed', 'http': status_code
            })

    avg_before = results['total_ads_before'] / max(results['total_posts'], 1)
    avg_after = results['total_ads_after'] / max(results['total_posts'], 1)

    print(f"\n{'=' * 60}")
    print(f"RESULTS:")
    print(f"  Modified: {results['modified']}")
    print(f"  Failed:   {results['failed']}")
    print(f"  Skipped:  {results['skipped']}")
    print(f"  Avg ads before: {avg_before:.1f}")
    print(f"  Avg ads after:  {avg_after:.1f}")
    print(f"{'=' * 60}")

    # Save results
    with open('/tmp/audit/tier1_adsense_results.json', 'w') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
