#!/usr/bin/env python3
"""AdSense CSVレポート取込 (API連携不可時の暫定)

オーナーがAdSense管理画面でCSV DL → data/adsense_import/ に配置
日次06:35実行、最新CSVを解析→adsense_manual.json更新
"""
import os, csv, json, glob
from datetime import datetime

IMPORT_DIR = '/home/aiuser/kpop-ai-system/data/adsense_import/'
OUT = '/home/aiuser/kpop-ai-system/data/adsense_manual.json'


def main():
    os.makedirs(IMPORT_DIR, exist_ok=True)
    csv_files = sorted(glob.glob(os.path.join(IMPORT_DIR, '*.csv')))
    if not csv_files:
        print(f"CSVなし ({IMPORT_DIR})")
        return

    latest = csv_files[-1]
    print(f"取込: {latest}")

    daily = {}
    try:
        with open(latest, encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                date = row.get('Date') or row.get('日付', '')
                earnings = float(
                    row.get('Estimated earnings (JPY)')
                    or row.get('推定収益額')
                    or row.get('Earnings')
                    or 0
                )
                if date:
                    daily[date] = earnings
    except Exception as e:
        print(f"CSV解析error: {e}")
        return

    if not daily:
        print("データなし")
        return

    dates = sorted(daily.keys())
    last_30 = sum(daily[d] for d in dates[-30:])
    last_7 = sum(daily[d] for d in dates[-7:])
    yesterday = daily.get(dates[-1], 0)

    data = {
        'available': True,
        'yesterday_revenue_jpy': yesterday,
        'last_7d_total_jpy': last_7,
        'last_7d_avg_jpy': round(last_7 / 7, 2),
        'last_30d_total_jpy': last_30,
        'updated_at': datetime.now().isoformat(),
        'source': 'csv_import',
        'csv_file': os.path.basename(latest),
    }
    json.dump(data, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print(f"昨日({dates[-1]}): ¥{yesterday} / 7d: ¥{last_7} / 30d: ¥{last_30}")


if __name__ == '__main__':
    main()
