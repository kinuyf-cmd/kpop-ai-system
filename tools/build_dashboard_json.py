#!/usr/bin/env python3
"""ダッシュボードJSON生成 (全数値を実データから取得)"""
import os, json, urllib.request, urllib.error, base64
from datetime import datetime, timedelta, timezone

AUTH = base64.b64encode(b"kpop-bot:vl1H 1brV m4Pq Z1sm F8lZ 3nzh").decode()
OUT = '/home/aiuser/kpopjournal-frontend/public/data/dashboard.json'
JST = timezone(timedelta(hours=9))


def _wp_posts(after_utc, pages=1):
    all_posts = []
    for pg in range(1, pages + 1):
        url = f"https://www.kpopjournal.tokyo/wp-json/wp/v2/posts?after={after_utc}&per_page=100&page={pg}&_fields=id,date,title,status"
        try:
            req = urllib.request.Request(url, headers={'Authorization': f'Basic {AUTH}'})
            posts = json.loads(urllib.request.urlopen(req, timeout=30).read())
            if not posts: break
            all_posts.extend(posts)
            if len(posts) < 100: break
        except urllib.error.HTTPError:
            break
        except Exception:
            break
    return all_posts


def _wp_total():
    try:
        req = urllib.request.Request(
            "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts?per_page=1&_fields=id",
            headers={'Authorization': f'Basic {AUTH}'})
        r = urllib.request.urlopen(req, timeout=20)
        return int(r.headers.get('X-WP-Total', 0))
    except Exception:
        return 0


def _classify(title):
    t = title if isinstance(title, str) else title.get('rendered', '') if isinstance(title, dict) else ''
    return 'breaking' if ('【速報】' in t or '【韓国メディア速報】' in t) else 'other'


def _gsc():
    result = {'available': False, 'clicks': 0, 'impressions': 0, 'ctr': 0, 'error': None}
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        creds = service_account.Credentials.from_service_account_file(
            '/home/aiuser/kpop-ai-system/google_metrics/service_account.json',
            scopes=['https://www.googleapis.com/auth/webmasters.readonly'])
        sc = build('searchconsole', 'v1', credentials=creds)
        end = (datetime.now() - timedelta(days=3)).strftime('%Y-%m-%d')
        start = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        resp = sc.searchanalytics().query(
            siteUrl='https://www.kpopjournal.tokyo/',
            body={'startDate': start, 'endDate': end, 'dimensions': ['date'], 'rowLimit': 28}
        ).execute()
        rows = resp.get('rows', [])
        clicks = sum(r.get('clicks', 0) for r in rows)
        imps = sum(r.get('impressions', 0) for r in rows)
        result.update({'available': True, 'clicks': clicks, 'impressions': imps,
                       'ctr': round(clicks / imps, 4) if imps else 0,
                       'latest_date': max(r['keys'][0] for r in rows) if rows else None})
    except Exception as e:
        result['error'] = str(e)[:150]
    return result


def _ga4():
    result = {'available': False, 'yesterday_users': 0, 'yesterday_pv': 0,
              'realtime_users': 0, 'error': None}
    try:
        os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = '/home/aiuser/kpop-ai-system/google_metrics/service_account.json'
        from google.analytics.data_v1beta import BetaAnalyticsDataClient
        from google.analytics.data_v1beta.types import (
            RunReportRequest, RunRealtimeReportRequest, DateRange, Metric)
        client = BetaAnalyticsDataClient()
        prop = 'properties/493983919'

        # 昨日
        yd = (datetime.now(JST) - timedelta(days=1)).strftime('%Y-%m-%d')
        r = client.run_report(RunReportRequest(
            property=prop, date_ranges=[DateRange(start_date=yd, end_date=yd)],
            metrics=[Metric(name='totalUsers'), Metric(name='screenPageViews')]))
        if r.rows:
            result['yesterday_users'] = int(r.rows[0].metric_values[0].value)
            result['yesterday_pv'] = int(r.rows[0].metric_values[1].value)

        # Realtime
        rr = client.run_realtime_report(RunRealtimeReportRequest(
            property=prop, metrics=[Metric(name='activeUsers'), Metric(name='screenPageViews')]))
        if rr.rows:
            result['realtime_users'] = int(rr.rows[0].metric_values[0].value)
            result['realtime_pv'] = int(rr.rows[0].metric_values[1].value)

        result['available'] = True
    except Exception as e:
        result['error'] = str(e)[:150]
    return result


def _adsense():
    p = '/home/aiuser/kpop-ai-system/data/adsense_manual.json'
    if os.path.exists(p):
        try:
            d = json.load(open(p, encoding='utf-8'))
            return {
                'available': bool(d.get('updated_at')),
                'yesterday_jpy': d.get('yesterday_revenue_jpy', 0),
                '7d_total_jpy': d.get('last_7d_total_jpy', 0),
                '30d_total_jpy': d.get('last_30d_total_jpy', 0),
                'updated_at': d.get('updated_at', ''),
            }
        except Exception:
            pass
    return {'available': False}


def _count_file(path, hours=24):
    if not os.path.exists(path): return 0
    cutoff = datetime.now() - timedelta(hours=hours)
    n = 0
    for line in open(path, encoding='utf-8'):
        try:
            ts = datetime.fromisoformat(json.loads(line).get('timestamp', json.loads(line).get('ts', ''))[:19])
            if ts >= cutoff: n += 1
        except Exception:
            pass
    return n


def main():
    now = datetime.now(JST)
    today_utc = now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')
    month_utc = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')

    posts_today = [p for p in _wp_posts(today_utc) if p.get('status') == 'publish']
    today_brk = sum(1 for p in posts_today if _classify(p['title']) == 'breaking')
    posts_month = [p for p in _wp_posts(month_utc, pages=10) if p.get('status') == 'publish']
    total_all = _wp_total()
    gsc = _gsc()
    ga4 = _ga4()
    adsense = _adsense()

    signals = _count_file('/home/aiuser/kpop-ai-system/data/trend_signals.jsonl', 24)
    x_today = 0
    xp = '/home/aiuser/kpop-ai-system/logs/x_posts.jsonl'
    if os.path.exists(xp):
        td = now.strftime('%Y-%m-%d')
        x_today = sum(1 for l in open(xp) if l.strip() and json.loads(l).get('ts', '')[:10] == td and json.loads(l).get('status') == 'ok')

    data = {
        'generated_at': now.isoformat(),
        'kpi': {
            'today': {'published': len(posts_today), 'breaking': today_brk, 'other': len(posts_today) - today_brk, 'target': 20},
        },
        'content_stats': {'month_total': len(posts_month), 'site_total': total_all},
        'signals_24h': signals,
        'x_posts_today': x_today,
        'gsc': gsc,
        'adsense': adsense,
        'ga4': ga4,
        'recent_posts': [
            {'id': p['id'], 'title': (p['title']['rendered'] if isinstance(p['title'], dict) else p['title'])[:70],
             'date': p['date'], 'classification': _classify(p['title'])}
            for p in posts_today[:10]
        ],
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(data, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)

    print(f"dashboard.json: today={len(posts_today)} month={len(posts_month)} total={total_all}")
    print(f"  GSC: {'OK clicks=' + str(gsc['clicks']) if gsc['available'] else 'err'}")
    print(f"  GA4: {'OK rt=' + str(ga4.get('realtime_users', 0)) if ga4['available'] else 'err'}")


if __name__ == '__main__':
    main()
