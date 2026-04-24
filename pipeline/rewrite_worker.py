#!/usr/bin/env python3
"""リライト担当AI

draft化された記事を GPT-4o-mini で加筆 → 品質ゲート再チェック → 再公開。
cron: 毎時15分、最大5件/回。リトライ3回失敗 → quarantine (trash)。
"""
import os, sys, json, urllib.request, base64, re
from datetime import datetime

sys.path.insert(0, '/home/aiuser/kpop-ai-system')
for line in open('/home/aiuser/kpop-ai-system/.env'):
    line = line.strip()
    if line and not line.startswith('#') and '=' in line:
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip())

AUTH = base64.b64encode(b"kpop-bot:vl1H 1brV m4Pq Z1sm F8lZ 3nzh").decode()
QUEUE = '/home/aiuser/kpop-ai-system/data/rewrite_queue.jsonl'
QUARANTINE = '/home/aiuser/kpop-ai-system/logs/quarantine.jsonl'
PROCESSED_LOG = '/home/aiuser/kpop-ai-system/data/auto_article_processed.jsonl'
MAX_PER_RUN = 5
MAX_RETRIES = 3


def load_queue():
    if not os.path.exists(QUEUE):
        return []
    entries = []
    with open(QUEUE, encoding='utf-8') as f:
        for line in f:
            try:
                entries.append(json.loads(line))
            except:
                pass
    return entries


def save_queue(entries):
    with open(QUEUE, 'w', encoding='utf-8') as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + '\n')


def wp_get(post_id):
    try:
        req = urllib.request.Request(
            f"https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/{post_id}"
            f"?_fields=id,title,content,status,slug,categories,featured_media,link",
            headers={'Authorization': f'Basic {AUTH}'}
        )
        return json.loads(urllib.request.urlopen(req, timeout=20).read())
    except Exception as e:
        print(f"  fetch({post_id}) error: {e}")
        return None


