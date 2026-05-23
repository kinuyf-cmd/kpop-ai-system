"""個別社員タスク管理"""
import json, uuid
from datetime import datetime

ROSTER_PATH = '/home/aiuser/kpop-ai-system/config/staff_roster.json'

def _load():
    return json.load(open(ROSTER_PATH))

def _save(r):
    json.dump(r, open(ROSTER_PATH, 'w'), ensure_ascii=False, indent=2)

def assign_task(staff_id, task_name, meta=None, priority='normal'):
    r = _load()
    s = r['individual_staff'].get(staff_id)
    if not s:
        return None
    task = {
        'task_id': str(uuid.uuid4())[:8], 'name': task_name,
        'meta': meta or {}, 'priority': priority,
        'assigned_at': datetime.now().isoformat(), 'status': 'queued',
    }
    s.setdefault('task_queue', []).append(task)
    _save(r)
    return task['task_id']

def begin_task(staff_id, task_name, meta=None):
    r = _load()
    s = r['individual_staff'].get(staff_id)
    if not s:
        return None
    task = {
        'task_id': str(uuid.uuid4())[:8], 'name': task_name,
        'meta': meta or {}, 'priority': 'normal',
        'assigned_at': datetime.now().isoformat(),
        'started_at': datetime.now().isoformat(), 'status': 'in_progress',
    }
    s.setdefault('task_queue', []).append(task)
    s['current_task'] = task['task_id']
    _save(r)
    return task['task_id']

def end_task(staff_id, task_id, status='success', result_meta=None):
    r = _load()
    s = r['individual_staff'].get(staff_id)
    if not s:
        return False
    for i, t in enumerate(s.get('task_queue', [])):
        if t.get('task_id') == task_id:
            t['status'] = status
            t['ended_at'] = datetime.now().isoformat()
            t['result'] = result_meta or {}
            if status == 'success':
                s.setdefault('completed_tasks', []).append(t)
                s['completed_tasks'] = s['completed_tasks'][-50:]
            else:
                s.setdefault('failed_tasks', []).append(t)
                s['failed_tasks'] = s['failed_tasks'][-30:]
            s['task_queue'].pop(i)
            break
    if s.get('current_task') == task_id:
        s['current_task'] = None
    _save(r)
    return True

def get_workload(staff_id):
    r = _load()
    s = r['individual_staff'].get(staff_id)
    if not s:
        return None
    return {
        'staff_id': staff_id, 'code_name': s.get('code_name'),
        'current_task': s.get('current_task'),
        'queue_size': len(s.get('task_queue', [])),
        'completed_total': len(s.get('completed_tasks', [])),
        'failed_total': len(s.get('failed_tasks', [])),
    }
