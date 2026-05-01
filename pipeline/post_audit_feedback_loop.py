#!/usr/bin/env python3
"""
投稿10分後の自動再監査+学習+担当社員指摘+再発防止
cron: 毎時10分・40分
"""
import os, json, urllib.request, base64, re, sys
sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
load_dotenv('/home/aiuser/kpop-ai-system/.env')

WP_USER = os.getenv('WP_USER', '')
WP_PASS = os.getenv('WP_PASS', '')
AUTH = base64.b64encode(f"{WP_USER}:{WP_PASS}".encode()).decode()
JST = timezone(timedelta(hours=9))

AGENT_PATTERNS = {
    'feature_article_writer': {
        'patterns': ['聖地巡礼', 'モデルコース', '推し活グッズ', '推しメイク', '韓国ドラマ',
                     'カラコンレビュー', '韓国カフェ', 'ファンチャント', 'お土産まとめ'],
    },
    'breaking_news_writer': {
        'patterns': ['速報', 'BREAKING', '【速報】', '【韓国メディア速報】'],
    },
    'popup_writer': {'patterns': []},
}


def detect_agent(title, content, post_type='posts'):
    if post_type == 'popup':
        return 'popup_writer'
    text = title + ' ' + content[:500]
    for agent, cfg in AGENT_PATTERNS.items():
        if any(p in text for p in cfg.get('patterns', [])):
            return agent
    return 'unknown'


def get_recent_posts(minutes_ago=5, max_age_minutes=60):
    now = datetime.now(timezone.utc)
    after = (now - timedelta(minutes=max_age_minutes)).isoformat()
    before = (now - timedelta(minutes=minutes_ago)).isoformat()
    posts = []
    for endpoint in ['posts', 'popup']:
        try:
            url = f"https://www.kpopjournal.tokyo/wp-json/wp/v2/{endpoint}?after={after}&before={before}&per_page=20&_fields=id,title,content,featured_media,slug,date,categories,link&context=edit"
            req = urllib.request.Request(url, headers={'Authorization': f'Basic {AUTH}'})
            data = json.loads(urllib.request.urlopen(req, timeout=20).read())
            for p in data:
                p['_post_type'] = endpoint
                posts.append(p)
        except:
            pass
    return posts


def audit_post(post):
    pid = post['id']
    title = post.get('title', {}).get('rendered', '') if isinstance(post.get('title'), dict) else ''
    content = post.get('content', {}).get('raw') or post.get('content', {}).get('rendered', '')
    slug = post.get('slug', '')
    fm = post.get('featured_media', 0)
    issues = []

    if not fm or fm == 0:
        issues.append({'kind': 'no_thumbnail', 'severity': 'high'})
    if '```html' in content or re.search(r'```\s*$', content, re.MULTILINE):
        issues.append({'kind': 'codeblock_leak', 'severity': 'high'})
    if re.search(r'(?:あわせて読みたい|関連記事|おすすめ記事)', content):
        issues.append({'kind': 'recommended_section_leak', 'severity': 'medium'})
    if '%' in slug or any(ord(c) > 127 for c in slug):
        issues.append({'kind': 'slug_encoded', 'severity': 'medium'})
    plain = re.sub(r'<[^>]+>', '', content)
    if len(plain) < 200:
        issues.append({'kind': 'too_short', 'severity': 'high'})


    # アーティストカテゴリ漏れ自動修正
    try:
        from lib.auto_category import ensure_artist_categories
        title = post.get('title', {}).get('rendered', '') if isinstance(post.get('title'), dict) else ''
        content_text = post.get('content', {}).get('rendered', '') if isinstance(post.get('content'), dict) else ''
        existing_cats = post.get('categories', [])
        ensure_artist_categories(post['id'], title, content_text, existing_cats)
    except: pass

    return {
        'post_id': pid,
        'title': title[:60],
        'agent': detect_agent(title, content, post.get('_post_type', 'posts')),
        'post_type': post.get('_post_type', 'posts'),
        'issues': issues,
    }


