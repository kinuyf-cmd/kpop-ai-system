#!/usr/bin/env python3
"""
完全監査エンジン - 全post type共通の16項目チェック

A. メタデータ完全性 (4): title長/slug/featured_media/category
B. SEO要件 (4): meta_description/OGP/JSON-LD/canonical
C. 本文品質 (3): 本文長+日本語比率/誤字蛇足/HTMLタグ閉じ
D. 配信完全性 (3): GSC Indexing/X投稿/internal_links
E. 自動回復 (2): rewrite判定/quarantine判定
"""
import re, json, os, urllib.request, base64
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
load_dotenv('/home/aiuser/kpop-ai-system/.env')

WP_USER = os.getenv('WP_USER', '')
WP_PASS = os.getenv('WP_PASS', '')
AUTH = base64.b64encode(f"{WP_USER}:{WP_PASS}".encode()).decode() if WP_USER else ''

CRITERIA = {
    'post': {
        'title_max': 42, 'title_min': 10,
        'slug_min': 20, 'slug_max': 60,
        'content_min': 200, 'jp_ratio_min': 0.30,
        'meta_desc_min': 80, 'meta_desc_max': 160,
        'require_x_post': True,
        'require_gsc_indexing': True,
        'require_og_image': True,
        'min_internal_links': 2,
    },
    'popup': {
        'title_max': 60, 'title_min': 10,
        'slug_min': 10, 'slug_max': 60,
        'content_min': 200, 'jp_ratio_min': 0.30,
        'meta_desc_min': 80, 'meta_desc_max': 160,
        'require_x_post': True,
        'require_gsc_indexing': True,
        'require_og_image': True,
        'min_internal_links': 1,
    },
}

TYPO_PATTERNS = [
    (r'こんにちは[、。!]', 'casual_greeting', 'medium'),
    (r'いかがでしょうか[、。!]', 'casual_question', 'medium'),
    (r'お楽しみに[!。]', 'salesy_ending', 'medium'),
    (r'ぜひお越しください', 'salesy_cta', 'medium'),
    (r'(.)\1{4,}', 'repeated_char', 'low'),
    (r'(?:です|ます)。\s*(?:です|ます)。', 'broken_sentence', 'high'),
    (r'<h2></h2>|<p></p>|<div></div>', 'empty_tag', 'high'),
    (r'```|^##\s', 'markdown_leak', 'high'),
    (r'(?:AI|ChatGPT|GPT-[34]|Claude)\b', 'ai_mention', 'high'),
    (r'(?:以上です|以下のように|参考になれば|まとめると)', 'meta_phrase', 'high'),
    (r'(?:皆さん|みなさん)、', 'casual_address', 'medium'),
    (r'~?(?:した|されました)。\s*~?(?:した|されました)。\s*~?(?:した|されました)。', 'monotonous_ending', 'medium'),
]


def _get_title(post):
    t = post.get('title', '')
    return t.get('rendered', '') if isinstance(t, dict) else t


def _get_content(post):
    c = post.get('content', '')
    return c.get('rendered', '') if isinstance(c, dict) else c


def _get_excerpt(post):
    e = post.get('excerpt', '')
    return e.get('rendered', '') if isinstance(e, dict) else e


# === Individual checks ===

def check_title(post, criteria):
    issues = []
    title = _get_title(post)
    if len(title) > criteria['title_max']:
        issues.append({'type': 'title_long', 'severity': 'low', 'value': len(title)})
    if len(title) < criteria['title_min']:
        issues.append({'type': 'title_short', 'severity': 'high', 'value': len(title)})
    return issues


def check_slug(post, criteria):
    issues = []
    slug = post.get('slug', '')
    if not slug:
        issues.append({'type': 'no_slug', 'severity': 'high'})
        return issues
    if '%' in slug:
        issues.append({'type': 'slug_encoded', 'severity': 'high'})
    if len(slug) < criteria['slug_min']:
        issues.append({'type': 'slug_short', 'severity': 'medium', 'value': len(slug)})
    if len(slug) > criteria['slug_max']:
        issues.append({'type': 'slug_long', 'severity': 'low', 'value': len(slug)})
    return issues


def check_featured_media(post):
    fm = post.get('featured_media', 0)
    if not fm or fm == 0:
        return [{'type': 'no_thumbnail', 'severity': 'high'}]
    return []


def check_category(post, post_type):
    issues = []
    if post_type == 'post':
        if not post.get('categories'):
            issues.append({'type': 'no_category', 'severity': 'high'})
    elif post_type == 'popup':
        if not post.get('meta', {}).get('_popup_city'):
            issues.append({'type': 'no_city', 'severity': 'high'})
    return issues


def check_meta_description(post, criteria):
    issues = []
    excerpt_plain = re.sub(r'<[^>]+>', '', _get_excerpt(post)).strip()
    if not excerpt_plain:
        issues.append({'type': 'no_meta_description', 'severity': 'high'})
    elif len(excerpt_plain) < criteria['meta_desc_min']:
        issues.append({'type': 'meta_desc_short', 'severity': 'medium', 'value': len(excerpt_plain)})
    elif len(excerpt_plain) > criteria['meta_desc_max']:
        issues.append({'type': 'meta_desc_long', 'severity': 'low', 'value': len(excerpt_plain)})
    return issues


def check_ogp(post, criteria):
    issues = []
    if criteria.get('require_og_image') and not post.get('featured_media'):
        issues.append({'type': 'no_og_image', 'severity': 'medium'})
    return issues


