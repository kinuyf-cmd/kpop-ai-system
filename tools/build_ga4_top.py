#!/usr/bin/env python3
"""GA4 Realtimeで過去30分のPV上位記事をJSON化

2026-05-12 修正: pagePath dimension を採用して **実 WP slug** を取得する。
従来 unifiedScreenName (タイトル) から regex で slug 自作していたため、
WP の実 slug と一致せずリンク 404 になっていた事故への根治。
"""
import json
import os

os.environ.setdefault('GOOGLE_APPLICATION_CREDENTIALS',
                      '/home/aiuser/kpop-ai-system/google_metrics/service_account.json')
OUT = '/home/aiuser/kpopjournal-frontend/public/data/ga4_top.json'
os.makedirs(os.path.dirname(OUT), exist_ok=True)

try:
    from google.analytics.data_v1beta import BetaAnalyticsDataClient
    from google.analytics.data_v1beta.types import RunRealtimeReportRequest, Dimension, Metric

    c = BetaAnalyticsDataClient()
    # Realtime API は pagePath dimension 非対応 (unifiedScreenName のみ)。
    # title から WP REST ?search= で実 slug を解決する方式。
    rt = c.run_realtime_report(RunRealtimeReportRequest(
        property="properties/493983919",
        dimensions=[Dimension(name="unifiedScreenName")],
        metrics=[Metric(name="screenPageViews")],
        limit=30,
    ))
    import urllib.parse
    import urllib.request
    items = []
    seen_slugs = set()
    for row in rt.rows:
        title = row.dimension_values[0].value or ''
        pv = int(row.metric_values[0].value)
        if ' | ' in title:
            title = title.split(' | ')[0].strip()
        if title in ('K-POP JOURNAL', '検索', '記事が見つかりません', '(not set)'):
            continue
        # WP REST で実 slug 解決 (検索ヒット 1件目を採用、なければ skip)
        slug = ''
        try:
            q = urllib.parse.quote_plus(title[:50])
            u = f'https://www.kpopjournal.tokyo/wp-json/wp/v2/posts?search={q}&per_page=1&_fields=slug'
            r = urllib.request.urlopen(u, timeout=8)
            data = json.loads(r.read())
            if data:
                slug = data[0].get('slug', '')
        except Exception:
            slug = ''
        if not slug or slug in seen_slugs:
            continue
        seen_slugs.add(slug)
        items.append({'slug': slug, 'title': title[:80], 'views': pv})
    items.sort(key=lambda x: -x['views'])
    json.dump({'items': items[:10]}, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print(f"ga4_top.json: {len(items[:10])}件 (WP REST 実 slug 解決)")
except Exception as e:
    print(f"GA4 fetch: {e}")
    json.dump({'items': []}, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)
