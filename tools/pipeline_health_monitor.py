"""パイプライン健全性監視 — NameError等の例外検知 (毎時20分)"""
import os, glob, re
from datetime import datetime, timedelta

ALERT_PATTERNS = [
    r'NameError', r'ImportError', r'ModuleNotFoundError',
    r'AttributeError.*not defined', r'Traceback',
]

def check():
    since = (datetime.now() - timedelta(hours=24)).timestamp()
    alerts = []
    for f in glob.glob('logs/*.log'):
        if os.path.getmtime(f) < since:
            continue
        try:
            content = open(f).read()[-20000:]
            for pat in ALERT_PATTERNS:
                matches = re.findall(pat, content)
                if matches:
                    alerts.append({'file': os.path.basename(f), 'pattern': pat, 'count': len(matches)})
        except:
            pass
    if alerts:
        os.makedirs('logs', exist_ok=True)
        with open('logs/pipeline_alerts.log', 'a') as af:
            af.write(f'\n=== {datetime.now().isoformat()} ===\n')
            for a in alerts:
                af.write(f'  {a["file"]}: {a["pattern"]} x{a["count"]}\n')
    return alerts

if __name__ == '__main__':
    alerts = check()
    print(f'検知: {len(alerts)}件')
    for a in alerts:
        print(f'  {a["file"]}: {a["pattern"]} x{a["count"]}')
