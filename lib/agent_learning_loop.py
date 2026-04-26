#!/usr/bin/env python3
"""AI社員自動学習ループ
- docs/agent_lessons/{agent}.md から最新教訓を読み込み
- GPT生成時のプロンプトに「過去の失敗例」として自動注入
- 教訓追加→即座に次回生成に反映
"""
import re
from pathlib import Path
from collections import Counter
from datetime import datetime

LESSONS_DIR = Path('/home/aiuser/kpop-ai-system/docs/agent_lessons')


def get_recent_lessons(agent_name: str, top_n: int = 10) -> list[str]:
    """指定社員の最新教訓Top N件を取得"""
    f = LESSONS_DIR / f'{agent_name}.md'
    if not f.exists():
        return []
    lines = [l.strip() for l in f.read_text(encoding='utf-8').splitlines()
             if l.strip().startswith('-')]
    return lines[-top_n:]


def inject_lessons_to_prompt(agent_name: str, base_prompt: str) -> str:
    """システムプロンプトに教訓セクションを自動注入"""
    lessons = get_recent_lessons(agent_name, top_n=10)
    if not lessons:
        return base_prompt
    lesson_block = "\n\n## 過去の失敗例 (繰り返し禁止)\n" + "\n".join(lessons)
    lesson_block += "\n上記の失敗を繰り返さないこと。\n"
    return base_prompt + lesson_block


def add_lesson(agent_name: str, lesson: str, source: str = 'auto') -> bool:
    """新しい教訓を追加 (重複防止)"""
    f = LESSONS_DIR / f'{agent_name}.md'
    f.parent.mkdir(parents=True, exist_ok=True)
    existing = f.read_text(encoding='utf-8') if f.exists() else f'# {agent_name} 品質ログ\n\n'
    if lesson in existing:
        return False
    stamp = datetime.now().strftime('%Y-%m-%d')
    existing += f'- [{stamp}|{source}] {lesson}\n'
    f.write_text(existing, encoding='utf-8')
    return True


def detect_recurring_errors(agent_name: str, threshold: int = 3) -> list[tuple]:
    """頻出エラーパターン検出 (threshold回以上で返却)"""
    lessons = get_recent_lessons(agent_name, top_n=50)
    keywords = Counter()
    for l in lessons:
        for kw in re.findall(r'[a-zA-Z_]{4,}|[\u4e00-\u9fff]{2,}', l):
            keywords[kw] += 1
    return [(k, c) for k, c in keywords.most_common(20) if c >= threshold]
