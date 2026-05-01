#!/usr/bin/env python3
"""人事部マネージャー — 全社員の稼働・成長・問題を毎日評価
cron: 30 23 * * *"""
import json, os, glob, re, sys
sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from datetime import datetime, timedelta
from pathlib import Path

ROSTER_PATH = 'config/staff_roster.json'
EVAL_DIR = Path('logs/hr_evaluations')
EVAL_DIR.mkdir(parents=True, exist_ok=True)

# Map staff IDs to their pipeline log patterns
STAFF_LOG_MAP = {
    'deoxys_kpop': ['logs/feature_article*', 'logs/daily_editor*'],
    'metamon_kpop': ['logs/breaking*', 'logs/popup_publish*'],
    'butterfree': ['logs/feature_article*'],
    'eevee': ['logs/feature_article*'],
    'jirachi_kpop': ['logs/feature_article*'],
    'gardevoir_hook_critic': ['logs/full_audit*', 'logs/audit_fixer*'],
    'arceus': ['logs/llm_proofreader*', 'logs/full_audit*'],
    'gengar': ['logs/quarantine*'],
    'alakazam_kpop': ['logs/post_publish_enricher*'],
    'lapras': ['logs/internal_link*'],
    'persian': ['logs/cta_*'],
    'mewtwo': ['logs/pipeline_health*'],
    'porygon': ['logs/post_publish_enricher*', 'logs/x_retry*'],
    'porygon_z': ['logs/x_retry*'],
    'raikou_thumb': ['logs/thumbnail_generator*'],
    'chansey': ['logs/hr_manager*'],
}

# Map staff to agent_lessons aliases
STAFF_LESSON_MAP = {
    'deoxys_kpop': 'feature_article_writer',
    'metamon_kpop': 'breaking_news_writer',
    'butterfree': 'beauty_writer',
    'eevee': 'trend_reporter',
    'jirachi_kpop': 'chart_analyst',
    'gardevoir_hook_critic': 'unknown',
    'arceus': 'unknown',
}


def evaluate_staff(staff_id):
    score = 100
    metrics = {'errors': 0, 'success': 0, 'last_active_h': None, 'lessons': 0, 'lessons_today': 0}
    since = (datetime.now() - timedelta(hours=24)).timestamp()

    # Check logs
    for pat in STAFF_LOG_MAP.get(staff_id, []):
        for f in glob.glob(pat):
            if os.path.getmtime(f) < since:
                continue
            try:
                hours = (datetime.now().timestamp() - os.path.getmtime(f)) / 3600
                if metrics['last_active_h'] is None or hours < metrics['last_active_h']:
                    metrics['last_active_h'] = round(hours, 1)
                c = open(f).read()[-20000:]
                metrics['errors'] += len(re.findall(r'NameError|Traceback|CRITICAL', c))
                metrics['success'] += len(re.findall(r'公開|published|HTTP 20[01]|OK', c))
            except:
                pass

    # Check lessons
    alias = STAFF_LESSON_MAP.get(staff_id, staff_id)
    lp = f'docs/agent_lessons/{alias}.md'
    if os.path.exists(lp):
        content = open(lp).read()
        metrics['lessons'] = content.count('\n- ')
        metrics['lessons_today'] = content.count(datetime.now().strftime('%Y-%m-%d'))

    # Score
    score -= metrics['errors'] * 5
    score += min(metrics['success'], 20)
    score += metrics['lessons_today'] * 3
    if metrics['last_active_h'] is None:
        score -= 20  # STALE penalty
    score = max(0, min(150, score))

    if score >= 120:
        status = 'excellent'
    elif score >= 100:
        status = 'above_100'
    elif score >= 80:
        status = 'standard'
    elif score >= 50:
        status = 'needs_improvement'
    else:
        status = 'critical'

    return {'score': score, 'status': status, 'metrics': metrics}


def main():
    roster = json.load(open(ROSTER_PATH))
    today = datetime.now().strftime('%Y-%m-%d')
    evaluations = {}

    for staff_id, info in roster.get('individual_staff', {}).items():
        result = evaluate_staff(staff_id)
        evaluations[staff_id] = result
        info['performance_score'] = result['score']
        info.setdefault('evaluations', []).append({
            'date': today, 'score': result['score'], 'status': result['status'],
        })
        info['evaluations'] = info['evaluations'][-30:]

    roster['last_updated'] = today
    json.dump(roster, open(ROSTER_PATH, 'w'), ensure_ascii=False, indent=2)

    # Dept summary
    by_dept = {}
    for staff_id, result in evaluations.items():
        dept = roster['individual_staff'].get(staff_id, {}).get('department', '?')
        by_dept.setdefault(dept, []).append({'id': staff_id, **result})

    print(f'=== 人事評価 {today} ({len(evaluations)}名) ===')
    for dept, members in sorted(by_dept.items()):
        avg = sum(m['score'] for m in members) / len(members)
        over100 = sum(1 for m in members if m['score'] >= 100)
        print(f'  {dept}: {len(members)}名 avg={avg:.0f} 100%超={over100}')

    # Critical
    critical = [s for s, e in evaluations.items() if e['score'] < 50]
    if critical:
        print(f'\n⚠️ 緊急介入: {critical}')

    # Save
    report_path = EVAL_DIR / f'hr_eval_{today}.json'
    json.dump({'date': today, 'total': len(evaluations), 'by_dept': {
        d: {'count': len(m), 'avg': round(sum(x['score'] for x in m) / len(m), 1),
            'over100': sum(1 for x in m if x['score'] >= 100)}
        for d, m in by_dept.items()
    }, 'all': evaluations}, open(report_path, 'w'), ensure_ascii=False, indent=2)
    print(f'\n保存: {report_path}')


if __name__ == '__main__':
    main()
