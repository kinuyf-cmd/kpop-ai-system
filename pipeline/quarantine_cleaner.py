#!/usr/bin/env python3
"""削除判定AI (完全自律版)

quarantine記事を救済(GPT-4o) or 完全削除。オーナー介入ゼロ。
日次02:00実行。
"""
import os, sys, json, urllib.request, base64, re
from datetime import datetime
from lib.agent_learning_loop import inject_lessons_to_prompt

sys.path.insert(0, '/home/aiuser/kpop-ai-system')
for line in open('/home/aiuser/kpop-ai-system/.env'):
    line = line.strip()
    if line and not line.startswith('#') and '=' in line:
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip())

AUTH = base64.b64encode(b"kpop-bot:vl1H 1brV m4Pq Z1sm F8lZ 3nzh").decode()
QUARANTINE = '/home/aiuser/kpop-ai-system/logs/quarantine.jsonl'
DELETED_LOG = '/home/aiuser/kpop-ai-system/logs/permanently_deleted.jsonl'
RESCUED_LOG = '/home/aiuser/kpop-ai-system/logs/rescued.jsonl'


def _load_quarantine():
    if not os.path.exists(QUARANTINE):
        return []
    return [json.loads(l) for l in open(QUARANTINE, encoding='utf-8') if l.strip()]


def _save_quarantine(entries):
    with open(QUARANTINE, 'w', encoding='utf-8') as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + '\n')


def _fetch_source(source_url):
    if not source_url:
        return ''
    try:
        req = urllib.request.Request(source_url, headers={'User-Agent': 'Mozilla/5.0'})
        html = urllib.request.urlopen(req, timeout=20).read().decode('utf-8', errors='replace')
        og = ''
        m = re.search(r'<meta\s+property="og:description"\s+content="([^"]+)"', html)
        if m:
            og = m.group(1)
        paras = re.findall(r'<p[^>]*>([^<]{30,500})</p>', html)
        body = ' '.join(paras[:20])
        return re.sub(r'\s+', ' ', (og + ' ' + body).strip())[:3000]
    except Exception:
        return ''


