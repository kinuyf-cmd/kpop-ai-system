#!/usr/bin/env python3
"""GA4 Realtimeで過去30分のPV上位記事をJSON化"""
import json
import os
import re

os.environ.setdefault('GOOGLE_APPLICATION_CREDENTIALS',
                      '/home/aiuser/kpop-ai-system/google_metrics/service_account.json')
OUT = '/home/aiuser/kpopjournal-frontend/public/data/ga4_top.json'
os.makedirs(os.path.dirname(OUT), exist_ok=True)

try:
    from google.analytics.data_v1beta import BetaAnalyticsDataClient
    from google.analytics.data_v1beta.types import RunRealtimeReportRequest, Dimension, Metric

    c = BetaAnalyticsDataClient()
    rt = c.run_realtime_report(RunRealtimeReportRequest(
        property="properties/493983919",
        dimensions=[Dimension(name="unifiedScreenName")],
        metrics=[Metric(name="screenPageViews")],
        limit=20,
    ))
    items = []
    for row in rt.rows:
        title = row.dimension_values[0].value
        pv = int(row.metric_values[0].value)
        if ' | ' in title:
            title = title.split(' | ')[0].strip()
        # Skip non-article pages
        if title in ('K-POP JOURNAL', '検索', '記事が見つかりません'):
            continue
        slug = re.sub(r'[^a-z0-9\-]', '', title.lower().replace(' ', '-'))[:60] or f'article-{pv}'
        items.append({'slug': slug, 'title': title[:80], 'views': pv})
    items.sort(key=lambda x: -x['views'])
    json.dump({'items': items[:10]}, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print(f"ga4_top.json: {len(items[:10])}件")
except Exception as e:
    print(f"GA4 fetch: {e}")
    json.dump({'items': []}, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)
