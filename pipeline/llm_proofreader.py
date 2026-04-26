#!/usr/bin/env python3
"""項目17 LLM校閲 — GPT-4o-miniで全記事を校閲 (4時間毎 cron)
   critical/high検出時は llm_audit_alerts.log + audit_state.jsonl にキュー追加"""
import sys, os, json, re, argparse
sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
load_dotenv('/home/aiuser/kpop-ai-system/.env')

import urllib.request, base64

WP_USER = os.getenv('WP_USER', '')
WP_PASS = os.getenv('WP_PASS', '')
AUTH = base64.b64encode(f"{WP_USER}:{WP_PASS}".encode()).decode() if WP_USER else ''
OPENAI_KEY = os.getenv('OPENAI_API_KEY', '')
JST = timezone(timedelta(hours=9))

LOGS_DIR = '/home/aiuser/kpop-ai-system/logs/llm_audit'
ALERT_LOG = '/home/aiuser/kpop-ai-system/logs/llm_audit_alerts.log'
AUDIT_STATE = '/home/aiuser/kpop-ai-system/data/audit_state.jsonl'


def fetch_recent_posts(hours=4, per_page=30):
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime('%Y-%m-%dT%H:%M:%S')
    posts = []
    for endpoint in ['posts', 'popup']:
        try:
            url = (f"https://www.kpopjournal.tokyo/wp-json/wp/v2/{endpoint}"
                   f"?after={cutoff}&per_page={per_page}&_embed=true")
            req = urllib.request.Request(url, headers={'Authorization': f'Basic {AUTH}'})
            data = json.loads(urllib.request.urlopen(req, timeout=20).read())
            for p in data:
                p['_post_type'] = endpoint
            posts.extend(data)
        except Exception as e:
            print(f"  fetch err {endpoint}: {e}")
    return posts


def _already_proofread(post_id):
    """直近24h以内に同一IDを校閲済みならスキップ"""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    if not os.path.exists(LOGS_DIR):
        return False
    for fname in os.listdir(LOGS_DIR):
        if not fname.endswith('.json'):
            continue
        try:
            data = json.load(open(os.path.join(LOGS_DIR, fname)))
            for r in data.get('results', []):
                if r.get('id') == post_id:
                    return True
        except:
            pass
    return False


def proofread_post(post):
    """GPT-4o-miniで1件校閲"""
    title = post['title']['rendered'] if isinstance(post.get('title'), dict) else post.get('title', '')
    content = post['content']['rendered'] if isinstance(post.get('content'), dict) else post.get('content', '')
    plain = re.sub(r'<[^>]+>', ' ', content)
    plain = re.sub(r'\s+', ' ', plain).strip()[:2500]

    prompt = f'''以下の記事を厳格に校閲。問題なしならcritical=[],high=[],medium=[]で返す。
【タイトル】{title}
【本文抜粋】{plain}
JSON出力のみ: {{"score":0-100,"critical":["致命的問題"],"high":["重要問題"],"medium":["軽微な問題"]}}
判定基準: critical=事実誤認/重大誤字, high=不自然な日本語/タイトル不整合, medium=表現の改善余地'''

    body = json.dumps({
        'model': 'gpt-4o-mini',
        'messages': [{'role': 'user', 'content': prompt}],
        'response_format': {'type': 'json_object'},
        'max_tokens': 600,
    }).encode()

    req = urllib.request.Request('https://api.openai.com/v1/chat/completions',
        data=body, headers={
            'Authorization': f'Bearer {OPENAI_KEY}',
            'Content-Type': 'application/json',
        })
    r = json.loads(urllib.request.urlopen(req, timeout=60).read())
    return json.loads(r['choices'][0]['message']['content'])


def queue_to_audit_state(post_id, post_type, llm_issues):
    """critical/high検出時にaudit_state.jsonlにキュー追加"""
    os.makedirs(os.path.dirname(AUDIT_STATE), exist_ok=True)
    issues = []
    for c in llm_issues.get('critical', []):
        issues.append({'type': 'llm_critical', 'severity': 'high', 'detail': c})
    for h in llm_issues.get('high', []):
        issues.append({'type': 'llm_high', 'severity': 'high', 'detail': h})

    with open(AUDIT_STATE, 'a', encoding='utf-8') as f:
        f.write(json.dumps({
            'post_id': post_id,
            'post_type': 'post' if post_type == 'posts' else post_type,
            'issues': issues,
            'audited_at': datetime.now(timezone.utc).isoformat(),
            'source': 'llm_proofreader',
            'high_count': len(issues),
            'medium_count': 0, 'low_count': 0,
        }, ensure_ascii=False) + '\n')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--hours', type=int, default=4)
    parser.add_argument('--limit', type=int, default=30)
    args = parser.parse_args()

    now = datetime.now(JST)
    print(f"=== llm_proofreader {now.strftime('%Y-%m-%d %H:%M')} ===")

    if not OPENAI_KEY:
        print("  OPENAI_API_KEY未設定、終了")
        return

    posts = fetch_recent_posts(hours=args.hours, per_page=args.limit)
    # Skip already proofread
    targets = [p for p in posts if not _already_proofread(p['id'])]
    print(f"  対象: {len(targets)}件 (取得{len(posts)}件, 既読{len(posts)-len(targets)}件)")

    if args.dry_run:
        for p in targets:
            title = p['title']['rendered'] if isinstance(p.get('title'), dict) else ''
            print(f"  [dry-run] id={p['id']} {title[:50]}")
        print(f"  dry-run完了 ({len(targets)}件)")
        return

    results = []
    crit_total = high_total = 0
    for i, p in enumerate(targets):
        pid = p['id']
        pt = p.get('_post_type', 'posts')
        title = p['title']['rendered'] if isinstance(p.get('title'), dict) else ''
        try:
            r = proofread_post(p)
            r['id'] = pid
            r['type'] = pt
            r['title'] = title[:60]
            results.append(r)

            nc = len(r.get('critical', []))
            nh = len(r.get('high', []))
            crit_total += nc
            high_total += nh
            print(f"  [{i+1}/{len(targets)}] id={pid} score={r.get('score',0)} C={nc} H={nh}")

            # Alert + queue
            if nc > 0 or nh > 0:
                os.makedirs(os.path.dirname(ALERT_LOG), exist_ok=True)
                with open(ALERT_LOG, 'a', encoding='utf-8') as f:
                    f.write(f"{now.isoformat()} id={pid} C={nc} H={nh} "
                            f"critical={r.get('critical',[])} high={r.get('high',[])}\n")
                queue_to_audit_state(pid, pt, r)

        except Exception as e:
            print(f"  [{i+1}/{len(targets)}] id={pid} ERR: {e}")
            results.append({'id': pid, 'type': pt, 'error': str(e)})

    # Save results
    os.makedirs(LOGS_DIR, exist_ok=True)
    out_path = os.path.join(LOGS_DIR, f"{now.strftime('%Y%m%d_%H')}.json")
    out = {
        'timestamp': now.isoformat(),
        'total': len(results),
        'critical': crit_total,
        'high': high_total,
        'results': results,
    }
    json.dump(out, open(out_path, 'w'), ensure_ascii=False, indent=2)

    print(f"\n校閲完了: {len(results)}件 / critical={crit_total} high={high_total}")
    print(f"保存: {out_path}")


if __name__ == '__main__':
    main()
