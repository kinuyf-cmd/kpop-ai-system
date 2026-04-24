#!/usr/bin/env python3
"""経営ダッシュボード用 完全JSON (15分毎)"""
import os, json, urllib.request, urllib.error, base64
from datetime import datetime, timedelta, timezone

AUTH = base64.b64encode(b"kpop-bot:vl1H 1brV m4Pq Z1sm F8lZ 3nzh").decode()
OUT = '/home/aiuser/kpopjournal-frontend/public/data/dashboard.json'
JST = timezone(timedelta(hours=9))

KPI_TARGETS = {
    'daily_articles': 20, 'daily_pv': 1000, 'daily_sessions': 500,
    'daily_gsc_clicks': 100, 'daily_x_posts': 10, 'daily_revenue_jpy': 1000,
    'monthly_articles': 600, 'monthly_pv': 30000, 'monthly_revenue_jpy': 30000,
    'monthly_ctr_pct': 3.0,
}


def _wp(after=None, pages=1):
    all_p = []
    for pg in range(1, pages + 1):
        q = f"per_page=100&page={pg}&_fields=id,date,title,status,link"
        if after: q = f"after={after}&{q}"
        try:
            r = urllib.request.urlopen(urllib.request.Request(
                f"https://www.kpopjournal.tokyo/wp-json/wp/v2/posts?{q}",
                headers={'Authorization': f'Basic {AUTH}'}), timeout=30)
            posts = json.loads(r.read())
            if not posts: break
            all_p.extend(posts)
            if len(posts) < 100: break
        except Exception: break
    return all_p


def _wp_total():
    try:
        r = urllib.request.urlopen(urllib.request.Request(
            "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts?per_page=1&_fields=id",
            headers={'Authorization': f'Basic {AUTH}'}), timeout=20)
        return int(r.headers.get('X-WP-Total', 0))
    except Exception: return 0


def _cls(t):
    s = t['rendered'] if isinstance(t, dict) else (t or '')
    return 'breaking' if '【速報】' in s or '【韓国メディア速報】' in s else 'other'


def _gsc():
    r = {'available': False, 'clicks': 0, 'impressions': 0, 'ctr': 0, 'daily_7d': [], 'error': None}
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        c = service_account.Credentials.from_service_account_file(
            '/home/aiuser/kpop-ai-system/google_metrics/service_account.json',
            scopes=['https://www.googleapis.com/auth/webmasters.readonly'])
        sc = build('searchconsole', 'v1', credentials=c)
        end = (datetime.now() - timedelta(days=3)).strftime('%Y-%m-%d')
        start = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        resp = sc.searchanalytics().query(siteUrl='https://www.kpopjournal.tokyo/',
            body={'startDate': start, 'endDate': end, 'dimensions': ['date'], 'rowLimit': 28}).execute()
        rows = resp.get('rows', [])
        cl = sum(x.get('clicks', 0) for x in rows)
        im = sum(x.get('impressions', 0) for x in rows)
        s7 = (datetime.now() - timedelta(days=10)).strftime('%Y-%m-%d')
        e7 = end
        r7 = sc.searchanalytics().query(siteUrl='https://www.kpopjournal.tokyo/',
            body={'startDate': s7, 'endDate': e7, 'dimensions': ['date'], 'rowLimit': 7}).execute()
        d7 = [{'date': x['keys'][0], 'clicks': x.get('clicks', 0), 'impressions': x.get('impressions', 0)} for x in r7.get('rows', [])]
        r.update({'available': True, 'clicks': cl, 'impressions': im,
                  'ctr': round(cl / im, 4) if im else 0,
                  'latest_date': max(x['keys'][0] for x in rows) if rows else None, 'daily_7d': d7})
    except Exception as e: r['error'] = str(e)[:150]
    return r


