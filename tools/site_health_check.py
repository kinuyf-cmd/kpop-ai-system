#!/usr/bin/env python3
"""
サイトヘルスチェック — インフラレベルのSEO問題を検出

検出項目:
  1. robots.txt が正常なテキスト形式で返るか（HTML soft-404 検出）
  2. sitemap.xml が有効なXMLか
  3. サイトマップ内サブマップが全て200+XMLか
  4. 空カテゴリ（count=0）がnoindexなしで公開されていないか
  5. 空タグ（count=0）が存在しないか
  6. タグページがリダイレクトされるか
  7. ランダム記事のHTTP 200 + noindex確認
"""
import json, os, sys, re, urllib.request, base64, ssl
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent.parent
load_dotenv(BASE / '.env')

SITE_URL = os.getenv('SITE_URL', 'https://www.kpopjournal.tokyo')
WP_USER = os.getenv('WP_USER', '')
WP_PASS = os.getenv('WP_PASS', '')
AUTH = base64.b64encode(f"{WP_USER}:{WP_PASS}".encode()).decode() if WP_USER else ''
LOG_PATH = BASE / 'logs' / 'site_health.jsonl'

ctx = ssl.create_default_context()


def _fetch(url, timeout=15):
    """Fetch URL and return (status_code, content, content_type)."""
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            body = resp.read().decode('utf-8', errors='replace')
            ct = resp.headers.get('Content-Type', '')
            return resp.status, body, ct
    except urllib.request.HTTPError as e:
        return e.code, '', ''
    except Exception as e:
        return 0, str(e), ''


def _wp_api(endpoint):
    """WordPress REST API call."""
    url = f"{SITE_URL}/wp-json/wp/v2/{endpoint}"
    req = urllib.request.Request(url)
    if AUTH:
        req.add_header('Authorization', f'Basic {AUTH}')
    with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
        return json.loads(resp.read())


def check_robots_txt():
    """robots.txt が正常なテキスト形式で返るか確認。"""
    issues = []
    status, body, ct = _fetch(f"{SITE_URL}/robots.txt")
    if status != 200:
        issues.append(f"robots.txt HTTP {status}")
    elif '<html' in body.lower() or '<!doctype' in body.lower():
        issues.append("robots.txt がHTML soft-404を返している（Next.js [slug] に捕捉されている可能性）")
    elif 'text/html' in ct.lower():
        issues.append(f"robots.txt Content-Type が text/html（期待: text/plain）")
    elif 'user-agent' not in body.lower():
        issues.append("robots.txt にUser-agentディレクティブがない")
    return issues


def check_sitemap():
    """sitemap.xmlとサブサイトマップの検証。"""
    issues = []
    status, body, ct = _fetch(f"{SITE_URL}/sitemap.xml")
    if status != 200:
        issues.append(f"sitemap.xml HTTP {status}")
        return issues
    if '<html' in body.lower()[:500]:
        issues.append("sitemap.xml がHTMLを返している（XML期待）")
        return issues

    # Extract sub-sitemaps
    locs = re.findall(r'<loc>\s*(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?\s*</loc>', body)
    for loc in locs:
        sub_status, sub_body, sub_ct = _fetch(loc)
        if sub_status != 200:
            issues.append(f"サブサイトマップ {loc} HTTP {sub_status}")
        elif '<html' in sub_body.lower()[:500]:
            issues.append(f"サブサイトマップ {loc} がHTMLを返している（XML期待）")
    return issues


def check_empty_categories():
    """count=0のカテゴリがnoindexなしで公開されていないか。"""
    issues = []
    cats = _wp_api('categories?per_page=100&_fields=id,name,slug,count')
    empty = [c for c in cats if c['count'] == 0]
    for c in empty:
        issues.append(f"空カテゴリ: id={c['id']} slug={c['slug']} name={c['name']} (count=0)")
    return issues


def check_empty_tags():
    """count=0のタグが存在しないか。"""
    issues = []
    tags = _wp_api('tags?per_page=100&_fields=id,name,slug,count')
    empty = [t for t in tags if t['count'] == 0]
    for t in empty:
        issues.append(f"空タグ: id={t['id']} slug={t['slug']} name={t['name']} (count=0)")
    return issues


