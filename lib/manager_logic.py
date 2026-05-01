"""部門長タスク配分ロジック"""
import json
from lib.staff_task_manager import assign_task, get_workload

ROSTER_PATH = '/home/aiuser/kpop-ai-system/config/staff_roster.json'

def _load():
    return json.load(open(ROSTER_PATH))

def get_subordinates(manager_staff_id):
    r = _load()
    for dept in r['departments'].values():
        if dept['head'].get('staff_id') == manager_staff_id:
            return [m['staff_id'] for m in dept['members']]
    return []

def delegate_to_subordinate(manager_id, task_name, meta=None):
    subs = get_subordinates(manager_id)
    if not subs:
        return assign_task(manager_id, task_name, meta)
    # Pick subordinate with lowest queue
    best = min(subs, key=lambda sid: (get_workload(sid) or {}).get('queue_size', 99))
    return assign_task(best, task_name, meta)