def auto_fix(post, result):
    pid = post['id']
    content = post.get('content', {}).get('raw') or post.get('content', {}).get('rendered', '')
    issue_kinds = {i['kind'] for i in result['issues']}
    payload = {}

    if any(k in issue_kinds for k in ['codeblock_leak', 'recommended_section_leak']):
        new_content = re.sub(r'```html\s*', '', content)
        new_content = re.sub(r'```\s*', '', new_content)
        new_content = re.sub(r'<(?:h[1-6])[^>]*>\s*(?:あわせて読みたい|関連記事|おすすめ記事)[^<]*</h[1-6]>', '', new_content, flags=re.IGNORECASE)

        def remove_internal(m):
            if 'kpj-cta-' in m.group(0) or 'kpj-aff-' in m.group(0):
                return m.group(0)
            return ''
        new_content = re.sub(r'<a [^>]*href="https?://(?:www\.)?kpopjournal\.tokyo[^"]*"[^>]*>[^<]*</a>', remove_internal, new_content)

        if new_content != content:
            payload['content'] = new_content

    if not payload:
        return False

    api_path = 'posts' if result['post_type'] == 'posts' else 'popup'
    body = json.dumps(payload).encode()
    try:
        req = urllib.request.Request(
            f"https://www.kpopjournal.tokyo/wp-json/wp/v2/{api_path}/{pid}",
            data=body, method='POST',
            headers={'Authorization': f'Basic {AUTH}', 'Content-Type': 'application/json'})
        urllib.request.urlopen(req, timeout=30)
        return True
    except:
        return False


def update_agent_lessons(audit_results):
    lessons_dir = '/home/aiuser/kpop-ai-system/docs/agent_lessons'
    os.makedirs(lessons_dir, exist_ok=True)

    agent_errors = {}
    for r in audit_results:
        agent_errors.setdefault(r['agent'], []).extend(r['issues'])

    # LLM校閲結果があれば統合
    llm_dir = '/home/aiuser/kpop-ai-system/logs/llm_audit'
    if os.path.exists(llm_dir):
        import glob
        for fp in sorted(glob.glob(f'{llm_dir}/*.json'))[-1:]:
            try:
                data = json.load(open(fp))
                for lr in data.get('results', []):
                    for c in lr.get('critical', []):
                        agent_errors.setdefault('unknown', []).append({'kind': f'llm_critical: {c[:40]}', 'severity': 'high'})
                    for h in lr.get('high', []):
                        agent_errors.setdefault('unknown', []).append({'kind': f'llm_high: {h[:40]}', 'severity': 'high'})
            except:
                pass

    for agent, errors in agent_errors.items():
        if not errors:
            continue
        kind_counts = {}
        for e in errors:
            kind_counts[e['kind']] = kind_counts.get(e['kind'], 0) + 1

        fp = f'{lessons_dir}/{agent}.md'
        existing = open(fp).read() if os.path.exists(fp) else f'# {agent} 品質ログ\n\n'
        ts = datetime.now(JST).strftime('%Y-%m-%d %H:%M')
        section = f'\n## {ts} 監査結果\n\n'
        for kind, count in sorted(kind_counts.items(), key=lambda x: -x[1]):
            section += f'- {kind}: {count}件\n'
        with open(fp, 'w') as f:
            f.write(existing + section)


SEEN_PATH = '/home/aiuser/kpop-ai-system/data/feedback_loop_seen.json'

def _load_seen() -> set:
    if os.path.exists(SEEN_PATH):
        try:
            data = json.load(open(SEEN_PATH))
            return set(data.get('ids', []))
        except (json.JSONDecodeError, OSError):
            pass
    return set()

def _save_seen(seen: set):
    # 直近200件のみ保持
    ids = sorted(seen)[-200:]
    with open(SEEN_PATH, 'w') as f:
        json.dump({'ids': ids}, f)


def main():
    print(f"=== post_audit_feedback_loop {datetime.now(JST).strftime('%Y-%m-%d %H:%M')} ===")
    posts = get_recent_posts(minutes_ago=5, max_age_minutes=40)
    seen = _load_seen()
    posts = [p for p in posts if p['id'] not in seen]
    if not posts:
        print("  対象投稿なし")
        return

    print(f"  対象: {len(posts)}件")
    audit_results = []
    fix_count = 0

    for post in posts:
        result = audit_post(post)
        audit_results.append(result)
        if result['issues']:
            print(f"  !! id={result['post_id']} [{result['agent']}] {result['title']}")
            for iss in result['issues']:
                print(f"     [{iss['severity']}] {iss['kind']}")
            if auto_fix(post, result):
                fix_count += 1
                print(f"     -> 自動修正OK")
        else:
            print(f"  OK id={result['post_id']} クリーン")

    update_agent_lessons(audit_results)

    # 監査済みIDを記録（重複防止）
    seen.update(r['post_id'] for r in audit_results)
    _save_seen(seen)

    log = '/home/aiuser/kpop-ai-system/logs/post_audit_feedback.jsonl'
    os.makedirs(os.path.dirname(log), exist_ok=True)
    with open(log, 'a', encoding='utf-8') as f:
        f.write(json.dumps({
            'ts': datetime.now(timezone.utc).isoformat(),
            'audited': len(audit_results),
            'fixed': fix_count,
        }, ensure_ascii=False) + '\n')

    print(f"\n{len(audit_results)}件監査 / {fix_count}件修正")


if __name__ == '__main__':
    main()