def _ga4():
    r = {'available': False, 'yesterday_users': 0, 'yesterday_pv': 0, 'yesterday_sessions': 0,
         'day_before_yesterday_users': 0, 'day_before_yesterday_pv': 0,
         '7d_users': 0, '7d_pv': 0, '7d_sessions': 0, '30d_users': 0, '30d_pv': 0,
         'realtime_users': 0, 'realtime_pv': 0, 'daily_7d': [], 'error': None}
    try:
        os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = '/home/aiuser/kpop-ai-system/google_metrics/service_account.json'
        from google.analytics.data_v1beta import BetaAnalyticsDataClient
        from google.analytics.data_v1beta.types import RunReportRequest, RunRealtimeReportRequest, DateRange, Metric, Dimension
        c = BetaAnalyticsDataClient()
        p = 'properties/493983919'
        yd = (datetime.now(JST) - timedelta(days=1)).strftime('%Y-%m-%d')
        dby = (datetime.now(JST) - timedelta(days=2)).strftime('%Y-%m-%d')
        # Yesterday
        rr = c.run_report(RunReportRequest(property=p, date_ranges=[DateRange(start_date=yd, end_date=yd)],
            metrics=[Metric(name='totalUsers'), Metric(name='screenPageViews'), Metric(name='sessions')]))
        if rr.rows:
            r['yesterday_users'] = int(rr.rows[0].metric_values[0].value)
            r['yesterday_pv'] = int(rr.rows[0].metric_values[1].value)
            r['yesterday_sessions'] = int(rr.rows[0].metric_values[2].value)
        # Day before
        rr2 = c.run_report(RunReportRequest(property=p, date_ranges=[DateRange(start_date=dby, end_date=dby)],
            metrics=[Metric(name='totalUsers'), Metric(name='screenPageViews')]))
        if rr2.rows:
            r['day_before_yesterday_users'] = int(rr2.rows[0].metric_values[0].value)
            r['day_before_yesterday_pv'] = int(rr2.rows[0].metric_values[1].value)
        # 7d daily
        s7 = (datetime.now(JST) - timedelta(days=7)).strftime('%Y-%m-%d')
        rr7 = c.run_report(RunReportRequest(property=p, date_ranges=[DateRange(start_date=s7, end_date=yd)],
            dimensions=[Dimension(name='date')], metrics=[Metric(name='totalUsers'), Metric(name='screenPageViews'), Metric(name='sessions')]))
        d7, tu, tp, ts = [], 0, 0, 0
        for row in rr7.rows:
            dd = row.dimension_values[0].value
            u, pv, ss = int(row.metric_values[0].value), int(row.metric_values[1].value), int(row.metric_values[2].value)
            d7.append({'date': f'{dd[:4]}-{dd[4:6]}-{dd[6:]}', 'users': u, 'pv': pv, 'sessions': ss})
            tu += u; tp += pv; ts += ss
        r.update({'7d_users': tu, '7d_pv': tp, '7d_sessions': ts, 'daily_7d': d7})
        # 30d
        s30 = (datetime.now(JST) - timedelta(days=30)).strftime('%Y-%m-%d')
        rr30 = c.run_report(RunReportRequest(property=p, date_ranges=[DateRange(start_date=s30, end_date=yd)],
            metrics=[Metric(name='totalUsers'), Metric(name='screenPageViews')]))
        if rr30.rows:
            r['30d_users'] = int(rr30.rows[0].metric_values[0].value)
            r['30d_pv'] = int(rr30.rows[0].metric_values[1].value)
        # Realtime
        rt = c.run_realtime_report(RunRealtimeReportRequest(property=p, metrics=[Metric(name='activeUsers'), Metric(name='screenPageViews')]))
        if rt.rows:
            r['realtime_users'] = int(rt.rows[0].metric_values[0].value)
            r['realtime_pv'] = int(rt.rows[0].metric_values[1].value)
        r['available'] = True
    except Exception as e: r['error'] = str(e)[:150]
    return r


def _adsense():
    fp = '/home/aiuser/kpop-ai-system/data/adsense_manual.json'
    if os.path.exists(fp):
        try:
            d = json.load(open(fp, encoding='utf-8'))
            return {'available': bool(d.get('available')) and bool(d.get('updated_at')),
                    'yesterday_jpy': d.get('yesterday_revenue_jpy', 0), '7d_total_jpy': d.get('last_7d_total_jpy', 0),
                    '7d_avg_jpy': d.get('last_7d_avg_jpy', 0), '30d_total_jpy': d.get('last_30d_total_jpy', 0),
                    'updated_at': d.get('updated_at', ''), 'source': d.get('source', ''), 'error': d.get('error')}
        except Exception: pass
    return {'available': False, 'error': '未連携'}


