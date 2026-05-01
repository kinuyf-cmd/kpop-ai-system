#!/usr/bin/env python3
"""Low CTR title rewriter - batch 3 (items 30-77)"""
import json
import os
import sys
import time
import urllib.parse
import subprocess
from dotenv import load_dotenv

load_dotenv('/home/aiuser/kpop-ai-system/.env')

OPENAI_API_KEY = os.environ['OPENAI_API_KEY']
WP_USER = os.environ['WP_USER']
WP_PASS = os.environ['WP_PASS']

# Load targets
with open('/home/aiuser/kpop-ai-system/data/low_ctr_targets.json') as f:
    all_targets = json.load(f)

targets = all_targets[30:]  # items 30 onward
print(f"Total targets to process: {len(targets)}")

# Skip patterns
SKIP_SLUGS = {'about-editor', 'www.kpopjournal.tokyo', 'about', 'advertise'}

def should_skip(item):
    slug = item.get('slug', '')
    if slug in SKIP_SLUGS:
        return True
    if slug.startswith('#rtoc-'):
        return True
    if slug.startswith('popup-'):
        return True
    # URL-encoded slugs that are truncated
    if '%' in slug and len(slug) < 60:
        # These might be OK, let's try them
        pass
    return False

def get_wp_post(slug):
    """Get post ID and title from WP REST API"""
    # Try the slug as-is first
    cmd = f'source /home/aiuser/kpop-ai-system/.env && curl -s "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts?slug={slug}&_fields=id,title" -u "$WP_USER:$WP_PASS"'
    result = subprocess.run(['bash', '-c', cmd], capture_output=True, text=True, timeout=30)
    try:
        data = json.loads(result.stdout)
        if isinstance(data, list) and len(data) > 0:
            return data[0]['id'], data[0]['title']['rendered']
    except (json.JSONDecodeError, KeyError, IndexError):
        pass
    return None, None

def generate_new_title(old_title, slug):
    """Use GPT-4o-mini to generate improved title"""
    import openai
    client = openai.OpenAI(api_key=OPENAI_API_KEY)

    prompt = f"""あなたはK-POPメディアの編集者です。以下の記事タイトルのCTR（クリック率）を改善してください。

現在のタイトル: {old_title}
slug: {slug}

ルール:
- 40文字以内（日本語）
- 「完全」「徹底」「衝撃」は使用禁止
- 疑問形や具体的な数字で注目を引く
- ファンが思わずクリックしたくなる表現
- 記事内容を正確に反映すること
- 新しいタイトルのみを出力（説明不要）"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=100,
        temperature=0.7
    )
    new_title = response.choices[0].message.content.strip()
    # Remove quotes if wrapped
    if (new_title.startswith('「') and new_title.endswith('」')) or \
       (new_title.startswith('"') and new_title.endswith('"')):
        new_title = new_title[1:-1]
    return new_title

def update_wp_title(post_id, new_title):
    """Update the post title via WP REST API"""
    escaped_title = new_title.replace('"', '\\"')
    cmd = f'''source /home/aiuser/kpop-ai-system/.env && curl -s -X POST "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/{post_id}" -u "$WP_USER:$WP_PASS" -H "Content-Type: application/json" -d '{{"title":"{escaped_title}"}}'  '''
    result = subprocess.run(['bash', '-c', cmd], capture_output=True, text=True, timeout=30)
    try:
        data = json.loads(result.stdout)
        if 'id' in data:
            return True
    except (json.JSONDecodeError, KeyError):
        pass
    return False

# Process
results = []
skipped = []
failed = []

for i, item in enumerate(targets):
    slug = item['slug']
    idx = i + 30  # original index

    print(f"\n--- [{idx}] slug={slug} ---")

    if should_skip(item):
        print(f"  SKIP (filter rule)")
        skipped.append({'index': idx, 'slug': slug, 'reason': 'filter'})
        continue

    # Get current post from WP
    post_id, old_title = get_wp_post(slug)
    if post_id is None:
        print(f"  SKIP (slug not found in WP)")
        skipped.append({'index': idx, 'slug': slug, 'reason': 'not_found'})
        continue

    print(f"  ID={post_id}, old_title={old_title}")

    # Generate new title (1 at a time to avoid batch bug)
    try:
        new_title = generate_new_title(old_title, slug)
    except Exception as e:
        print(f"  FAIL (GPT error: {e})")
        failed.append({'index': idx, 'slug': slug, 'error': str(e)})
        continue

    print(f"  new_title={new_title}")

    # Validate
    if len(new_title) > 60:  # generous limit for mixed jp/en
        print(f"  WARN: title may be too long ({len(new_title)} chars), truncating")
        new_title = new_title[:40]

    for banned in ['完全', '徹底', '衝撃']:
        if banned in new_title:
            print(f"  WARN: banned word '{banned}' found, regenerating...")
            try:
                new_title = generate_new_title(old_title, slug)
            except:
                pass

    # Update WP
    success = update_wp_title(post_id, new_title)
    if success:
        print(f"  OK - updated")
        results.append({
            'post_id': post_id,
            'slug': slug,
            'old_title': old_title,
            'new_title': new_title,
            'impressions': item.get('impressions'),
            'ctr_before': item.get('ctr')
        })
    else:
        print(f"  FAIL (WP update error)")
        failed.append({'index': idx, 'slug': slug, 'error': 'wp_update_failed'})

    # Rate limit: small delay between requests
    time.sleep(1)

# Save results
output = {
    'batch': 3,
    'processed_at': '2026-05-01',
    'total_targets': len(targets),
    'updated': len(results),
    'skipped': len(skipped),
    'failed': len(failed),
    'rewrites': results,
    'skipped_details': skipped,
    'failed_details': failed
}

with open('/home/aiuser/kpop-ai-system/data/ctr_rewrites_batch3.json', 'w', encoding='utf-8') as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f"\n=== SUMMARY ===")
print(f"Updated: {len(results)}")
print(f"Skipped: {len(skipped)}")
print(f"Failed:  {len(failed)}")
print(f"Results saved to data/ctr_rewrites_batch3.json")
