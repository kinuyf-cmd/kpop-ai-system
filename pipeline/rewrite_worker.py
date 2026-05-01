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


from lib.agent_learning_loop import inject_lessons_to_prompt

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


# ============================================================
# 速報Stage 1→2 加筆ロジック (2時間後、800字目標)
# ============================================================

def find_breaking_stage1_to_upgrade():
    """2時間以上経過したStage 1速報を取得"""
    from datetime import timedelta, timezone
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime('%Y-%m-%dT%H:%M:%S')
    url = (f"https://www.kpopjournal.tokyo/wp-json/wp/v2/posts"
           f"?meta_key=_breaking_stage&meta_value=1&before={cutoff}"
           f"&per_page=10&_fields=id,title,content,date&context=edit")
    try:
        req = urllib.request.Request(url, headers={'Authorization': f'Basic {AUTH}'})
        return json.loads(urllib.request.urlopen(req, timeout=20).read())
    except Exception as e:
        print(f"  Stage1検索エラー: {e}")
        return []


def upgrade_breaking_to_stage2(post):
    """Stage 1→Stage 2: GPT-4o-miniで800字以上に加筆"""
    pid = post['id']
    title = post['title']['rendered']
    content_html = post['content']['rendered']
    plain = re.sub(r'<[^>]+>', '', content_html)

    key = os.getenv('OPENAI_API_KEY')
    prompt = f"""以下のK-POP速報記事を、800字以上の充実した記事に加筆してください。

【加筆ルール】
- 既存の事実は完全に保持し、削除・改変しない
- 背景情報、関連事実、ファンへの含意を追加
- K-POPメディア読者向けの自然な日本語
- 文末バリエーション豊富 (~した、~と語った、~と発表した等を混ぜる)
- HTMLタグ (h2/p等) は適切に使用
- 注意書きや「以上です」等の蛇足は不要

【元記事】
タイトル: {title}
本文: {plain[:2000]}

【加筆版本文】 (HTML、800字以上、以下に出力):"""

    body = json.dumps({
        'model': 'gpt-4o-mini',
        'messages': [{'role': 'user', 'content': inject_lessons_to_prompt('feature_article_writer', prompt)}],
        'temperature': 0.7,
        'max_tokens': 1800,
    }).encode()

    try:
        req = urllib.request.Request('https://api.openai.com/v1/chat/completions',
            data=body, headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'})
        r = json.loads(urllib.request.urlopen(req, timeout=90).read())
        new_content = r['choices'][0]['message']['content'].strip()

        new_plain = re.sub(r'<[^>]+>', '', new_content)
        # 既に十分長い記事はスキップ (速報の加筆対象は短い記事のみ)
        if len(plain) >= 500:
            print(f"  ⚠️ post_id={pid} 既に{len(plain)}字あるためスキップ")
            return False
        if len(new_plain) < 400:
            print(f"  ⚠️ post_id={pid} 加筆結果が短い ({len(new_plain)}字)、スキップ")
            return False

        upd_url = f"https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/{pid}"
        upd_body = json.dumps({
            'content': new_content,
            'meta': {'_breaking_stage': '2'}
        }).encode()
        req2 = urllib.request.Request(upd_url, data=upd_body, method='POST',
            headers={'Authorization': f'Basic {AUTH}', 'Content-Type': 'application/json'})
        urllib.request.urlopen(req2, timeout=20).read()
        print(f"  ✅ Stage 1→2 完了 post_id={pid} ({len(plain)}→{len(new_plain)}字)")
        return True
    except Exception as e:
        print(f"  🔴 post_id={pid} 加筆失敗: {str(e)[:120]}")
        return False


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
    if len(core) < 800:
        return False, f'本文{len(core)}字(800字未満)'
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
    # 速報Stage 1→2 加筆 (2時間以上経過)
    print("\n=== 速報Stage 1→2 加筆処理 ===")
    breaking_stage1 = find_breaking_stage1_to_upgrade()
    print(f"対象: {len(breaking_stage1)}件 (2時間以上経過したStage 1速報)")
    upgraded = 0
    for post in breaking_stage1[:5]:
        if upgrade_breaking_to_stage2(post):
            upgraded += 1
    if breaking_stage1:
        print(f"加筆完了: {upgraded}/{min(len(breaking_stage1), 5)}件")

    # 通常リライト処理
    entries = load_queue()
    retryable = {'pending', 'gpt_failed', 'quality_failed', 'wp_update_failed', 'fetch_failed'}
    pending = [e for e in entries if e.get('status') in retryable
               and e.get('retry_count', 0) < MAX_RETRIES]

    print(f"\n=== リライト担当 開始 ===")
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
