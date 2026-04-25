#!/usr/bin/env python3
"""popup_signals.jsonl から記事生成 → WP popup post type に投稿"""
import sys, os, json, re, urllib.request, base64
sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
load_dotenv()

WP_USER = os.getenv('WP_USER', '')
WP_PASS = os.getenv('WP_PASS', '')
AUTH = base64.b64encode(f"{WP_USER}:{WP_PASS}".encode()).decode()
SIGNALS = '/home/aiuser/kpop-ai-system/data/popup_signals.jsonl'
PROCESSED = '/home/aiuser/kpop-ai-system/data/popup_processed.jsonl'
JST = timezone(timedelta(hours=9))


def is_processed(url):
    if not os.path.exists(PROCESSED):
        return False
    with open(PROCESSED, encoding='utf-8') as f:
        for line in f:
            try:
                if json.loads(line).get('url') == url:
                    return True
            except:
                pass
    return False


def mark_processed(url, post_id, status):
    with open(PROCESSED, 'a', encoding='utf-8') as f:
        f.write(json.dumps({
            'url': url, 'post_id': post_id, 'status': status,
            'ts': datetime.now(JST).isoformat()
        }, ensure_ascii=False) + '\n')


def fetch_full_content(url):
    """記事URLから全文取得 (簡易)"""
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        html = urllib.request.urlopen(req, timeout=20).read().decode('utf-8', errors='ignore')
        for pat in [r'<article[^>]*>(.*?)</article>',
                    r'<div[^>]*class="[^"]*entry-content[^"]*"[^>]*>(.*?)</div>',
                    r'<div[^>]*class="[^"]*post-content[^"]*"[^>]*>(.*?)</div>']:
            m = re.search(pat, html, re.DOTALL)
            if m:
                content = m.group(1)
                text = re.sub(r'<[^>]+>', ' ', content)
                text = re.sub(r'\s+', ' ', text).strip()
                if len(text) > 200:
                    return text[:3000]
        return None
    except Exception as e:
        print(f"  fetch err: {e}")
        return None


