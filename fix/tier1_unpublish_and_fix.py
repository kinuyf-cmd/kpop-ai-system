#!/usr/bin/env python3
"""
TIER 1-2: 同一文繰り返し7記事を非公開化
TIER 1-3: ID=3168 JSONフラグメント画像記事を非公開化
"""
import requests
import os
import json
from datetime import datetime

# Load env
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

# Phase2で特定された問題記事
DUPLICATE_SENTENCE_IDS = [
    2805,  # KPop Demon Hunters キャスト詳細
    2806,  # KPop Demon Hunters 相関図
    2807,  # KPop Demon Hunters ネタバレ
    2808,  # KPop Demon Hunters OST
    2809,  # KPop Demon Hunters 続編考察
    2797,  # 音楽サブスク比較
    2798,  # 韓国コスメガイド
]

JSON_FRAGMENT_IDS = [
    3168,  # BTS AOY AMA - JSONフラグメントがサムネイルに焼き込み
]

NEWLINE_IN_IMAGE_IDS = [
    3132,  # 復帰ラッシュ\n全構図
    3133,  # スキズ\n仏Gold
    3134,  # BTS\n東京ドーム
    3237,  # BTS\n東京ドーム (duplicate image)
]

results = {
    'timestamp': datetime.now().isoformat(),
    'tier1_2_unpublished': [],
    'tier1_3_unpublished': [],
    'tier2_newline_unpublished': [],
    'failed': [],
}

def set_draft(post_id, reason):
    """記事をdraftに変更"""
    r = requests.post(
        f'{WP_BASE}/posts/{post_id}',
        auth=AUTH,
        json={'status': 'draft'},
        timeout=30
    )
    if r.status_code == 200:
        title = r.json().get('title', {}).get('rendered', '')[:50]
        print(f"  DRAFT  ID={post_id} | {reason} | {title}")
        return True, title
    else:
        print(f"  FAIL   ID={post_id} | HTTP {r.status_code}")
        return False, ''


print("=" * 60)
print("TIER 1-2: Unpublish Duplicate Sentence Articles")
print("=" * 60)

for pid in DUPLICATE_SENTENCE_IDS:
    ok, title = set_draft(pid, "同一文8回繰り返し")
    if ok:
        results['tier1_2_unpublished'].append({'id': pid, 'title': title})
    else:
        results['failed'].append({'id': pid, 'tier': '1-2'})


print(f"\n{'=' * 60}")
print("TIER 1-3: Unpublish JSON Fragment Thumbnail Articles")
print("=" * 60)

for pid in JSON_FRAGMENT_IDS:
    ok, title = set_draft(pid, "JSONフラグメント画像")
    if ok:
        results['tier1_3_unpublished'].append({'id': pid, 'title': title})
    else:
        results['failed'].append({'id': pid, 'tier': '1-3'})


print(f"\n{'=' * 60}")
print("TIER 2: Unpublish \\n-in-image Articles")
print("=" * 60)

for pid in NEWLINE_IN_IMAGE_IDS:
    ok, title = set_draft(pid, "\\nリテラル画像")
    if ok:
        results['tier2_newline_unpublished'].append({'id': pid, 'title': title})
    else:
        results['failed'].append({'id': pid, 'tier': '2'})


# Summary
print(f"\n{'=' * 60}")
print(f"RESULTS:")
print(f"  TIER 1-2 (duplicate sentences) unpublished: {len(results['tier1_2_unpublished'])}/{len(DUPLICATE_SENTENCE_IDS)}")
print(f"  TIER 1-3 (JSON fragment)       unpublished: {len(results['tier1_3_unpublished'])}/{len(JSON_FRAGMENT_IDS)}")
print(f"  TIER 2   (\\n in images)        unpublished: {len(results['tier2_newline_unpublished'])}/{len(NEWLINE_IN_IMAGE_IDS)}")
print(f"  Failed: {len(results['failed'])}")
print(f"  Total unpublished: {len(results['tier1_2_unpublished']) + len(results['tier1_3_unpublished']) + len(results['tier2_newline_unpublished'])}")
print(f"{'=' * 60}")

# Save results
with open('/tmp/audit/tier1_unpublish_results.json', 'w') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
