"""個別社員ログ自動分離"""
import json, os
from datetime import datetime, timedelta
from pathlib import Path

PIPE_MAP_PATH = '/home/aiuser/kpop-ai-system/config/pipeline_to_staff.json'
STAFF_LOG_DIR = Path('/home/aiuser/kpop-ai-system/logs/staff')
STAFF_LOG_DIR.mkdir(parents=True, exist_ok=True)

_pipe_to_staff = None

def _load_map():
    global _pipe_to_staff
    if _pipe_to_staff is None:
        try:
            _pipe_to_staff = json.load(open(PIPE_MAP_PATH))
        except:
            _pipe_to_staff = {}
    return _pipe_to_staff

def get_staff_id(pipeline_name):
    m = _load_map()
    if pipeline_name in m:
        return m[pipeline_name]
    for k, v in m.items():
        if k in pipeline_name or pipeline_name in k:
            return v
    return None

def log_for_staff(staff_id_or_pipeline, event, level='INFO'):
    sid = staff_id_or_pipeline if staff_id_or_pipeline.startswith('KPJ-') else get_staff_id(staff_id_or_pipeline)
    if not sid:
        sid = 'UNKNOWN'
    log_path = STAFF_LOG_DIR / f'{sid}.log'
    ts = datetime.now().isoformat()
    with open(log_path, 'a') as f:
        f.write(f'[{ts}] [{level}] {event}\n')
    return sid

def get_staff_summary(staff_id, hours=24):
    log_path = STAFF_LOG_DIR / f'{staff_id}.log'
    if not log_path.exists():
        return {'log_exists': False}
    since = datetime.now() - timedelta(hours=hours)
    count = {'INFO': 0, 'WARN': 0, 'ERROR': 0, 'SUCCESS': 0}
    for line in open(log_path):
        try:
            ts_str = line.split(']')[0].lstrip('[')
            ts = datetime.fromisoformat(ts_str)
            if ts < since:
                continue
            for level in count:
                if f'[{level}]' in line:
                    count[level] += 1
        except:
            pass
    return {'log_exists': True, 'last_24h': count}