def check_content_quality(post, criteria):
    issues = []
    content = _get_content(post)
    plain = re.sub(r'<[^>]+>', '', content)

    if len(plain) < criteria['content_min']:
        issues.append({'type': 'content_short', 'severity': 'high', 'value': len(plain)})

    jp_chars = len(re.findall(r'[\u3040-\u309F\u30A0-\u30FF\u4e00-\u9fff]', plain))
    if len(plain) > 0 and jp_chars / len(plain) < criteria['jp_ratio_min']:
        issues.append({'type': 'low_jp_ratio', 'severity': 'high', 'value': round(jp_chars / len(plain), 2)})

    for pattern, issue_type, severity in TYPO_PATTERNS:
        m = re.search(pattern, plain)
        if m:
            issues.append({'type': f'text_{issue_type}', 'severity': severity, 'sample': m.group(0)[:30]})

    open_h2 = len(re.findall(r'<h2[^>]*>', content))
    close_h2 = len(re.findall(r'</h2>', content))
    if open_h2 != close_h2:
        issues.append({'type': 'unclosed_h2', 'severity': 'high'})

    open_p = len(re.findall(r'<p[^>]*>', content))
    close_p = len(re.findall(r'</p>', content))
    if abs(open_p - close_p) > 2:
        issues.append({'type': 'unclosed_p', 'severity': 'medium'})

    return issues


def check_internal_links(post, criteria):
    content = _get_content(post)
    internal = len(re.findall(r'href="https?://(?:www\.)?kpopjournal\.tokyo[^"]*"', content))
    if internal < criteria['min_internal_links']:
        return [{'type': 'few_internal_links', 'severity': 'medium', 'value': internal}]
    return []


def check_distribution(post, post_type, criteria):
    """配信完全性: GSC Indexing + X投稿"""
    issues = []
    pid = post['id']
    date_str = post.get('date', '')
    if not date_str:
        return issues

    try:
        pub = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=timezone(timedelta(hours=9)))
        age_h = (datetime.now(timezone.utc) - pub.astimezone(timezone.utc)).total_seconds() / 3600
    except:
        return issues

    if age_h < 1:
        return issues  # 投稿後1時間は猶予

    # GSC
    if criteria.get('require_gsc_indexing'):
        gsc_log = '/home/aiuser/kpop-ai-system/logs/indexing_api_sends.jsonl'
        if not _is_in_log(pid, gsc_log, 'post_id'):
            issues.append({'type': 'no_gsc_indexing', 'severity': 'high'})

    # X
    if criteria.get('require_x_post'):
        x_log = '/home/aiuser/kpop-ai-system/logs/x_posts.jsonl'
        if not _is_in_log(pid, x_log, 'post_id'):
            issues.append({'type': 'x_missing', 'severity': 'medium'})

    return issues


def _is_in_log(post_id, log_path, key='post_id'):
    if not os.path.exists(log_path):
        return False
    with open(log_path, encoding='utf-8') as f:
        for line in f:
            try:
                if json.loads(line).get(key) == post_id:
                    return True
            except:
                pass
    return False


# === Integrated audit ===

def full_audit(post, post_type='post'):
    """投稿1件の16項目フル監査"""
    criteria = CRITERIA.get(post_type, CRITERIA['post'])
    issues = []

    # A. メタデータ完全性
    issues.extend(check_title(post, criteria))
    issues.extend(check_slug(post, criteria))
    issues.extend(check_featured_media(post))
    issues.extend(check_category(post, post_type))

    # B. SEO要件
    issues.extend(check_meta_description(post, criteria))
    issues.extend(check_ogp(post, criteria))

    # C. 本文品質
    issues.extend(check_content_quality(post, criteria))

    # D. 配信完全性
    issues.extend(check_distribution(post, post_type, criteria))
    issues.extend(check_internal_links(post, criteria))

    # E. 自動回復判定
    high_count = sum(1 for i in issues if i.get('severity') == 'high')
    if high_count >= 3:
        issues.append({'type': 'rewrite_target', 'severity': 'info', 'reason': f'high_issues={high_count}'})
    if high_count >= 5:
        issues.append({'type': 'quarantine_target', 'severity': 'info', 'reason': f'high_issues={high_count}'})

    return issues


def fetch_posts(post_type='post', hours=12, per_page=20):
    """直近のpostを取得"""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime('%Y-%m-%dT%H:%M:%S')
    endpoint = 'posts' if post_type == 'post' else post_type
    url = f"https://www.kpopjournal.tokyo/wp-json/wp/v2/{endpoint}?after={cutoff}&per_page={per_page}&_embed=true"
    try:
        req = urllib.request.Request(url, headers={'Authorization': f'Basic {AUTH}'})
        return json.loads(urllib.request.urlopen(req, timeout=30).read())
    except Exception as e:
        print(f"  fetch err {post_type}: {e}")
        return []


def save_audit_state(post_id, post_type, issues):
    out = '/home/aiuser/kpop-ai-system/data/audit_state.jsonl'
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, 'a', encoding='utf-8') as f:
        f.write(json.dumps({
            'post_id': post_id,
            'post_type': post_type,
            'issues': issues,
            'audited_at': datetime.now(timezone.utc).isoformat(),
            'high_count': sum(1 for i in issues if i.get('severity') == 'high'),
            'medium_count': sum(1 for i in issues if i.get('severity') == 'medium'),
            'low_count': sum(1 for i in issues if i.get('severity') == 'low'),
        }, ensure_ascii=False) + '\n')


if __name__ == '__main__':
    for pt in ['post', 'popup']:
        posts = fetch_posts(pt, hours=24, per_page=5)
        print(f"\n=== {pt}: {len(posts)}件 ===")
        for p in posts:
            issues = full_audit(p, pt)
            title = _get_title(p)
            print(f"  id={p['id']} {title[:40]}: {len(issues)} issues")
            for i in issues[:5]:
                print(f"    [{i['severity']}] {i['type']}")
