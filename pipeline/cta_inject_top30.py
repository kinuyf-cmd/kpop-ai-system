#!/usr/bin/env python3
"""高PV TOP30記事に CTAを一括挿入"""
import sys, os, json, urllib.request, base64
sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from datetime import datetime, timezone
from dotenv import load_dotenv
load_dotenv('/home/aiuser/kpop-ai-system/.env')

from lib.cta_injector import inject_cta_into_content

WP_USER = os.getenv('WP_USER', '')
WP_PASS = os.getenv('WP_PASS', '')
AUTH = base64.b64encode(f"{WP_USER}:{WP_PASS}".encode()).decode()


def get_top30_articles_from_ga4():
    """GA4から過去30日のPV TOP30を取得"""
    try:
        from google.oauth2.credentials import Credentials
        from google.analytics.data_v1beta import BetaAnalyticsDataClient
        from google.analytics.data_v1beta.types import (
            DateRange, Dimension, Metric, RunReportRequest, OrderBy,
        )

        token_path = '/home/aiuser/kpop-ai-system/google_metrics/oauth_token.json'
        creds = Credentials.from_authorized_user_file(token_path)
        client = BetaAnalyticsDataClient(credentials=creds)

        request = RunReportRequest(
            property='properties/493983919',
            date_ranges=[DateRange(start_date='30daysAgo', end_date='today')],
            dimensions=[Dimension(name='pagePath')],
            metrics=[Metric(name='screenPageViews')],
            order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name='screenPageViews'), desc=True)],
            limit=50,
        )
        response = client.run_report(request)

        results = []
        for row in response.rows:
            path = row.dimension_values[0].value
            pv = int(row.metric_values[0].value)
            if path.startswith('/') and not path.startswith('/dash') and not path.startswith('/popup'):
                results.append({'path': path, 'pv': pv})

        return results[:30]
    except Exception as e:
        print(f"GA4 err: {e}")
        return []


def find_post_id_by_path(path):
    """URLパスから WP post_id を逆引き"""
    slug = path.strip('/').split('/')[-1] if path.strip('/') else ''
    if not slug:
        return None
    try:
        url = f"https://www.kpopjournal.tokyo/wp-json/wp/v2/posts?slug={slug}&_fields=id,title,content&context=edit"
        req = urllib.request.Request(url, headers={'Authorization': f'Basic {AUTH}'})
        data = json.loads(urllib.request.urlopen(req, timeout=20).read())
        if data:
            return data[0]
    except Exception as e:
        print(f"  find err {slug}: {e}")
    return None


def inject_cta_to_post(post):
    pid = post['id']
    title = post.get('title', {}).get('rendered', '') if isinstance(post.get('title'), dict) else ''
    content = post.get('content', {}).get('raw') or post.get('content', {}).get('rendered', '')

    new_content = inject_cta_into_content(title, content)

    if new_content == content:
        return False, 'no_change'

    body = json.dumps({'content': new_content}).encode()
    try:
        req = urllib.request.Request(
            f"https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/{pid}",
            data=body, method='POST',
            headers={'Authorization': f'Basic {AUTH}', 'Content-Type': 'application/json'})
        urllib.request.urlopen(req, timeout=30).read()
        return True, 'updated'
    except Exception as e:
        return False, f'err: {e}'


def main():
    print("=== TOP30記事取得 (GA4) ===")
    top30 = get_top30_articles_from_ga4()
    if not top30:
        print("GA4取得失敗、最新30件フォールバック")
        url = "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts?per_page=30&orderby=date&order=desc&_fields=id,title,slug,content&context=edit"
        try:
            req = urllib.request.Request(url, headers={'Authorization': f'Basic {AUTH}'})
            posts = json.loads(urllib.request.urlopen(req, timeout=30).read())
            print(f"フォールバック: 最新{len(posts)}件取得")
        except Exception as e:
            print(f"err: {e}")
            return
    else:
        print(f"GA4 TOP30 取得成功")
        for i, item in enumerate(top30[:10]):
            print(f"  {i+1}. PV={item['pv']} {item['path']}")

        posts = []
        for item in top30:
            post = find_post_id_by_path(item['path'])
            if post:
                posts.append(post)
        print(f"post_id解決: {len(posts)}/{len(top30)}件")

    print(f"\n=== CTA挿入処理 ===")
    success = 0
    skipped = 0
    for post in posts:
        ok, msg = inject_cta_to_post(post)
        if ok:
            success += 1
            title_text = post.get('title', {}).get('rendered', '')[:40] if isinstance(post.get('title'), dict) else ''
            print(f"  OK post_id={post['id']} {title_text}")
        elif msg == 'no_change':
            skipped += 1
        else:
            print(f"  NG post_id={post['id']}: {msg}")

    print(f"\n{success}件 CTA挿入完了 / {skipped}件スキップ")

    log = '/home/aiuser/kpop-ai-system/logs/cta_inject.jsonl'
    os.makedirs(os.path.dirname(log), exist_ok=True)
    with open(log, 'a', encoding='utf-8') as f:
        f.write(json.dumps({
            'ts': datetime.now(timezone.utc).isoformat(),
            'top30_attempted': len(posts),
            'success': success,
            'skipped': skipped,
        }, ensure_ascii=False) + '\n')


if __name__ == '__main__':
    main()