def wp_update(post_id, data):
    req = urllib.request.Request(
        f"https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/{post_id}",
        data=json.dumps(data).encode(),
        headers={'Authorization': f'Basic {AUTH}', 'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        return json.loads(urllib.request.urlopen(req, timeout=60).read())
    except Exception as e:
        print(f"  wp_update({post_id}) error: {e}")
        return None


def find_source_url(post_id):
    """auto_article_processed.jsonl から元ソースURL特定"""
    if not os.path.exists(PROCESSED_LOG):
        return None
    with open(PROCESSED_LOG, encoding='utf-8') as f:
        for line in f:
            try:
                d = json.loads(line)
                if d.get('wp_post_id') == post_id:
                    return d.get('source_url')
            except:
                pass
    return None


def fetch_source_summary(source_url):
    """ソースURLからog:descriptionを取得"""
    if not source_url:
        return ''
    try:
        req = urllib.request.Request(source_url, headers={'User-Agent': 'Mozilla/5.0'})
        html = urllib.request.urlopen(req, timeout=15).read().decode('utf-8', errors='replace')
        m = re.search(r'<meta\s+property="og:description"\s+content="([^"]+)"', html)
        return m.group(1)[:300] if m else ''
    except Exception:
        return ''


def rewrite_body(title, original_body, source_url=None):
    """GPT-4o-mini で本文を再生成"""
    key = os.getenv('OPENAI_API_KEY')
    if not key:
        return None, 'OPENAI_API_KEY未設定'

    clean_title = re.sub(r'【.*?】', '', title).strip()
    source_hint = fetch_source_summary(source_url)

    system = (
        "K-POP専門Webメディアの編集者。以下のK-POP記事を、ファン向けに事実ベースで日本語加筆。\n"
        "要件:\n"
        "1. 日本語のみ、500-800文字\n"
        "2. 原文にない情報・推測は絶対に書かない\n"
        "3. タイトル内のアーティスト名・具体名は保持\n"
        "4. 読みやすい段落 (2-4段落、HTML <p>タグで段落分け)"
    )
    user_msg = f"タイトル: {clean_title}\n\n原本文:\n{re.sub(r'<[^>]+>', '', original_body)[:800]}"
    if source_hint:
        user_msg += f"\n\n参考情報:\n{source_hint}"
    user_msg += "\n\n新しい日本語本文 (500-800字、<p>タグで段落分け):"

    body_req = json.dumps({
        'model': 'gpt-4o-mini',
        'messages': [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': user_msg},
        ],
        'temperature': 0.5,
        'max_tokens': 2000,
    }).encode()

    req = urllib.request.Request('https://api.openai.com/v1/chat/completions', data=body_req, headers={
        'Authorization': f'Bearer {key}',
        'Content-Type': 'application/json',
    })

    try:
        r = urllib.request.urlopen(req, timeout=90)
        res = json.loads(r.read())
        text = res['choices'][0]['message']['content'].strip()
        if '<p>' not in text:
            paras = [p.strip() for p in text.split('\n\n') if p.strip()]
            text = '\n'.join(f'<p>{p}</p>' for p in paras)
        return text, None
    except Exception as e:
        return None, str(e)


def check_quality(body_html):
    """品質ゲート (unified_publisher と同一基準)"""
    text = re.sub(r'<[^>]+>', '', body_html).strip()
    core = re.sub(r'※[^<\n]*|情報ソース[\s\S]*', '', text).strip()
    if len(core) < 200:
        return False, f'本文{len(core)}字(200字未満)'
    ja = sum(1 for c in core if '\u3040' <= c <= '\u30ff' or '\u4e00' <= c <= '\u9fff')
    ratio = ja / len(core)
    if ratio < 0.3:
        return False, f'日本語{ratio*100:.0f}%(30%未満)'
    return True, f'{len(core)}字, 日本語{ratio*100:.0f}%'


def quarantine_post(entry, reason):
    """修復不能 → trash + ログ"""
    os.makedirs(os.path.dirname(QUARANTINE), exist_ok=True)
    entry['quarantined_at'] = datetime.now().isoformat()
    entry['quarantine_reason'] = reason
    with open(QUARANTINE, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    # trash化
    req = urllib.request.Request(
        f"https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/{entry['post_id']}",
        headers={'Authorization': f'Basic {AUTH}'},
        method='DELETE',
    )
    try:
        urllib.request.urlopen(req, timeout=30)
    except Exception:
        pass
    print(f"  [{entry['post_id']}] QUARANTINE: {reason}")


def process_entry(entry):
    pid = entry['post_id']
    retry = entry.get('retry_count', 0)

    if retry >= MAX_RETRIES:
        quarantine_post(entry, f'retry上限{MAX_RETRIES}回')
        entry['status'] = 'quarantined'
        return entry

    post = wp_get(pid)
    if not post:
        entry['retry_count'] = retry + 1
        entry['status'] = 'fetch_failed'
        return entry

    if post.get('status') == 'publish':
        entry['status'] = 'already_published'
        entry['resolved_at'] = datetime.now().isoformat()
        print(f"  [{pid}] 既に公開済、skip")
        return entry

    title = re.sub(r'<[^>]+>', '', post.get('title', {}).get('rendered', ''))
    body = post.get('content', {}).get('rendered', '')
    source_url = find_source_url(pid)

    print(f"  [{pid}] リライト実行 (試行{retry+1}) title={title[:30]}...")
    new_body, err = rewrite_body(title, body, source_url)

    if not new_body:
        entry['retry_count'] = retry + 1
        entry['status'] = 'gpt_failed'
        entry['last_error'] = err
        print(f"  [{pid}] GPT失敗: {err}")
        return entry

    ok, quality_msg = check_quality(new_body)
    if not ok:
        entry['retry_count'] = retry + 1
        entry['status'] = 'quality_failed'
        entry['last_error'] = quality_msg
        print(f"  [{pid}] 品質不合格: {quality_msg}")
        return entry

    # 信頼度注意書き + ソース情報
    note = '<p><em>※ 本記事は韓国メディアの公式報道を元にAI編集部が再編集しました。</em></p>'
    final_body = new_body + '\n\n' + note
    if source_url:
        final_body += (
            f'\n\n<h2>情報ソース</h2>\n'
            f'<p>元記事: <a href="{source_url}" target="_blank" rel="noopener">'
            f'{source_url[:60]}</a></p>'
        )

    r = wp_update(pid, {'content': final_body, 'status': 'publish'})
    if r and r.get('status') == 'publish':
        print(f"  [{pid}] ✅ リライト成功+再公開 ({quality_msg})")
        entry['status'] = 'rewritten'
        entry['resolved_at'] = datetime.now().isoformat()
        entry['quality'] = quality_msg

        # GSC再通知
        post_url = post.get('link', '')
        if post_url:
            try:
                from lib.gsc_indexing import notify_url_updated
                notify_url_updated(post_url)
            except Exception:
                pass
    else:
        entry['retry_count'] = retry + 1
        entry['status'] = 'wp_update_failed'

    return entry


def main(max_items=MAX_PER_RUN):
    entries = load_queue()
    retryable = {'pending', 'gpt_failed', 'quality_failed', 'wp_update_failed', 'fetch_failed'}
    pending = [e for e in entries if e.get('status') in retryable
               and e.get('retry_count', 0) < MAX_RETRIES]

    print(f"=== リライト担当 開始 ===")
    print(f"全キュー: {len(entries)}件 / 処理対象: {len(pending)}件 / "
          f"本回処理: {min(len(pending), max_items)}件")

    pending.sort(key=lambda e: e.get('ts', ''))

    for i, entry in enumerate(pending[:max_items]):
        print(f"\n--- 処理 {i+1}/{min(len(pending), max_items)} ---")
        updated = process_entry(entry)
        for j, e in enumerate(entries):
            if e.get('post_id') == updated['post_id'] and e.get('ts') == updated.get('ts'):
                entries[j] = updated
                break

    save_queue(entries)

    summary = {}
    for e in entries:
        st = e.get('status', 'unknown')
        summary[st] = summary.get(st, 0) + 1
    print(f"\n=== キュー状況 ===")
    for st, cnt in sorted(summary.items()):
        print(f"  {st}: {cnt}")


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--max', type=int, default=MAX_PER_RUN)
    args = ap.parse_args()
    main(max_items=args.max)
