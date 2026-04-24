#!/usr/bin/env python3
"""ダッシュボード用JSON生成 (15分毎)

public/data/dashboard.json にKPI・投稿数・collector状況・監査結果をまとめて出力
"""
import os, json, urllib.request, base64
from datetime import datetime, timedelta, timezone

AUTH = base64.b64encode(b"kpop-bot:vl1H 1brV m4Pq Z1sm F8lZ 3nzh").decode()
OUT = '/home/aiuser/kpopjournal-frontend/public/data/dashboard.json'
JST = timezone(timedelta(hours=9))


def _wp_posts(hours=24):
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime('%Y-%m-%dT%H:%M:%S')
    url = (f"https://www.kpopjournal.tokyo/wp-json/wp/v2/posts"
           f"?after={since}&per_page=100&_fields=id,title,date")
    try:
        req = urllib.request.Request(url, headers={'Authorization': f'Basic {AUTH}'})
        return json.loads(urllib.request.urlopen(req, timeout=20).read())
    except Exception:
        return []


def _jsonl_tail(path, n=50):
    if not os.path.exists(path):
        return []
    result = []
    for l in open(path, encoding='utf-8').readlines()[-n:]:
        try:
            result.append(json.loads(l))
        except Exception:
            pass
    return result


def _signals_24h():
    p = '/home/aiuser/kpop-ai-system/data/trend_signals.jsonl'
    if not os.path.exists(p):
        return {'total': 0, 'by_source': {}}
    cutoff = datetime.now() - timedelta(hours=24)
    total = 0
    by_source = {}
    for line in open(p, encoding='utf-8'):
        try:
            d = json.loads(line)
            ts = datetime.fromisoformat(d.get('timestamp', '')[:19])
            if ts >= cutoff:
                total += 1
                src = d.get('source_id', '?')
                by_source[src] = by_source.get(src, 0) + 1
        except Exception:
            pass
    return {'total': total, 'by_source': by_source}


def main():
    now = datetime.now(JST)
    posts = _wp_posts(24)

    # 速報 vs その他
    def is_breaking(p):
        t = p.get('title', {}).get('rendered', '') if isinstance(p.get('title'), dict) else ''
        return '【速報】' in t or '【韓国メディア速報】' in t

    breaking = sum(1 for p in posts if is_breaking(p))
    other = len(posts) - breaking

    # 本日 (JST 0時以降)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_posts = [p for p in posts if p['date'][:10] >= today_start.strftime('%Y-%m-%d')]
    today_breaking = sum(1 for p in today_posts if is_breaking(p))

    # editor_state
    editor = {}
    es_path = '/home/aiuser/kpop-ai-system/data/editor_state.json'
    if os.path.exists(es_path):
        try:
            editor = json.load(open(es_path, encoding='utf-8'))
        except Exception:
            pass

    # audit
    audit = _jsonl_tail('/home/aiuser/kpop-ai-system/logs/audit_issues.jsonl', 100)
    audit_by_type = {}
    for a in audit:
        audit_by_type[a.get('issue', '?')] = audit_by_type.get(a.get('issue', '?'), 0) + 1

    # X
    x_logs = _jsonl_tail('/home/aiuser/kpop-ai-system/logs/x_posts.jsonl', 50)
    x_today = sum(1 for x in x_logs
                  if x.get('ts', '')[:10] == now.strftime('%Y-%m-%d') and x.get('status') == 'ok')

    data = {
        'generated_at': now.isoformat(),
        'kpi': {
            'today': {
                'total': len(today_posts),
                'breaking': today_breaking,
                'other': len(today_posts) - today_breaking,
                'target': 20,
            },
            'last_24h': {'total': len(posts), 'breaking': breaking, 'other': other},
            'urgency': editor.get('urgency', 'normal'),
            'hours_left': editor.get('hours_left_today', 0),
        },
        'signals_24h': _signals_24h(),
        'audit': {'total': len(audit), 'by_type': audit_by_type},
        'x_today': x_today,
        'recent_posts': [
            {'id': p['id'], 'title': (p['title']['rendered'] if isinstance(p['title'], dict) else p['title'])[:70], 'date': p['date']}
            for p in today_posts[:10]
        ],
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(data, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print(f"dashboard.json: today={data['kpi']['today']['total']} signals={data['signals_24h']['total']}")


if __name__ == '__main__':
    main()
