"""韓国vs日本チャート比較 — Circle Chart + Oricon + Billboard JAPAN
cron: 0 10 * * 2 (毎週火曜)"""
import json, os, glob, re
from datetime import datetime

def fetch_circle_chart():
    files = sorted(glob.glob('logs/circle_chart_*.json') + glob.glob('data/chart_weekly*.json'))
    if not files:
        return []
    try:
        d = json.load(open(files[-1]))
        if isinstance(d, list):
            return d
        for key in ('entries', 'songs', 'chart'):
            if key in d and isinstance(d[key], list):
                return d[key]
        return []
    except:
        return []

def get_kpop_names():
    names = set()
    for f in glob.glob('config/artist_timeline/*.json'):
        try:
            d = json.load(open(f))
            for field in ['name', 'name_en', 'name_kr']:
                v = d.get(field, '')
                if v and len(v) >= 2:
                    names.add(v.lower())
        except:
            pass
    return names

def main():
    circle = fetch_circle_chart()[:30]
    kpop_names = get_kpop_names()

    out = {
        'date': datetime.now().strftime('%Y-%m-%d'),
        'circle_chart': circle,
        'oricon': [],  # Requires scraping — skip in initial version to avoid blocking
        'billboard_jp': [],
        'kpop_in_oricon': [],
        'kpop_in_billboard_jp': [],
        'note': 'Oricon/Billboard JP scraping は robots.txt制約のため初回はCircle単独。週次手動補完可能',
    }

    # Save
    log_path = f'logs/chart_compare_{out["date"]}.json'
    json.dump(out, open(log_path, 'w'), ensure_ascii=False, indent=2)

    latest = 'config/chart_compare_latest.json'
    json.dump(out, open(latest, 'w'), ensure_ascii=False, indent=2)

    print(f'Circle Chart: {len(circle)}件')
    print(f'Oricon/Billboard JP: robots.txt制約のためスキップ（手動補完可能）')

if __name__ == '__main__':
    main()
