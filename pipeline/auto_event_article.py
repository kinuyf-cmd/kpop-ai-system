#!/usr/bin/env python3
"""韓国メディアsignalsからイベント記事を自動生成+WP投稿

トリガー: trend_signals.jsonl の韓国ソースで콘서트/팬미팅等を含むsignal
条件: 複数ソース一致 OR 公式キーワード含有、既記事化済でない
"""
import sys, os, json, urllib.request, base64
from datetime import datetime, timedelta
from dotenv import load_dotenv

sys.path.insert(0, '/home/aiuser/kpop-ai-system')
load_dotenv()

from lib.korean_translator import translate_ko_to_ja

SIGNALS = '/home/aiuser/kpop-ai-system/data/trend_signals.jsonl'
PROCESSED = '/home/aiuser/kpop-ai-system/data/auto_article_processed.jsonl'
WP_USER = 'kpop-bot'
WP_PASS = os.getenv('WP_APP_PASS', 'vl1H 1brV m4Pq Z1sm F8lZ 3nzh')
AUTH = base64.b64encode(f"{WP_USER}:{WP_PASS}".encode()).decode()

EVENT_KW_KO = ['콘서트', '팬미팅', '투어', '공연', '라이브', '쇼케이스', '축제', '페스티벌']
OFFICIAL_KW = ['공식', '발표', '확정', '예정']


def load_signals(hours_back=24):
    if not os.path.exists(SIGNALS):
        return []
    cutoff = datetime.now() - timedelta(hours=hours_back)
    result = []
    with open(SIGNALS, encoding='utf-8') as f:
        for line in f:
            try:
                sig = json.loads(line)
                ts_str = sig.get('timestamp', '')[:19]
                ts = datetime.fromisoformat(ts_str)
                if ts >= cutoff and sig.get('source') in ('korean_media', 'japanese_media'):
                    result.append(sig)
            except Exception:
                pass
    return result


def is_event_signal(sig):
    return any(kw in sig.get('title', '') for kw in EVENT_KW_KO)


def is_processed(url):
    if not os.path.exists(PROCESSED):
        return False
    with open(PROCESSED, encoding='utf-8') as f:
        for line in f:
            try:
                if json.loads(line).get('source_url') == url:
                    return True
            except Exception:
                pass
    return False


def mark_processed(record):
    os.makedirs(os.path.dirname(PROCESSED), exist_ok=True)
    with open(PROCESSED, 'a', encoding='utf-8') as f:
        f.write(json.dumps(record, ensure_ascii=False) + '\n')


def generate_article_content(sigs, translated_body):
    source_links = ''.join(
        f'<li><a href="{s["url"]}" target="_blank" rel="noopener">{s.get("source_id", "?").upper()}</a>: '
        f'{s["title"][:60]}</li>'
        for s in sigs[:5]
    )
    return f"""<p>{translated_body}</p>

<h2>情報ソース</h2>
<p>本記事は以下の韓国メディア報道を元に編集部が翻訳・編集しました:</p>
<ul>{source_links}</ul>

<p><em>※ 原情報は韓国メディア各社の報道に基づきます。最新情報は各公式発表をご確認ください。</em></p>"""


def post_to_wp(title_ja, content_html, category_id=None):
    data = {'title': title_ja, 'content': content_html, 'status': 'publish'}
    if category_id:
        data['categories'] = [category_id]
    body = json.dumps(data).encode()
    req = urllib.request.Request(
        "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts",
        data=body,
        headers={'Authorization': f'Basic {AUTH}', 'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"WP post error: {e}")
        return None


def fetch_category_id(slug='event'):
    try:
        req = urllib.request.Request(
            f"https://www.kpopjournal.tokyo/wp-json/wp/v2/categories?slug={slug}&_fields=id",
            headers={'Authorization': f'Basic {AUTH}'},
        )
        return json.loads(urllib.request.urlopen(req, timeout=20).read())[0]['id']
    except Exception:
        return None


def main(dry_run=False, max_articles=3):
    signals = load_signals(hours_back=24)
    event_sigs = [s for s in signals if is_event_signal(s)]
    print(f"過去24h signals: {len(signals)}, イベント関連: {len(event_sigs)}")

    from lib.collectors.korean_base import is_kpop_related
    groups = {}
    for sig in event_sigs:
        artists = is_kpop_related(sig['title'])
        if not artists:
            continue
        event_type = next((kw for kw in EVENT_KW_KO if kw in sig['title']), 'other')
        key = f"{artists[0]}-{event_type}"
        groups.setdefault(key, []).append(sig)

    qualified = []
    for key, sigs in groups.items():
        sources = set(s.get('source_id', '') for s in sigs)
        has_multi = len(sources) >= 2
        has_official = any(any(kw in s['title'] for kw in OFFICIAL_KW) for s in sigs)
        if (has_multi or has_official) and not any(is_processed(s['url']) for s in sigs):
            qualified.append((key, sigs))

    print(f"記事化候補: {len(qualified)}")
    cat_id = fetch_category_id('event')
    created = 0

    for key, sigs in qualified[:max_articles]:
        best = max(sigs, key=lambda s: len(s['title']))
        print(f"\n=== {key}: {best['title'][:60]} ===")
        if dry_run:
            continue

        title_r = translate_ko_to_ja(best['title'], 'K-POPイベント見出し')
        if not title_r['success']:
            continue
        title_ja = title_r['translated'].strip().strip('「」""')[:70]

        combined = "\n".join([s['title'] for s in sigs[:3]])
        body_r = translate_ko_to_ja(
            f"以下のK-POPイベント報道から200-300字の日本語記事本文を事実ベースで作成。推測禁止:\n\n{combined}",
            'K-POPイベント記事',
        )
        if not body_r['success']:
            continue

        result = post_to_wp(title_ja, generate_article_content(sigs, body_r['translated']), cat_id)
        if result and result.get('id'):
            print(f"  WP公開 ID={result['id']}")
            created += 1
            for s in sigs:
                mark_processed({'ts': datetime.now().isoformat(), 'source_url': s['url'],
                                'wp_post_id': result['id'], 'kind': 'event'})

    print(f"\n完了: {created}件記事化")
    return created


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--max', type=int, default=3)
    args = ap.parse_args()
    main(dry_run=args.dry_run, max_articles=args.max)
