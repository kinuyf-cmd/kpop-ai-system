"""社員間メッセージング (横連携)

社員Aが社員Bに業務依頼する際、両方がpersonaベースで発言する。
"""
import os
import json
from openai import OpenAI
from lib.staff_persona import get_persona_prompt
from lib.staff_task_manager import assign_task
from lib.discord_client import post_as_staff


def staff_to_staff(from_staff_id, to_staff_id, task_description, channel_override=None):
    """社員Aが社員Bに業務依頼。両方が独立人格で発言する。

    Returns:
        dict with task_id, from, to
    """
    client = OpenAI()

    # A: 依頼発言
    a_persona = get_persona_prompt(from_staff_id) or f'あなたはKPOP JOURNAL社員 {from_staff_id} です。'
    a_prompt = f"""{a_persona}

あなたは {to_staff_id} の社員に以下の業務依頼をします。150字以内、簡潔、丁寧。
依頼内容: {task_description}"""
    try:
        a_r = client.chat.completions.create(
            model='gpt-4o-mini',
            messages=[{'role': 'user', 'content': a_prompt}],
            max_tokens=200,
        )
        a_msg = a_r.choices[0].message.content
        post_as_staff(from_staff_id, a_msg)
    except Exception:
        post_as_staff(from_staff_id, f'{to_staff_id} さんへ: {task_description[:100]}')

    # B: タスク受領 + 応答発言
    task_id = assign_task(to_staff_id, task_description, meta={'from': from_staff_id})

    b_persona = get_persona_prompt(to_staff_id) or f'あなたはKPOP JOURNAL社員 {to_staff_id} です。'
    b_prompt = f"""{b_persona}

{from_staff_id} 社員から以下の業務依頼を受けました。150字以内、簡潔。
依頼内容: {task_description}
タスクID: {task_id}
依頼者の専門領域も考慮して受領コメントを書いてください。"""
    try:
        b_r = client.chat.completions.create(
            model='gpt-4o-mini',
            messages=[{'role': 'user', 'content': b_prompt}],
            max_tokens=200,
        )
        b_msg = b_r.choices[0].message.content
        post_as_staff(to_staff_id, b_msg)
    except Exception:
        post_as_staff(to_staff_id, f'タスク {task_id} 受領しました。業務開始します。')

    return {'task_id': task_id, 'from': from_staff_id, 'to': to_staff_id}
