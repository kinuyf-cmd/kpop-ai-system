#!/usr/bin/env python3
"""
TIER 2: 本文sanitize
- \nリテラル除去
- テンプレート }} 除去
- 同一文重複除去（3回以上→1回に）
"""
import requests
import re
import os
import json
import html
from datetime import datetime
from collections import Counter

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

# Target post IDs from Phase2 audit
NEWLINE_POSTS = [3045, 2967, 2861]  # \n残存
TEMPLATE_POSTS = [3286, 3045, 2967, 2861]  # }} 残存
# All published posts need HTMLentity fix


def get_post_content(post_id):
    r = requests.get(f'{WP_BASE}/posts/{post_id}', auth=AUTH,
                     params={'_fields': 'id,title,content,status'}, timeout=30)
    if r.status_code == 200:
        return r.json()
    return None


def sanitize_content(content):
    """本文のsanitize"""
    changes = []

    # 1. \n リテラル除去（実際の改行ではなくバックスラッシュ+n）
    if '\\n' in content:
        count = content.count('\\n')
        content = content.replace('\\n', ' ')
        changes.append(f'\\n除去 {count}箇所')

    # 2. テンプレート }} 残存除去
    if '}}' in content:
        # Only remove standalone }} not inside code blocks
        content = re.sub(r'(?<!</code>)\}\}(?!\.)', '', content)
        changes.append('}} 除去')

    # 3. 同一文の重複除去（3回以上→1回に）
    # Split by 。and check for duplicates
    parts = content.split('。')
    if len(parts) > 5:
        seen = Counter()
        new_parts = []
        for part in parts:
            stripped = part.strip()
            if len(stripped) > 20:
                seen[stripped] += 1
                if seen[stripped] <= 1:
                    new_parts.append(part)
                # Skip duplicates
            else:
                new_parts.append(part)
        if len(new_parts) < len(parts):
            content = '。'.join(new_parts)
            removed = len(parts) - len(new_parts)
            changes.append(f'重複文除去 {removed}文')

    return content, changes


def update_post(post_id, content):
    r = requests.post(f'{WP_BASE}/posts/{post_id}', auth=AUTH,
                      json={'content': content}, timeout=30)
    return r.status_code == 200


print("=" * 60)
print("TIER 2: Content Sanitization")
print(f"Time: {datetime.now().isoformat()}")
print("=" * 60)

# Get all recent posts
all_posts = []
page = 1
while True:
    r = requests.get(f'{WP_BASE}/posts', auth=AUTH, timeout=30,
                     params={'per_page': 50, 'page': page,
                             'after': '2026-04-16T00:00:00',
                             '_fields': 'id,title,content,status'})
    if r.status_code != 200:
        break
    data = r.json()
    if not data:
        break
    all_posts.extend(data)
    page += 1

print(f"Fetched {len(all_posts)} posts")

results = {'sanitized': 0, 'unchanged': 0, 'failed': 0, 'details': []}

for post in all_posts:
    pid = post['id']
    content = post['content']['rendered']
    status = post.get('status', '')

    if status != 'publish':
        continue

    new_content, changes = sanitize_content(content)

    if not changes:
        results['unchanged'] += 1
        continue

    if update_post(pid, new_content):
        results['sanitized'] += 1
        title = post['title']['rendered'][:50]
        print(f"  OK  ID={pid} | {', '.join(changes)} | {title}")
        results['details'].append({'id': pid, 'changes': changes})
    else:
        results['failed'] += 1
        print(f"  FAIL ID={pid}")

print(f"\n{'=' * 60}")
print(f"RESULTS:")
print(f"  Sanitized: {results['sanitized']}")
print(f"  Unchanged: {results['unchanged']}")
print(f"  Failed:    {results['failed']}")
print(f"{'=' * 60}")

with open('/tmp/audit/tier2_sanitize_results.json', 'w') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