def extract_dates(text):
    """期間抽出"""
    patterns = [
        r'(\d{4})年(\d{1,2})月(\d{1,2})日.*?[~〜から至まで\-].*?(\d{1,2})月(\d{1,2})日',
        r'(\d{1,2})月(\d{1,2})日.*?[~〜\-].*?(\d{1,2})月(\d{1,2})日',
        r'(\d{4})/(\d{1,2})/(\d{1,2}).*?[~〜\-].*?(\d{4})/(\d{1,2})/(\d{1,2})',
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            now = datetime.now(JST)
            year = now.year
            try:
                groups = m.groups()
                if len(groups) == 5:
                    sy = int(groups[0])
                    sm, sd, em, ed = map(int, groups[1:])
                    start = datetime(sy, sm, sd, tzinfo=JST)
                    end = datetime(sy, em, ed, tzinfo=JST)
                elif len(groups) == 6:
                    sy, sm, sd, ey, em, ed = map(int, groups)
                    start = datetime(sy, sm, sd, tzinfo=JST)
                    end = datetime(ey, em, ed, tzinfo=JST)
                else:
                    sm, sd, em, ed = map(int, groups[:4])
                    start = datetime(year, sm, sd, tzinfo=JST)
                    end = datetime(year, em, ed, tzinfo=JST)
                return start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d')
            except:
                pass
    return None, None


def determine_status(start_date, end_date):
    """開催予定/開催中/終了 判定"""
    if not start_date:
        return 'unknown'
    today = datetime.now(JST).date()
    try:
        s = datetime.strptime(start_date, '%Y-%m-%d').date()
        e = datetime.strptime(end_date, '%Y-%m-%d').date() if end_date else s
        if today < s:
            return 'upcoming'
        elif s <= today <= e:
            return 'ongoing'
        else:
            return 'ended'
    except:
        return 'unknown'


def generate_article_with_gpt(signal, full_text):
    """GPTで記事生成"""
    key = os.getenv('OPENAI_API_KEY')
    if not key:
        print("  OPENAI_API_KEY未設定")
        return None

    prompt = f"""以下のポップアップ情報から、K-POPファン向けのSEO最適化記事を生成してください。

【元情報】
タイトル: {signal['title']}
本文抜粋: {full_text[:1500] if full_text else 'なし'}
都市: {signal.get('city', '不明')}
情報源: {signal.get('source', '不明')}

【出力要件】
- HTMLで本文400-800字
- h2見出し使用 (例: <h2>開催概要</h2>, <h2>見どころ</h2>, <h2>アクセス</h2>)
- 文末バリエーション: ~開催/~オープン/~登場/~実施
- ポップアップ情報として読者が知りたい: 期間/場所/見どころ/予約要否/アクセス
- 末尾に必ず以下を入れる:
  <p class="kpj-disclaimer">※情報は変更になる場合があります。最新情報は公式SNSをご確認ください。</p>

【出力】HTML本文のみ (説明・前置き不要)"""

    body = json.dumps({
        'model': 'gpt-4o-mini',
        'messages': [{'role': 'user', 'content': prompt}],
        'temperature': 0.7,
        'max_tokens': 1500,
    }).encode()

    try:
        req = urllib.request.Request('https://api.openai.com/v1/chat/completions',
            data=body, headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'})
        r = json.loads(urllib.request.urlopen(req, timeout=60).read())
        return r['choices'][0]['message']['content'].strip()
    except Exception as e:
        print(f"  GPT err: {e}")
        return None


def post_to_wp_popup(signal, content, status):
    """WP popup post type に投稿"""
    title = signal.get('title', '')[:60]

    meta = {
        '_popup_city': signal.get('city', ''),
        '_popup_official_url': signal.get('url', ''),
        '_popup_status': status,
    }
    if signal.get('start_date'):
        meta['_popup_start_date'] = signal['start_date']
    if signal.get('end_date'):
        meta['_popup_end_date'] = signal['end_date']

    body = json.dumps({
        'title': title,
        'content': content,
        'status': 'publish',
        'meta': meta,
    }).encode()

    try:
        req = urllib.request.Request(
            'https://www.kpopjournal.tokyo/wp-json/wp/v2/popup',
            data=body, method='POST',
            headers={'Authorization': f'Basic {AUTH}', 'Content-Type': 'application/json'})
        r = json.loads(urllib.request.urlopen(req, timeout=30).read())
        return r.get('id')
    except Exception as e:
        print(f"  WP err: {e}")
        return None


def main(max_articles=10):
    if not os.path.exists(SIGNALS):
        print("popup_signals.jsonl なし")
        return

    signals = []
    with open(SIGNALS, encoding='utf-8') as f:
        for line in f:
            try:
                s = json.loads(line)
                if not is_processed(s['url']):
                    signals.append(s)
            except:
                pass

    print(f"未処理signals: {len(signals)}件")

    created = 0
    for sig in signals[:max_articles]:
        print(f"\n処理中: {sig['title'][:50]}")

        full_text = fetch_full_content(sig['url'])

        start, end = extract_dates(f"{sig['title']} {full_text or ''}")
        if start:
            sig['start_date'] = start
        if end:
            sig['end_date'] = end
        status = determine_status(start, end)
        sig['status_label'] = status

        content = generate_article_with_gpt(sig, full_text)
        if not content or len(content) < 200:
            print(f"  記事生成失敗、スキップ")
            mark_processed(sig['url'], None, 'gen_failed')
            continue

        post_id = post_to_wp_popup(sig, content, status)
        if post_id:
            print(f"  post_id={post_id} status={status}")
            mark_processed(sig['url'], post_id, 'published')
            created += 1
        else:
            mark_processed(sig['url'], None, 'wp_failed')

    print(f"\n公開: {created}件")


if __name__ == '__main__':
    main(max_articles=10)