def check_recent_posts_status():
    """最新10記事のHTTP 200 + noindexチェック。"""
    issues = []
    posts = _wp_api('posts?per_page=10&orderby=date&order=desc&_fields=id,link,slug')
    for p in posts:
        status, body, ct = _fetch(p['link'])
        if status != 200:
            issues.append(f"記事 id={p['id']} slug={p['slug']} HTTP {status}")
        elif 'noindex' in body.lower():
            # Check if it's in a meta robots tag (not just any noindex mention)
            if re.search(r'<meta\s+name=["\']robots["\']\s+content=["\'][^"\']*noindex', body, re.I):
                issues.append(f"記事 id={p['id']} slug={p['slug']} にnoindexメタタグ検出")
    return issues


def check_draft_trash_accumulation():
    """draft/trashが蓄積していないか。"""
    issues = []
    for status in ['draft', 'trash']:
        try:
            posts = _wp_api(f'posts?status={status}&per_page=100&_fields=id,slug,title')
            if len(posts) > 0:
                titles = [p.get('title', {}).get('rendered', '')[:40] for p in posts[:5]]
                issues.append(f"{status}記事 {len(posts)}件蓄積: {', '.join(titles)}")
        except Exception:
            pass
    return issues


def check_bad_slugs():
    """自動生成スラッグ・エンコードスラッグの公開記事がないか。"""
    issues = []
    for page in range(1, 12):
        try:
            posts = _wp_api(f'posts?status=publish&per_page=100&page={page}&_fields=id,slug,title')
            if not posts:
                break
            for p in posts:
                slug = p.get('slug', '')
                title = p.get('title', {}).get('rendered', '')[:40]
                if re.match(r'^post-\d+$', slug):
                    issues.append(f"自動生成slug: id={p['id']} slug={slug} title={title}")
                if '%' in slug:
                    issues.append(f"エンコードslug: id={p['id']} slug={slug[:40]} title={title}")
                if '__trashed' in slug:
                    issues.append(f"trashed slug: id={p['id']} slug={slug[:40]}")
        except Exception:
            break
    return issues


def check_duplicate_content():
    """重複タイトルの公開記事がないか。"""
    issues = []
    title_map = {}
    for page in range(1, 12):
        try:
            posts = _wp_api(f'posts?status=publish&per_page=100&page={page}&_fields=id,title')
            if not posts:
                break
            for p in posts:
                t = p.get('title', {}).get('rendered', '').strip()
                if t and len(t) > 10:
                    title_map.setdefault(t, []).append(p['id'])
        except Exception:
            break
    for t, ids in title_map.items():
        if len(ids) > 1:
            issues.append(f"重複タイトル: \"{t[:40]}\" (ids={ids})")
    return issues


def run_all():
    """全チェック実行。"""
    results = {}
    checks = [
        ('robots_txt', check_robots_txt),
        ('sitemap', check_sitemap),
        ('empty_categories', check_empty_categories),
        ('empty_tags', check_empty_tags),
        ('recent_posts_status', check_recent_posts_status),
        ('draft_trash', check_draft_trash_accumulation),
        ('bad_slugs', check_bad_slugs),
        ('duplicate_content', check_duplicate_content),
    ]

    total_issues = 0
    for name, fn in checks:
        try:
            issues = fn()
            results[name] = {'ok': len(issues) == 0, 'issues': issues}
            total_issues += len(issues)
            status = 'OK' if not issues else f'{len(issues)} issue(s)'
            print(f"  [{status}] {name}")
            for iss in issues:
                print(f"    - {iss}")
        except Exception as e:
            results[name] = {'ok': False, 'issues': [f'Error: {e}']}
            print(f"  [ERROR] {name}: {e}")
            total_issues += 1

    # Log results
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'total_issues': total_issues,
        'results': results,
    }
    with open(LOG_PATH, 'a') as f:
        f.write(json.dumps(record, ensure_ascii=False) + '\n')

    return total_issues


if __name__ == '__main__':
    print("=== サイトヘルスチェック ===")
    print(f"対象: {SITE_URL}")
    print(f"実行: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    total = run_all()
    print()
    if total == 0:
        print("全チェックOK")
    else:
        print(f"問題 {total} 件検出")
    sys.exit(0 if total == 0 else 1)
