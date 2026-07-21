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


def _neg_ts(ts: str) -> float:
    """ts を「新しいほど小さい」数値に変換 (昇順ソートで新着優先にするため)。

    パース不能な ts は最も古い扱い (+inf) にして末尾へ送る。
    """
    try:
        return -datetime.fromisoformat(ts).timestamp()
    except (TypeError, ValueError):
        return float('inf')


def get_recent_lessons(days: int = 30, max_count: int = MAX_LESSONS_IN_PROMPT) -> list[dict]:
    """最近 N日の教訓を取得 (factcheck prompt用)。

    2026-07-21 (コスト修理): 「当日ぶん」を除外した日次スナップショットを返す。

    旧実装は ts 降順で最新 max_count 件を返していた。lessons は 1日 100-180 件
    追加されるため、prompt に載る 12 件が数分で総入れ替えになり、この文字列を
    含む system prefix (prefix+corpus+lessons ≒12.5k tok) の prompt cache が
    呼び出しの度に invalidate されていた。実測 cache_read/write=0.17、
    cold write が factcheck API 費の 93% を占めた。

    当日ぶんを除外することで同一日内では母集合が不変になり、返り値がバイト同一
    になる (= cache hit)。翌日には前日ぶんが取り込まれるので学習は止まらない。
    """
    if not LESSONS_PATH.exists():
        return []
    now = datetime.now()
    cutoff = now - timedelta(days=days)
    # 当日 00:00 以降に追加されたぶんは「まだ確定していない」として除外し、
    # 同一日内で母集合が変化しないようにする (prompt cache 安定化)。
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    lessons = []
    try:
        with open(LESSONS_PATH, encoding='utf-8') as f:
            for line in f:
                try:
                    d = json.loads(line)
                    ts = datetime.fromisoformat(d.get('ts', ''))
                    if cutoff <= ts < today_start:
                        lessons.append(d)
                except (json.JSONDecodeError, ValueError):
                    continue
    except OSError:
        return []
    # critical 優先 + 新しい順。
    # 注 (2026-07-21): 旧実装は `key=(severity!='critical', ts), reverse=True` で、
    # reverse が第1キーにも効くため critical(False) が末尾に回り、critical 優先が
    # 反転していた。severity は昇順・ts は降順と向きが違うので reverse は使わず、
    # ts は文字列の補数化ではなく個別キーで表現する。
    # ts 同着でも順序が揺れないよう title を tiebreak に入れ、同一入力に対して
    # 決定的な並びを保証する (prompt cache 安定性のため)。
    lessons.sort(key=lambda x: (x.get('title', ''),))
    lessons.sort(
        key=lambda x: (x['severity'] != 'critical', _neg_ts(x.get('ts', ''))),
    )
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