def _rescue_gpt4o(title, original_body, source_text, source_url):
    key = os.getenv('OPENAI_API_KEY')
    if not key or len(source_text) < 100:
        return None
    clean_title = re.sub(r'【.*?】', '', re.sub(r'<[^>]+>', '', title)).strip()
    system_prompt = (
        'K-POP専門メディア編集者。品質不足で一度失敗した記事を、追加情報で救済。'
        '日本語600-900字、事実のみ、推測禁止、HTML <p>タグで3-4段落。'
    )
    system_prompt = inject_lessons_to_prompt('unknown', system_prompt)
    body_req = json.dumps({
        'model': 'gpt-4o',
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': (
                f'タイトル: {clean_title}\n元本文(失敗): {re.sub(r"<[^>]+>", "", original_body)[:500]}\n'
                f'ソースURL: {source_url}\nソース本文: {source_text[:2500]}\n\n'
                '上記から完全な日本語記事(600-900字、<p>タグ付き)を作成:'
            )},
        ],
        'temperature': 0.4,
        'max_tokens': 2500,
    }).encode()
    req = urllib.request.Request('https://api.openai.com/v1/chat/completions', data=body_req,
                                 headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'})
    try:
        r = urllib.request.urlopen(req, timeout=120)
        res = json.loads(r.read())
        text = res['choices'][0]['message']['content'].strip()
        if '<p>' not in text:
            text = '\n'.join(f'<p>{p.strip()}</p>' for p in text.split('\n\n') if p.strip())
        usage = res.get('usage', {})
        cost = usage.get('prompt_tokens', 0) * 2.5 / 1e6 + usage.get('completion_tokens', 0) * 10 / 1e6
        return {'body': text, 'cost': cost}
    except Exception as e:
        print(f"  GPT-4o error: {e}")
        return None


def _quality_ok(body_html):
    text = re.sub(r'<[^>]+>', '', body_html).strip()
    core = re.sub(r'※[^<\n]*|情報ソース[\s\S]*', '', text).strip()
    if len(core) < 200:
        return False, f'短({len(core)}字)'
    ja = sum(1 for c in core if '\u3040' <= c <= '\u30ff' or '\u4e00' <= c <= '\u9fff')
    if ja / len(core) < 0.3:
        return False, f'日本語不足({ja * 100 // len(core)}%)'
    return True, 'OK'


def _wp_fetch(pid):
    try:
        req = urllib.request.Request(
            f"https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/{pid}?context=edit&_fields=id,title,content,status,link",
            headers={'Authorization': f'Basic {AUTH}'})
        return json.loads(urllib.request.urlopen(req, timeout=20).read())
    except Exception:
        return None


def _wp_update(pid, data):
    req = urllib.request.Request(
        f"https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/{pid}",
        data=json.dumps(data).encode(),
        headers={'Authorization': f'Basic {AUTH}', 'Content-Type': 'application/json'},
        method='POST')
    try:
        return json.loads(urllib.request.urlopen(req, timeout=60).read())
    except Exception:
        return None


def _wp_delete(pid):
    req = urllib.request.Request(
        f"https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/{pid}?force=true",
        headers={'Authorization': f'Basic {AUTH}'}, method='DELETE')
    try:
        urllib.request.urlopen(req, timeout=30)
        return True
    except Exception:
        return False


def _log_append(path, entry):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')


def process(entry, dry_run=False):
    pid = entry['post_id']
    source_url = entry.get('source_url', '')

    post = _wp_fetch(pid)
    if not post:
        return 'delete', 'WP取得不可'
    if post.get('status') == 'publish':
        return 'skip', '既に公開済'

    # trash→draft復元
    if post.get('status') == 'trash':
        r = _wp_update(pid, {'status': 'draft'})
        if not r or r.get('status') != 'draft':
            return 'delete', 'trash復元失敗'

    source_text = _fetch_source(source_url) if source_url else ''

    if not source_url or len(source_text) < 100:
        if dry_run:
            return 'would_delete', f'source不足({len(source_text)}字)'
        _wp_update(pid, {'status': 'trash'})
        _wp_delete(pid)
        return 'deleted', f'source不足({len(source_text)}字)'

    if dry_run:
        return 'would_rescue', f'source {len(source_text)}字'

    rescue = _rescue_gpt4o(
        post['title']['rendered'],
        post.get('content', {}).get('rendered', ''),
        source_text, source_url,
    )

    if not rescue:
        _wp_update(pid, {'status': 'trash'})
        _wp_delete(pid)
        return 'deleted', 'GPT-4o失敗'

    ok, reason = _quality_ok(rescue['body'])
    if not ok:
        _wp_update(pid, {'status': 'trash'})
        _wp_delete(pid)
        return 'deleted', f'品質NG: {reason}'

    # 救済成功 → 再公開
    note = '<p><em>※ 本記事はAI編集部が元記事を元に再編集しました。</em></p>'
    body = rescue['body'] + '\n\n' + note
    if source_url:
        body += f'\n<h2>情報ソース</h2>\n<p><a href="{source_url}" target="_blank" rel="noopener">{source_url[:60]}</a></p>'

    # 捏造ブロックリスト確認
    try:
        import json as _j2
        _bl = set(_j2.load(open('/home/aiuser/kpop-ai-system/data/factcheck_blocked.json')).get('blocked_ids', []))
        if pid in _bl:
            print(f"  [{pid}] SKIP: 捏造ブロック済み")
            return 'blocked', '捏造ブロックリストに該当'
    except Exception:
        pass
    r = _wp_update(pid, {'content': body, 'status': 'publish'})
    if r and r.get('status') == 'publish':
        try:
            from lib.gsc_indexing import notify_url_updated
            notify_url_updated(post.get('link', ''))
        except Exception:
            pass
        try:
            from lib.x_poster import post_tweet
            post_tweet(re.sub(r'<[^>]+>', '', post['title']['rendered']), post.get('link', ''))
        except Exception:
            pass
        return 'rescued', f'GPT-4o成功 (${rescue["cost"]:.4f})'

    _wp_update(pid, {'status': 'trash'})
    _wp_delete(pid)
    return 'deleted', 'WP更新失敗'


def main(dry_run=False):
    entries = _load_quarantine()
    pending = [e for e in entries if not e.get('final_verdict')]
    print(f"=== 削除判定AI === quarantine={len(entries)} pending={len(pending)} dry={dry_run}")

    counts = {}
    for entry in pending:
        pid = entry['post_id']
        print(f"\n[{pid}] src={entry.get('source_url', 'なし')[:50]}")
        verdict, reason = process(entry, dry_run)
        counts[verdict] = counts.get(verdict, 0) + 1
        print(f"  → {verdict}: {reason}")

        if not dry_run:
            entry['final_verdict'] = verdict
            entry['final_reason'] = reason
            entry['processed_at'] = datetime.now().isoformat()
            if verdict == 'deleted':
                _log_append(DELETED_LOG, entry)
            elif verdict == 'rescued':
                _log_append(RESCUED_LOG, entry)

    if not dry_run:
        _save_quarantine(entries)

    print(f"\n=== 結果 ===")
    for k, v in counts.items():
        if v: print(f"  {k}: {v}")


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()
    main(dry_run=args.dry_run)
