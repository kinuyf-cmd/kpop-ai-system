"""カムバック予測: artist_timeline/*.json から過去パターン分析 → 次回予測
cron: 0 4 * * *"""
import json, os, glob
from datetime import datetime, timedelta

def analyze_artist(path):
    d = json.load(open(path))
    events = [e for e in d.get('events', []) if e.get('type') in ('comeback', 'album')]
    events.sort(key=lambda e: e['date'])
    if len(events) < 2:
        return None
    intervals = []
    for i in range(1, len(events)):
        try:
            d1 = datetime.strptime(events[i-1]['date'], '%Y-%m-%d')
            d2 = datetime.strptime(events[i]['date'], '%Y-%m-%d')
            intervals.append((d2 - d1).days)
        except:
            pass
    if not intervals:
        return None
    avg = sum(intervals) / len(intervals)
    try:
        last = datetime.strptime(events[-1]['date'], '%Y-%m-%d')
    except:
        return None
    predicted = last + timedelta(days=int(avg))
    return {
        'slug': d.get('slug'), 'name': d.get('name'),
        'last_comeback': events[-1]['date'],
        'last_title': events[-1].get('title', ''),
        'avg_interval_days': int(avg),
        'predicted_next': predicted.strftime('%Y-%m-%d'),
        'confidence': 'medium' if len(intervals) >= 3 else 'low',
        'sample_size': len(intervals),
    }

def main():
    predictions = []
    for f in glob.glob('config/artist_timeline/*.json'):
        p = analyze_artist(f)
        if p:
            predictions.append(p)

    path = 'config/comeback_calendar.json'
    if os.path.exists(path):
        d = json.load(open(path))
    else:
        d = {'schema_version': '1.0', 'predictions': []}

    d['ai_predictions'] = sorted(predictions, key=lambda x: x['predicted_next'])
    d['last_updated'] = datetime.now().strftime('%Y-%m-%d')
    json.dump(d, open(path, 'w'), ensure_ascii=False, indent=2)

    print(f'予測生成: {len(predictions)}アーティスト')
    for p in sorted(predictions, key=lambda x: x['predicted_next'])[:8]:
        print(f'  {p["name"]}: {p["last_comeback"]} → 次回予測 {p["predicted_next"]} ({p["avg_interval_days"]}日間隔, {p["confidence"]})')

if __name__ == '__main__':
    main()
