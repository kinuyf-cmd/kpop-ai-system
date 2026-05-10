"""factcheck 自己学習 — Lessons learned (2026-05-10)

factcheck v2 で検出した critical/high issue を「教訓」として蓄積し、
将来のfactcheck呼び出し時に prompt に注入する。これによりシステムは
過去の事例から学習し、同種の事実誤りを早期検出できるようになる。

例: 「○○視聴率」誤記検出 → 教訓として「視聴率データは年齢層も確認」
将来BLACKPINK視聴率記事が来た時 → この教訓が prompt に入って事前チェック

データ構造 (data/factcheck_lessons.jsonl):
{
    "ts": "2026-05-10T15:00:00",
    "post_id": 19623,
    "title": "IU視聴率自己最高更新",
    "severity": "high",
    "issue": "2049視聴率→実は2054視聴率",
    "category": "数字/統計指標",
    "pattern": "視聴率の年齢層レンジ"
}
"""
from __future__ import annotations
import os
import json
from datetime import datetime, timedelta
from pathlib import Path

LESSONS_PATH = Path('/home/aiuser/kpop-ai-system/data/factcheck_lessons.jsonl')
MAX_LESSONS_IN_PROMPT = 12  # prompt膨張防止


def append_lessons(post_id: int, title: str, result: dict) -> None:
    """factcheck v2の結果から critical/high issue を教訓として蓄積"""
    issues_to_log = []
    for severity in ('critical', 'high'):
        for issue in result.get(severity, []):
            issues_to_log.append({'severity': severity, 'issue': issue})
    if not issues_to_log:
        return
    LESSONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LESSONS_PATH, 'a', encoding='utf-8') as f:
        for it in issues_to_log:
            f.write(json.dumps({
                'ts': datetime.now().isoformat(),
                'post_id': post_id,
                'title': title[:80],
                'severity': it['severity'],
                'issue': it['issue'][:300],
            }, ensure_ascii=False) + '\n')


def get_recent_lessons(days: int = 30, max_count: int = MAX_LESSONS_IN_PROMPT) -> list[dict]:
    """最近 N日の教訓を取得 (factcheck prompt用)"""
    if not LESSONS_PATH.exists():
        return []
    cutoff = datetime.now() - timedelta(days=days)
    lessons = []
    try:
        with open(LESSONS_PATH, encoding='utf-8') as f:
            for line in f:
                try:
                    d = json.loads(line)
                    ts = datetime.fromisoformat(d.get('ts', ''))
                    if ts >= cutoff:
                        lessons.append(d)
                except (json.JSONDecodeError, ValueError):
                    continue
    except OSError:
        return []
    # 最新を優先 + critical優先
    lessons.sort(key=lambda x: (x['severity'] != 'critical', x['ts']), reverse=True)
    return lessons[:max_count]


def format_lessons_for_prompt(lessons: list[dict]) -> str:
    """教訓を prompt に挿入できるテキストに整形"""
    if not lessons:
        return ''
    lines = ['## 過去の検出事例 (これらに類似するパターンがあれば再検出してください)']
    for l in lessons:
        sev = '🔴' if l['severity'] == 'critical' else '🟡'
        lines.append(f"  {sev} [{l['title'][:40]}]: {l['issue'][:150]}")
    return '\n'.join(lines)


if __name__ == '__main__':
    # Test: list recent lessons
    lessons = get_recent_lessons()
    print(f"Recent lessons ({len(lessons)}):")
    print(format_lessons_for_prompt(lessons))