def _costs():
    r = {'total_jpy': 0, 'by_service': {}, 'calls': 0}
    cutoff = datetime.now() - timedelta(hours=24)
    for lp in ['/home/aiuser/kpop-ai-system/logs/dalle_cost.jsonl']:
        if not os.path.exists(lp): continue
        for line in open(lp, encoding='utf-8'):
            try:
                d = json.loads(line)
                if d.get('date', '') >= cutoff.strftime('%Y-%m-%d'):
                    cost_jpy = d.get('cost_usd', 0) * 150
                    r['total_jpy'] += cost_jpy; r['calls'] += 1
                    r['by_service']['dalle3'] = r['by_service'].get('dalle3', 0) + cost_jpy
            except Exception: pass
    for lp in ['/home/aiuser/kpop-ai-system/logs/translation.jsonl']:
        if not os.path.exists(lp): continue
        for line in open(lp, encoding='utf-8'):
            try:
                d = json.loads(line)
                if d.get('date', '') >= cutoff.strftime('%Y-%m-%d'):
                    cost_jpy = d.get('cost_usd', 0) * 150
                    r['total_jpy'] += cost_jpy; r['calls'] += 1
                    r['by_service']['gpt4o_mini'] = r['by_service'].get('gpt4o_mini', 0) + cost_jpy
            except Exception: pass
    r['total_jpy'] = round(r['total_jpy'], 1)
    for k in r['by_service']: r['by_service'][k] = round(r['by_service'][k], 1)
    return r


def _errors():
    r = {'today_total': 0, 'today_critical': 0, 'by_type': {}, 'recent_incidents': []}
    ap = '/home/aiuser/kpop-ai-system/logs/audit_issues.jsonl'
    if os.path.exists(ap):
        cutoff = datetime.now() - timedelta(hours=24)
        for line in open(ap, encoding='utf-8'):
            try:
                d = json.loads(line)
                ts = datetime.fromisoformat(d.get('ts', '')[:19])
                if ts >= cutoff:
                    r['today_total'] += 1
                    r['by_type'][d.get('issue', '?')] = r['by_type'].get(d.get('issue', '?'), 0) + 1
                    if d.get('severity') == 'high': r['today_critical'] += 1
            except Exception: pass
    for lp, kind in [('/home/aiuser/kpop-ai-system/logs/permanently_deleted.jsonl', 'deleted'),
                      ('/home/aiuser/kpop-ai-system/logs/quarantine.jsonl', 'quarantined')]:
        if os.path.exists(lp):
            for line in open(lp, encoding='utf-8').readlines()[-3:]:
                try:
                    d = json.loads(line)
                    r['recent_incidents'].append({'kind': kind, 'post_id': d.get('post_id'),
                        'reason': (d.get('deletion_reason') or d.get('quarantine_reason', ''))[:60],
                        'ts': d.get('deleted_at') or d.get('quarantined_at', '')})
                except Exception: pass
    return r


def _agents():
    cutoff = datetime.now() - timedelta(hours=24)
    specs = [
        ('editor', 'AI編集長', '/home/aiuser/kpop-ai-system/data/editor_state.json', 'json'),
        ('crawlers', 'クロール部', '/home/aiuser/kpop-ai-system/data/trend_signals.jsonl', 'sources'),
        ('publisher', '校正部', '/home/aiuser/kpop-ai-system/logs/unified_publish.jsonl', 'count'),
        ('auditor', '監査部', '/home/aiuser/kpop-ai-system/logs/audit_issues.jsonl', 'count'),
        ('x_poster', 'X担当', '/home/aiuser/kpop-ai-system/logs/x_posts.jsonl', 'count'),
    ]
    result = []
    for key, name, path, typ in specs:
        s = {'key': key, 'name': name, 'count_24h': 0, 'healthy': False, 'last': None}
        if not os.path.exists(path):
            result.append(s); continue
        if typ == 'json':
            try:
                d = json.load(open(path, encoding='utf-8'))
                ts = d.get('updated_at', d.get('generated_at', ''))
                if ts and datetime.fromisoformat(ts[:19]) >= cutoff:
                    s['count_24h'] = 1; s['healthy'] = True; s['last'] = ts[:16]
            except Exception: pass
        elif typ == 'count':
            for line in open(path, encoding='utf-8'):
                try:
                    d = json.loads(line)
                    ts_s = d.get('ts') or d.get('timestamp', '')
                    if ts_s and datetime.fromisoformat(ts_s[:19]) >= cutoff:
                        s['count_24h'] += 1
                        if not s['last'] or ts_s > s['last']: s['last'] = ts_s[:16]
                except Exception: pass
            s['healthy'] = s['count_24h'] > 0
        elif typ == 'sources':
            srcs = set()
            for line in open(path, encoding='utf-8'):
                try:
                    d = json.loads(line)
                    if d.get('timestamp', '')[:19] and datetime.fromisoformat(d['timestamp'][:19]) >= cutoff:
                        srcs.add(d.get('source_id', '?'))
                except Exception: pass
            s['count_24h'] = len(srcs); s['healthy'] = len(srcs) >= 5
        result.append(s)
    return result


