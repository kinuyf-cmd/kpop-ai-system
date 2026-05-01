"""実務自動配分 — シグナル/draft/監査結果から社員にタスク振分
cron: 0 * * * *"""
import json, glob, os, sys
sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from dotenv import load_dotenv
load_dotenv('/home/aiuser/kpop-ai-system/.env')
from datetime import datetime
from lib.manager_logic import delegate_to_subordinate

def dispatch_drafts():
    import requests
    auth = (os.getenv('WP_USER', ''), os.getenv('WP_PASS', ''))
    try:
        r = requests.get('https://www.kpopjournal.tokyo/wp-json/wp/v2/posts?status=draft&per_page=5&_fields=id,title',
                         auth=auth, timeout=10)
        drafts = r.json() if r.status_code == 200 and isinstance(r.json(), list) else []
        count = 0
        for p in drafts:
            delegate_to_subordinate('KPJ-0029', 'proofread_draft',
                                   meta={'post_id': p['id'], 'title': p['title']['rendered'][:40]})
            count += 1
        return count
    except:
        return 0

def dispatch_audit_fixes():
    try:
        state_file = '/home/aiuser/kpop-ai-system/data/audit_state.jsonl'
        if not os.path.exists(state_file):
            return 0
        count = 0
        for line in open(state_file):
            try:
                rec = json.loads(line)
                if rec.get('high_count', 0) >= 2:
                    delegate_to_subordinate('KPJ-0032', 'fix_high_issue',
                                           meta={'post_id': rec.get('post_id')})
                    count += 1
                    if count >= 5:
                        break
            except:
                pass
        return count
    except:
        return 0

def main():
    report = {
        'timestamp': datetime.now().isoformat(),
        'drafts': dispatch_drafts(),
        'audit_fixes': dispatch_audit_fixes(),
    }
    report['total'] = report['drafts'] + report['audit_fixes']
    os.makedirs('logs', exist_ok=True)
    with open('logs/staff_dispatcher.log', 'a') as f:
        f.write(json.dumps(report, ensure_ascii=False) + '\n')
    print(f'Dispatcher: drafts={report["drafts"]} fixes={report["audit_fixes"]} total={report["total"]}')

if __name__ == '__main__':
    main()
