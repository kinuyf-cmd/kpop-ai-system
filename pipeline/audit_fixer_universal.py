#!/usr/bin/env python3
"""audit_state.jsonl から修正対象を読み、自動修正実行 (post + popup共通)"""
import sys, os, json, re, urllib.request, base64
sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
load_dotenv('/home/aiuser/kpop-ai-system/.env')

WP_USER = os.getenv('WP_USER', '')
WP_PASS = os.getenv('WP_PASS', '')
AUTH = base64.b64encode(f"{WP_USER}:{WP_PASS}".encode()).decode()

FIXABLE_TYPES = {
    'text_ai_mention', 'text_meta_phrase', 'text_markdown_leak',
    'text_casual_greeting', 'text_casual_question', 'text_salesy_ending',
    'text_salesy_cta', 'text_broken_sentence', 'text_empty_tag',
    'text_repeated_char', 'text_casual_address', 'text_monotonous_ending',
    'unclosed_h2', 'unclosed_p',
    'content_short', 'few_internal_links',
    'slug_encoded',
    'meta_desc_short', 'no_meta_description',
}


def fetch_post(post_id, post_type):
    endpoint = 'posts' if post_type == 'post' else post_type
    url = f"https://www.kpopjournal.tokyo/wp-json/wp/v2/{endpoint}/{post_id}?_embed=true"
    try:
        req = urllib.request.Request(url, headers={'Authorization': f'Basic {AUTH}'})
        return json.loads(urllib.request.urlopen(req, timeout=20).read())
    except Exception as e:
        print(f"  fetch err: {e}")
        return None


def update_post(post_id, post_type, payload):
    endpoint = 'posts' if post_type == 'post' else post_type
    url = f"https://www.kpopjournal.tokyo/wp-json/wp/v2/{endpoint}/{post_id}"
    body = json.dumps(payload).encode()
    try:
        req = urllib.request.Request(url, data=body, method='POST',
            headers={'Authorization': f'Basic {AUTH}', 'Content-Type': 'application/json'})
        urllib.request.urlopen(req, timeout=30)
        return True
    except Exception as e:
        print(f"  update err: {e}")
        return False


def rewrite_with_gpt(post, issues, post_type):
    """GPT-4o-miniで本文修正"""
    key = os.getenv('OPENAI_API_KEY')
    if not key:
        return None

    title = post.get('title', {}).get('rendered', '') if isinstance(post.get('title'), dict) else ''
    content = post.get('content', {}).get('rendered', '') if isinstance(post.get('content'), dict) else ''
    issue_types = list(set(i['type'] for i in issues if i['type'] in FIXABLE_TYPES))

    if post_type == 'popup':
        structure = """必須h2: イベント概要/開催詳細/特典・限定アイテム/アクセス
末尾必須: <p class="kpj-disclaimer">※情報は変更になる場合があります。最新情報は公式SNSをご確認ください。</p>"""
    else:
        structure = "リード→詳細→まとめ三段構成、h2見出し2つ以上"

    prompt = f"""以下のK-POP記事を問題を解消した自然な記事に書き直してください。

【タイトル】{title}
【現在の本文】{content[:2500]}
【検出問題】{', '.join(issue_types)}

【修正要件】
- 「以上です」「いかがでしょうか」「お楽しみに」「皆さん」等の蛇足削除
- AI/ChatGPT/Claude等メタ言及完全除去
- HTMLタグ閉じ修正
- 文末バリエーション (同じ語尾3連続禁止)
- 内部リンク2本: <a href="https://www.kpopjournal.tokyo/category/news/">最新ニュース</a> 等
- {structure}
- 800-1200字

【出力】HTML本文のみ"""

    body = json.dumps({
        'model': 'gpt-4o-mini',
        'messages': [{'role': 'user', 'content': prompt}],
        'temperature': 0.6,
        'max_tokens': 2000,
    }).encode()

    try:
        req = urllib.request.Request('https://api.openai.com/v1/chat/completions',
            data=body, headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'})
        r = json.loads(urllib.request.urlopen(req, timeout=90).read())
        result = r['choices'][0]['message']['content'].strip()
        return re.sub(r'^```html\s*\n?|```\s*$', '', result, flags=re.MULTILINE)
    except Exception as e:
        print(f"  GPT err: {e}")
        return None


def generate_meta_description(post):
    content = post.get('content', {}).get('rendered', '') if isinstance(post.get('content'), dict) else ''
    plain = re.sub(r'<[^>]+>', '', content).strip()
    plain = re.sub(r'\s+', ' ', plain)
    if len(plain) > 150:
        m = re.search(r'^(.{80,150}?[。!?])', plain)
        if m:
            return m.group(1)
        return plain[:140] + '...'
    return plain[:150]


def main(max_fixes=15):
    audit_log = '/home/aiuser/kpop-ai-system/data/audit_state.jsonl'
    if not os.path.exists(audit_log):
        print("audit_state.jsonl なし")
        return

    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    targets = {}

    with open(audit_log, encoding='utf-8') as f:
        for line in f:
            try:
                rec = json.loads(line)
                audited = datetime.fromisoformat(rec['audited_at'].replace('Z', '+00:00'))
                if audited < cutoff:
                    continue
                fixable = [i for i in rec['issues'] if i['type'] in FIXABLE_TYPES]
                if fixable:
                    key = (rec['post_id'], rec.get('post_type', 'post'))
                    targets[key] = fixable
            except:
                pass

    print(f"自動修正対象: {len(targets)}件")

    fixed = 0
    for (pid, ptype), issues in list(targets.items())[:max_fixes]:
        post = fetch_post(pid, ptype)
        if not post:
            continue

        title = post.get('title', {}).get('rendered', '') if isinstance(post.get('title'), dict) else ''
        print(f"\n[{ptype}] id={pid}: {title[:40]}")

        update_payload = {}

        # slug修正
        if any(i['type'] == 'slug_encoded' for i in issues):
            update_payload['slug'] = f"{ptype}-{pid}"

        # 本文修正
        text_issues = [i for i in issues if i['type'].startswith('text_')
                       or i['type'] in ('unclosed_h2', 'unclosed_p', 'content_short', 'few_internal_links')]
        if text_issues:
            new_content = rewrite_with_gpt(post, text_issues, ptype)
            if new_content and len(new_content) > 200:
                update_payload['content'] = new_content

        # excerpt生成
        if any(i['type'] in ('meta_desc_short', 'no_meta_description') for i in issues):
            update_payload['excerpt'] = generate_meta_description(post)

        if update_payload:
            if update_post(pid, ptype, update_payload):
                fixed += 1
                print(f"  修正完了: {list(update_payload.keys())}")
                fix_log = '/home/aiuser/kpop-ai-system/logs/audit_fixed.jsonl'
                os.makedirs(os.path.dirname(fix_log), exist_ok=True)
                with open(fix_log, 'a', encoding='utf-8') as f:
                    f.write(json.dumps({
                        'post_id': pid, 'post_type': ptype,
                        'fixed_keys': list(update_payload.keys()),
                        'fixed_at': datetime.now(timezone.utc).isoformat(),
                    }, ensure_ascii=False) + '\n')

    print(f"\n{fixed}/{len(targets)}件 自動修正完了")


if __name__ == '__main__':
    main()
