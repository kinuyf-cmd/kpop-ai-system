"""4/30最終100%完成自動検証"""
import requests, json, os, glob
from datetime import datetime

def check_urls():
    urls = [
        '/', '/about/', '/popup/', '/popular/', '/artist/', '/comeback-calendar/', '/chart-compare/',
        '/artist/bts/timeline/', '/artist/blackpink/timeline/', '/artist/seventeen/timeline/',
        '/artist/straykids/timeline/', '/artist/newjeans/timeline/', '/artist/aespa/timeline/',
        '/artist/twice/timeline/', '/artist/ive/timeline/', '/artist/lesserafim/timeline/',
        '/artist/enhypen/timeline/', '/artist/zerobaseone/timeline/', '/artist/riize/timeline/',
        '/artist/illit/timeline/', '/artist/babymonster/timeline/', '/artist/boynextdoor/timeline/',
        '/popup/tokyo/', '/popup/osaka/', '/popup/nagoya/', '/popup/fukuoka/',
        '/popup/seoul-gangnam/', '/popup/seoul-seongsu/', '/popup/seoul-hongdae/', '/popup/seoul-myeongdong/',
    ]
    ng = []
    for u in urls:
        try:
            r = requests.get(f'https://www.kpopjournal.tokyo{u}', timeout=10, allow_redirects=True)
            if r.status_code != 200:
                ng.append({'url': u, 'status': r.status_code})
        except Exception as e:
            ng.append({'url': u, 'error': str(e)[:50]})
    return {'total': len(urls), 'pass': len(urls) - len(ng), 'fail': ng}

def check_pipelines():
    patterns = {
        'full_audit': 'logs/full_audit*', 'llm_proofreader': 'logs/llm_proofreader*',
        'post_audit_feedback': 'logs/post_audit_feedback*', 'audit_fixer': 'logs/audit_fixer*',
        'thumbnail_generator': 'logs/thumbnail_generator*', 'internal_link': 'logs/internal_link*',
        'x_retry': 'logs/x_retry*', 'post_publish_enricher': 'logs/post_publish_enricher*',
        'comeback_predictor': 'logs/comeback_predictor*', 'chart_compare': 'logs/chart_compare*',
    }
    active = 0; stale = []
    for name, pat in patterns.items():
        files = glob.glob(pat)
        if files:
            newest = max(files, key=os.path.getmtime)
            hours = (datetime.now() - datetime.fromtimestamp(os.path.getmtime(newest))).total_seconds() / 3600
            if hours < 48: active += 1
            else: stale.append(name)
        else:
            stale.append(name)
    return {'total': len(patterns), 'active': active, 'stale': stale}

def check_meta():
    lessons = 0
    if os.path.exists('docs/lessons_learned.md'):
        lessons = sum(1 for l in open('docs/lessons_learned.md') if l.strip().startswith(('##', '-')))
    agents = len(glob.glob('docs/agent_lessons/*.md'))
    cron = int(os.popen('crontab -l 2>/dev/null | grep -v "^#" | grep -v "^$" | wc -l').read().strip())
    timelines = len(glob.glob('config/artist_timeline/*.json'))
    return {'lessons': lessons, 'agent_files': agents, 'cron_entries': cron, 'timelines': timelines}

def main():
    report = {
        'date': datetime.now().isoformat(),
        'urls': check_urls(),
        'pipelines': check_pipelines(),
        'meta': check_meta(),
    }
    m = report['meta']
    u = report['urls']
    p = report['pipelines']
    report['ready_for_4_30'] = (
        len(u['fail']) == 0 and
        p['active'] >= 7 and
        m['lessons'] >= 40 and
        m['timelines'] >= 15 and
        m['cron_entries'] >= 10
    )
    out = f'logs/completion_evidence/final_check_{datetime.now().strftime("%Y%m%d_%H%M")}.json'
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump(report, open(out, 'w'), ensure_ascii=False, indent=2)
    
    print(f'URLs: {u["pass"]}/{u["total"]} OK')
    print(f'Pipelines: {p["active"]}/{p["total"]} active')
    print(f'Meta: lessons={m["lessons"]} agents={m["agent_files"]} cron={m["cron_entries"]} timelines={m["timelines"]}')
    print(f'\n=> Ready for 4/30: {report["ready_for_4_30"]}')
    return report

if __name__ == '__main__':
    main()
