#!/usr/bin/env python3
"""翻訳API使用量監視 (30分毎cron実行)

閾値:
  90%以上 → critical
  80%以上 → warning
  60%以上 → info
"""
import json, os
from datetime import datetime

LOG = '/home/aiuser/kpop-ai-system/logs/translation.jsonl'
LIMIT = 300
THRESHOLD = '/home/aiuser/kpop-ai-system/data/translation_threshold.json'


def main():
    if not os.path.exists(LOG):
        print("翻訳ログなし")
        return

    today = datetime.now().strftime('%Y-%m-%d')
    used = 0
    with open(LOG, encoding='utf-8') as f:
        for line in f:
            try:
                if json.loads(line).get('date') == today:
                    used += 1
            except:
                pass

    pct = used / LIMIT * 100
    if pct >= 90:
        level = 'critical'
    elif pct >= 80:
        level = 'warning'
    elif pct >= 60:
        level = 'info'
    else:
        level = 'normal'

    flag = {
        'level': level,
        'used': used,
        'limit': LIMIT,
        'pct': round(pct, 1),
        'updated_at': datetime.now().isoformat(),
    }

    os.makedirs(os.path.dirname(THRESHOLD), exist_ok=True)
    with open(THRESHOLD, 'w', encoding='utf-8') as f:
        json.dump(flag, f, ensure_ascii=False, indent=2)

    icon = '\U0001f534' if level == 'critical' else '\U0001f7e1' if level == 'warning' else '\U0001f7e2'
    print(f"{icon} 翻訳API: {used}/{LIMIT} ({pct:.0f}%) level={level}")

    if level == 'critical':
        print("  間もなく上限到達、パイプライン停止リスク")


if __name__ == '__main__':
    main()
