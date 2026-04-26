#!/usr/bin/env python3
"""内部リンク自動挿入 — 辞書ベース (GPT非依存、コスト$0)
cron: 0 3 * * * (毎日03:00)

config/internal_link_dictionary.json のキーワード→URLマッピングで
本文中のキーワードを自動リンク化。
- 既にリンク済みのキーワードはスキップ
- 1記事あたり最大5リンク
- 1キーワードは1記事中1回だけリンク化 (最初の出現)
"""
import sys, os, json, re, argparse, urllib.request, base64
sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
load_dotenv('/home/aiuser/kpop-ai-system/.env')

WP_USER = os.getenv('WP_USER', '')
WP_PASS = os.getenv('WP_PASS', '')
AUTH = base64.b64encode(f"{WP_USER}:{WP_PASS}".encode()).decode()
DICT_FILE = '/home/aiuser/kpop-ai-system/config/internal_link_dictionary.json'
MAX_LINKS_PER_POST = 5
BASE_URL = 'https://www.kpopjournal.tokyo'


def load_dictionary():
    if not os.path.exists(DICT_FILE):
        return {}
    return json.load(open(DICT_FILE, encoding='utf-8'))


def count_internal_links(content):
    return len(re.findall(r'href="https?://(?:www\.)?kpopjournal\.tokyo[^"]*"', content))


def inject_links(content, dictionary, max_new=5):
    """本文中のキーワードをリンク化 (タグ内・既存リンク内はスキップ)"""
    added = 0
    used_keywords = set()

    # Sort by keyword length (longer first to avoid partial matches)
    sorted_kw = sorted(dictionary.keys(), key=len, reverse=True)

    for keyword in sorted_kw:
        if added >= max_new:
            break
        if keyword in used_keywords:
            continue

        url_path = dictionary[keyword]
        full_url = f'{BASE_URL}{url_path}'

        # Already linked to this URL?
        if full_url in content or url_path in content:
            continue

        # Find keyword in text (not inside HTML tags or existing links)
        # Pattern: keyword that is NOT inside <a>...</a> or inside a tag attribute
        # Simple approach: split by tags, process text nodes only
        def replace_in_text(match):
            nonlocal added
            if added >= max_new:
                return match.group(0)
            text = match.group(0)
            if keyword in text and keyword not in used_keywords:
                # Only replace first occurrence
                new_text = text.replace(
                    keyword,
                    f'<a href="{full_url}">{keyword}</a>',
                    1)
                if new_text != text:
                    added += 1
                    used_keywords.add(keyword)
                    return new_text
            return text

        # Match text between tags (excluding content inside <a> tags)
        # Remove existing <a>...</a> temporarily, process, then restore
        # Simpler: use regex to find keyword outside of tags
        pattern = re.compile(
            r'(?<=>)([^<]*?)(' + re.escape(keyword) + r')([^<]*?)(?=<)',
        )

        def replacer(m):
            nonlocal added
            if added >= max_new or keyword in used_keywords:
                return m.group(0)
            # Check we're not inside an <a> tag by looking backwards
            prefix = content[:m.start()]
            # Count unclosed <a> tags
            open_a = len(re.findall(r'<a\b', prefix))
            close_a = len(re.findall(r'</a>', prefix))
            if open_a > close_a:
                return m.group(0)  # Inside an <a> tag, skip

            added += 1
            used_keywords.add(keyword)
            return m.group(1) + f'<a href="{full_url}">{keyword}</a>' + m.group(3)

        new_content = pattern.sub(replacer, content, count=1)
        if new_content != content:
            content = new_content

    return content, added


def fetch_posts(post_type='posts', hours=None, per_page=50, date_after=None):
    all_results = []
    page_size = min(per_page, 100)
    for page_num in range(1, (per_page // page_size) + 2):
        params = f'per_page={page_size}&page={page_num}&_fields=id,title,content,date'
        if date_after:
            params += f'&after={date_after}'
        elif hours:
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime('%Y-%m-%dT%H:%M:%S')
            params += f'&after={cutoff}'
        url = f'{BASE_URL}/wp-json/wp/v2/{post_type}?{params}'
        try:
            req = urllib.request.Request(url, headers={'Authorization': f'Basic {AUTH}'})
            data = json.loads(urllib.request.urlopen(req, timeout=20).read())
            if not data:
                break
            all_results.extend(data)
            if len(all_results) >= per_page:
                break
        except Exception as e:
            print(f"  fetch err: {e}")
            break
    return all_results[:per_page]


def update_post(post_id, post_type, content):
    endpoint = post_type
    url = f'{BASE_URL}/wp-json/wp/v2/{endpoint}/{post_id}'
    body = json.dumps({'content': content}).encode()
    req = urllib.request.Request(url, data=body, method='POST',
        headers={'Authorization': f'Basic {AUTH}', 'Content-Type': 'application/json'})
    r = json.loads(urllib.request.urlopen(req, timeout=20).read())
    return r.get('id')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--date', default=None, help='YYYY-MM-DD')
    parser.add_argument('--hours', type=int, default=None)
    parser.add_argument('--limit', type=int, default=100)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    dictionary = load_dictionary()
    print(f"=== internal_link_injector {datetime.now().isoformat()} ===")
    print(f"  辞書: {len(dictionary)}件")

    date_after = None
    if args.date:
        date_after = f'{args.date}T00:00:00'
    elif args.hours:
        date_after = (datetime.now(timezone.utc) - timedelta(hours=args.hours)).strftime('%Y-%m-%dT%H:%M:%S')

    all_posts = []
    for ptype in ['posts', 'popup']:
        posts = fetch_posts(ptype, date_after=date_after, per_page=args.limit)
        for p in posts:
            p['_endpoint'] = ptype
        all_posts.extend(posts)

    print(f"  対象: {len(all_posts)}件")

    updated = 0
    total_links_added = 0
    for p in all_posts[:args.limit]:
        pid = p['id']
        content = p['content']['rendered'] if isinstance(p['content'], dict) else p['content']
        existing = count_internal_links(content)

        new_content, added = inject_links(content, dictionary, max_new=MAX_LINKS_PER_POST)
        if added > 0:
            if args.dry_run:
                print(f"  [dry] id={pid} +{added} links (existing={existing})")
            else:
                try:
                    update_post(pid, p['_endpoint'], new_content)
                    print(f"  id={pid} +{added} links (existing={existing}→{existing+added})")
                    updated += 1
                except Exception as e:
                    print(f"  id={pid} ERR: {e}")
            total_links_added += added

    print(f"\n更新: {updated}件 / リンク追加: {total_links_added}件")


if __name__ == '__main__':
    main()
