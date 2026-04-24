#!/usr/bin/env python3
"""AdSense収益取得 (OAuth token使用、日次 06:30)"""
import os, json
from datetime import datetime, timedelta

OUT = '/home/aiuser/kpop-ai-system/data/adsense_manual.json'
TOKEN = '/home/aiuser/kpop-ai-system/google_metrics/oauth_token.json'


def main():
    if not os.path.exists(TOKEN):
        print("oauth_token.json not found")
        return

    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    token = json.load(open(TOKEN))
    creds = Credentials(
        token=token.get('access_token'), refresh_token=token.get('refresh_token'),
        token_uri=token['token_uri'], client_id=token['client_id'], client_secret=token['client_secret'],
    )
    if creds.expired:
        creds.refresh(Request())
        token['access_token'] = creds.token
        json.dump(token, open(TOKEN, 'w'), indent=2)

    ads = build('adsense', 'v2', credentials=creds)
    accs = ads.accounts().list().execute().get('accounts', [])
    if not accs:
        print("AdSense account not found")
        return

    account = accs[0]['name']

    def revenue(start, end):
        resp = ads.accounts().reports().generate(
            account=account,
            startDate_year=start.year, startDate_month=start.month, startDate_day=start.day,
            endDate_year=end.year, endDate_month=end.month, endDate_day=end.day,
            metrics=['ESTIMATED_EARNINGS'], currencyCode='JPY',
        ).execute()
        rows = resp.get('rows', [])
        return float(rows[0]['cells'][0].get('value', 0)) if rows else 0

    yd = datetime.now() - timedelta(days=1)
    y = revenue(yd, yd)
    w = revenue(datetime.now() - timedelta(days=7), yd)
    m = revenue(datetime.now() - timedelta(days=30), yd)

    data = {
        'available': True,
        'yesterday_revenue_jpy': y,
        'last_7d_total_jpy': w,
        'last_7d_avg_jpy': round(w / 7, 2),
        'last_30d_total_jpy': m,
        'updated_at': datetime.now().isoformat(),
        'source': 'adsense_api_oauth',
    }
    json.dump(data, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print(f"AdSense: 昨日¥{y:.0f} 7d¥{w:.0f} 30d¥{m:.0f}")


if __name__ == '__main__':
    main()
