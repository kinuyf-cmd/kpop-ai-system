#!/usr/bin/env python3
"""a8_materials.csv → a8_materials.json 変換"""
import csv, json, os, re
from datetime import datetime, timezone

csv_path = '/home/aiuser/kpop-ai-system/config/affiliate/a8_materials.csv'
json_path = '/home/aiuser/kpop-ai-system/config/affiliate/a8_materials.json'

if not os.path.exists(csv_path):
    print(f"⚠️ {csv_path} 未作成、オーナーが先に作成必要")
    print("形式: internal_key,html_material,raw_url")
    exit()

data = json.load(open(json_path)) if os.path.exists(json_path) else {'programs': {}}

count = 0
with open(csv_path, encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        key = row.get('internal_key', '').strip()
        html = row.get('html_material', '').strip()
        url = row.get('raw_url', '').strip()

        if not key or not html:
            continue

        href_match = re.search(r'href="([^"]+)"', html)
        extracted_url = href_match.group(1) if href_match else ''

        if not url:
            url = extracted_url

        if 'a8mat=' not in html and 'px.a8.net' not in html:
            print(f"  ⚠️ {key}: a8matパラメータなし、スキップ")
            continue

        data['programs'][key] = {
            'html_material': html,
            'raw_url': url,
            'extracted_url': extracted_url,
            'registered_at': datetime.now(timezone.utc).isoformat(),
        }
        count += 1

json.dump(data, open(json_path, 'w'), ensure_ascii=False, indent=2)
print(f"✅ {count}件 a8_materials.jsonに登録")
