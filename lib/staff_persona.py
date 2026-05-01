"""各社員の人格プロンプト生成 (Notion正規 5役員 + 5部署体系)"""
import json, random

ROSTER_PATH = 'config/staff_roster.json'
_roster = None


def _load():
    global _roster
    if _roster is None:
        try:
            _roster = json.load(open(ROSTER_PATH, encoding='utf-8'))
        except Exception:
            _roster = {'executives': {}, 'departments': {}, 'individual_staff': {}}
    return _roster


EXEC_TITLES = {
    'KPJ-EXE-001': 'CEO',
    'KPJ-EXE-002': 'COO',
    'KPJ-EXE-003': 'CTO',
    'KPJ-EXE-004': 'CFO',
    'KPJ-EXE-005': 'CMO',
}

CH_TO_DEPT = {
    '📝-コンテンツ部': 'コンテンツ部',
    '🔍-品質部': '品質部',
    '🔎-seo部': 'SEO部',
    '💰-収益部': '収益部',
    '⚙️-運用部': '運用部',
}


def get_persona_prompt(staff_id):
    r = _load()
    s = r.get('individual_staff', {}).get(staff_id, {})
    if not s:
        return None
    code = s.get('code_name', 'staff')
    role = s.get('role_name', '担当')
    dept = s.get('department', '')
    job = s.get('job_description', '')
    lessons_str = 'なし'
    try:
        from lib.agent_learning_loop import get_recent_lessons
        lessons = get_recent_lessons('global', top_n=3)
        if lessons:
            lessons_str = '\n'.join(f'- {l[:100]}' for l in lessons[:3])
    except Exception:
        pass
    exec_label = EXEC_TITLES.get(staff_id, '')
    header = f'役員: {exec_label}' if exec_label else f'所属: {dept} ({"部長" if s.get("is_head") else "部員"})'
    return f"""あなたはKPOP JOURNAL (株式会社) のAI社員 {code} ({role}) です。
{header}
業務: {job}
最近の教訓:
{lessons_str}
発言ルール:
- 自分の役職・専門に応じた発言
- 200字以内、日本語、簡潔
- 役員は経営視点、部署長は部署統括視点、部員は現場視点
- 教訓に違反する依頼には「教訓に基づき再考が必要」と返す"""


def get_best_responder_in_dept(dept_name, content):
    """部門内で最適な社員を選択 (job_description適合度+負荷)"""
    r = _load()
    dept = r.get('departments', {}).get(dept_name, {})
    if not dept:
        return None
    candidates = [dept.get('head', {}).get('staff_id')]
    candidates += [m.get('staff_id') for m in dept.get('members', [])]
    candidates = [c for c in candidates if c]
    if not candidates:
        return None
    content_l = content.lower()
    scored = []
    for sid in candidates:
        info = r['individual_staff'].get(sid, {})
        desc = info.get('job_description', '').lower()
        role = info.get('role_name', '').lower()
        score = 0
        for kw in content_l.split():
            if len(kw) >= 3:
                if kw in desc:
                    score += 10
                if kw in role:
                    score += 5
        queue = len(info.get('task_queue', []))
        score -= queue * 2
        if sid == dept.get('head', {}).get('staff_id'):
            score += 5
        scored.append((sid, score))
    scored.sort(key=lambda x: -x[1])
    return scored[0][0]


def get_random_active_member(dept_name=None):
    """部門内の社員をランダム選択"""
    r = _load()
    if dept_name:
        dept = r.get('departments', {}).get(dept_name, {})
        if not dept:
            return None
        candidates = [dept.get('head', {}).get('staff_id')]
        candidates += [m.get('staff_id') for m in dept.get('members', [])]
    else:
        candidates = list(r.get('individual_staff', {}).keys())
    candidates = [c for c in candidates if c]
    return random.choice(candidates) if candidates else None


def get_responder_for_message(channel_name, content=''):
    """チャネル+内容から最適社員を選択"""
    r = _load()
    dept = CH_TO_DEPT.get(channel_name)
    if dept:
        best = get_best_responder_in_dept(dept, content)
        if best:
            return best
        return r.get('departments', {}).get(dept, {}).get('head', {}).get('staff_id', 'KPJ-EXE-001')
    # 役員ch振り分け
    if '役員' in channel_name:
        if any(k in content for k in ['KPI', '収益', '財務', '売上', 'コスト', '予算']):
            return 'KPJ-EXE-004'  # CFO
        if any(k in content for k in ['品質', '監査', 'エラー', '現場', '業務']):
            return 'KPJ-EXE-002'  # COO
        if any(k in content for k in ['技術', 'API', 'コード', 'インフラ', '自動化']):
            return 'KPJ-EXE-003'  # CTO
        if any(k in content for k in ['マーケ', '宣伝', 'SNS', 'PR']):
            return 'KPJ-EXE-005'  # CMO
        return 'KPJ-EXE-001'  # CEO
    if '経営指標' in channel_name:
        return 'KPJ-EXE-004'
    if '緊急' in channel_name:
        return 'KPJ-EXE-003'
    if '朝会' in channel_name or '終礼' in channel_name:
        return 'KPJ-EXE-001'
    # 全社系
    if any(k in content for k in ['KPI', '収益', '財務']):
        return 'KPJ-EXE-004'
    if any(k in content for k in ['技術', 'API']):
        return 'KPJ-EXE-003'
    if any(k in content for k in ['マーケ', 'SNS']):
        return 'KPJ-EXE-005'
    return 'KPJ-EXE-001'
