#!/usr/bin/env python3
"""AdSense収益取得 (日次 06:30)

service_accountでAPI試行。失敗ならadsense_manual.jsonにエラー記録。
オーナー作業: AdSense管理画面でservice_accountメールをユーザー追加すれば動く。
"""
import os, json
from datetime import datetime, timedelta

OUT = '/home/aiuser/kpop-ai-system/data/adsense_manual.json'


def try_service_account():
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        creds = service_account.Credentials.from_service_account_file(
            '/home/aiuser/kpop-ai-system/google_metrics/service_account.json',
            scopes=['https://www.googleapis.com/auth/adsense.readonly'],
        )
        adsense = build('adsense', 'v2', credentials=creds)
        accs = adsense.accounts().list().execute().get('accounts', [])
        if not accs:
            return None

        account = accs[0]['name']
        yd = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d').split('-')
        s7 = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d').split('-')
        s30 = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d').split('-')

        def revenue(start, end):
            resp = adsense.accounts().reports().generate(
                account=account,
                startDate_year=int(start[0]), startDate_month=int(start[1]), startDate_day=int(start[2]),
                endDate_year=int(end[0]), endDate_month=int(end[1]), endDate_day=int(end[2]),
                metrics=['ESTIMATED_EARNINGS'], currencyCode='JPY',
            ).execute()
            rows = resp.get('rows', [])
            return float(rows[0]['cells'][0].get('value', 0)) if rows else 0

        y = revenue(yd, yd)
        w = revenue(s7, yd)
        m = revenue(s30, yd)
        return {
            'available': True,
            'yesterday_revenue_jpy': y,
            'last_7d_total_jpy': w,
            'last_7d_avg_jpy': round(w / 7, 2),
            'last_30d_total_jpy': m,
            'updated_at': datetime.now().isoformat(),
            'source': 'adsense_api',
        }
    except Exception as e:
        return {'error': str(e)[:300]}


def main():
    result = try_service_account()
    if result and result.get('available'):
        print(f"AdSense OK: 昨日¥{result['yesterday_revenue_jpy']} 7d¥{result['last_7d_total_jpy']}")
        json.dump(result, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    else:
        err = result.get('error', '?') if result else '?'
        print(f"AdSense NG: {err[:150]}")
        sa = json.load(open('/home/aiuser/kpop-ai-system/google_metrics/service_account.json'))
        print(f"  → AdSense管理画面で {sa.get('client_email')} をユーザー追加してください")
        data = {'available': False, 'error': err[:200], 'last_check': datetime.now().isoformat()}
        if os.path.exists(OUT):
            try:
                existing = json.load(open(OUT))
                existing.update(data)
                data = existing
            except Exception:
                pass
        json.dump(data, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)


if __name__ == '__main__':
    main()
