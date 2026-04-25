#!/usr/bin/env python3
"""GPT生成記事に紛れ込んだ404内部リンクの一括除去"""
import os, json, urllib.request, base64, re
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
load_dotenv('/home/aiuser/kpop-ai-system/.env')

WP_USER = os.getenv('WP_USER', '')
WP_PASS = os.getenv('WP_PASS', '')
AUTH = base64.b64encode(f"{WP_USER}:{WP_PASS}".encode()).decode()


def get_recent_posts(days=30, per_page=100):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime('%Y-%m-%dT%H:%M:%S')
    url = f"https://www.kpopjournal.tokyo/wp-json/wp/v2/posts?after={cutoff}&per_page={per_page}&_fields=id,title,content&context=edit"
    req = urllib.request.Request(url, headers={'Authorization': f'Basic {AUTH}'})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=30).read())
    except Exception as e:
        print(f"取得err: {e}")
        return []


def cleanup_post_content(content):
    original = content

    # 「あわせて読みたい」セクション全体を除去
    content = re.sub(
        r'<(?:h[2-4]|p|div)[^>]*>\s*(?:あわせて読みたい|関連記事|おすすめ記事|読まれている記事)[^<]*</[^>]+>\s*(?:<(?:ul|ol)[^>]*>.*?</(?:ul|ol)>)?',
        '', content, flags=re.DOTALL
    )

    # kpopjournal.tokyoへの内部リンク (CTAブロック外) をテキストに置換
    # CTAブロック内のリンクは保護
    def replace_internal_link(m):
        full = m.group(0)
        # CTAブロック内なら保護
        if 'kpj-aff-' in full or 'kpj-cta-' in full:
            return full
        # テキストだけ残す
        text_match = re.search(r'>([^<]+)</a>', full)
        return text_match.group(1) if text_match else ''

    content = re.sub(
        r'<a [^>]*href="https?://(?:www\.)?kpopjournal\.tokyo/[^"]*"[^>]*>[^<]*</a>',
        replace_internal_link, content
    )

    # 疑わしいリンクパターンを除去
    suspicious = [
        r'<a [^>]*>[^<]*(?:PDRNおすすめ|CICAスキンケア|アイテム選びはこちら|完全版はこちら|チェックする)[^<]*</a>',
    ]
    for pat in suspicious:
        content = re.sub(pat, '', content, flags=re.IGNORECASE)

    # 空のh2/h3/h4
    content = re.sub(r'<h[2-4][^>]*>\s*</h[2-4]>', '', content)
    # 連続空段落
    content = re.sub(r'(<p[^>]*>\s*</p>\s*){2,}', '', content)
    content = re.sub(r'\n{3,}', '\n\n', content)

    return content, content != original


def update_post(post_id, new_content):
    body = json.dumps({'content': new_content}).encode()
    try:
        req = urllib.request.Request(
            f"https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/{post_id}",
            data=body, method='POST',
            headers={'Authorization': f'Basic {AUTH}', 'Content-Type': 'application/json'})
        urllib.request.urlopen(req, timeout=30).read()
        return True
    except Exception as e:
        print(f"  更新err post_id={post_id}: {e}")
        return False


def main():
    print("=== 404リンク一括除去 ===")
    posts = get_recent_posts(days=30, per_page=100)
    print(f"対象: {len(posts)}件")

    fixed = 0
    for post in posts:
        pid = post['id']
        content = post.get('content', {}).get('raw') or post.get('content', {}).get('rendered', '')
        title = post.get('title', {}).get('rendered', '')[:40] if isinstance(post.get('title'), dict) else ''

        new_content, changed = cleanup_post_content(content)
        if not changed:
            continue

        if update_post(pid, new_content):
            fixed += 1
            print(f"  OK post_id={pid} {title}")

    print(f"\n{fixed}件 修正完了")

    log = '/home/aiuser/kpop-ai-system/logs/cleanup_404_links.jsonl'
    os.makedirs(os.path.dirname(log), exist_ok=True)
    with open(log, 'a', encoding='utf-8') as f:
        f.write(json.dumps({
            'ts': datetime.now(timezone.utc).isoformat(),
            'attempted': len(posts), 'fixed': fixed,
        }, ensure_ascii=False) + '\n')


if __name__ == '__main__':
    main()