def _delta(a, b):
    if not b: return None
    return round((a - b) / b * 100, 1)


def main():
    now = datetime.now(JST)
    today_utc = now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')
    yd_start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0).astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')
    yd_end = today_utc
    week_utc = (now - timedelta(days=7)).astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')
    month_utc = now.replace(day=1, hour=0, minute=0, second=0).astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')

    pt = [p for p in _wp(today_utc) if p.get('status') == 'publish']
    tb = sum(1 for p in pt if _cls(p['title']) == 'breaking')
    aw = _wp(week_utc, pages=3)
    py = [p for p in aw if p.get('status') == 'publish' and yd_start <= p['date'] + 'Z' < yd_end]
    yb = sum(1 for p in py if _cls(p['title']) == 'breaking')
    wp = [p for p in aw if p.get('status') == 'publish']
    # daily 7d
    ad7 = {}
    for p in wp:
        d = p['date'][:10]
        ad7.setdefault(d, {'total': 0, 'breaking': 0})
        ad7[d]['total'] += 1
        if _cls(p['title']) == 'breaking': ad7[d]['breaking'] += 1
    ad7l = [{'date': k, **v} for k, v in sorted(ad7.items())]

    pm = [p for p in _wp(month_utc, pages=10) if p.get('status') == 'publish']
    ta = _wp_total()
    gsc, ga4, ads = _gsc(), _ga4(), _adsense()
    costs, errors, agents = _costs(), _errors(), _agents()

    sig = 0
    sp = '/home/aiuser/kpop-ai-system/data/trend_signals.jsonl'
    if os.path.exists(sp):
        co = datetime.now() - timedelta(hours=24)
        for l in open(sp):
            try:
                if datetime.fromisoformat(json.loads(l).get('timestamp', '')[:19]) >= co: sig += 1
            except Exception: pass

    xp = 0
    xl = '/home/aiuser/kpop-ai-system/logs/x_posts.jsonl'
    if os.path.exists(xl):
        td = now.strftime('%Y-%m-%d')
        for l in open(xl):
            try:
                d = json.loads(l)
                if d.get('ts', '')[:10] == td and d.get('status') == 'ok': xp += 1
            except Exception: pass

    data = {
        'generated_at': now.isoformat(), 'targets': KPI_TARGETS,
        'kpi': {
            'today': {'published': len(pt), 'breaking': tb, 'other': len(pt) - tb,
                      'vs_yesterday_pct': _delta(len(pt), len(py))},
            'yesterday': {'published': len(py), 'breaking': yb, 'other': len(py) - yb},
        },
        'content_stats': {'week_total': len(wp), 'month_total': len(pm), 'site_total': ta},
        'articles_daily_7d': ad7l,
        'signals_24h': sig, 'x_posts_today': xp,
        'gsc': gsc, 'ga4': ga4, 'adsense': ads,
        'costs_24h': costs, 'errors': errors, 'agents': agents,
        'recent_posts': [
            {'id': p['id'], 'title': (p['title']['rendered'] if isinstance(p['title'], dict) else p['title'])[:80],
             'date': p['date'], 'classification': _cls(p['title'])} for p in pt[:10]
        ],
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(data, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print(f"v4 json: today={len(pt)} yd={len(py)} month={len(pm)} total={ta} GSC:{'OK' if gsc['available'] else 'NG'} GA4:{'OK' if ga4['available'] else 'NG'}")


if __name__ == '__main__':
    main()
