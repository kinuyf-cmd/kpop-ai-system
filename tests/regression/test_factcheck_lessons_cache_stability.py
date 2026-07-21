"""factcheck の system prefix が呼び出し間で安定していることを保証する回帰テスト。

背景 (2026-07-21):
  lessons は 1日 100-180 件追加される。get_recent_lessons が「最新12件」を
  返す実装だったため、prompt に載る lessons が数分で総入れ替えになり、
  cache breakpoint を置いた system prefix (prefix+corpus+lessons ≒12.5k tok)
  が毎回 cache_write されていた。実測 cache_read/write は 0.17 まで悪化し、
  factcheck の cold write が API 費の 93% を占めた。

  修理: lessons を「日次スナップショット」に固定し、同一日内では
  バイト同一の文字列を返す。これにより system prefix が TTL 内で安定し
  cache_read hit する。
"""
import sys
from datetime import datetime, timedelta

sys.path.insert(0, '/home/aiuser/kpop-ai-system')

from lib.factcheck_lessons import (  # noqa: E402
    get_recent_lessons,
    format_lessons_for_prompt,
)


def _mk(ts: datetime, sev: str, title: str, issue: str) -> dict:
    return {
        'ts': ts.isoformat(),
        'severity': sev,
        'title': title,
        'issue': issue,
    }


def test_lessons_stable_within_same_day(tmp_path, monkeypatch):
    """同一日内で lessons が追加されても prompt 文字列がバイト同一であること。

    これが崩れると system prefix の cache が毎回 invalidate される。
    """
    import lib.factcheck_lessons as fl

    path = tmp_path / 'lessons.jsonl'
    now = datetime.now()
    base = [
        _mk(now - timedelta(days=2, hours=i), 'high', f'記事{i}', f'指摘{i}')
        for i in range(20)
    ]
    with open(path, 'w', encoding='utf-8') as f:
        for d in base:
            f.write(__import__('json').dumps(d, ensure_ascii=False) + '\n')
    monkeypatch.setattr(fl, 'LESSONS_PATH', path)

    before = format_lessons_for_prompt(get_recent_lessons())

    # 同じ日にさらに lessons が追加される (実運用では 1日 100件超)
    with open(path, 'a', encoding='utf-8') as f:
        for i in range(30):
            d = _mk(now, 'high', f'新記事{i}', f'新指摘{i}')
            f.write(__import__('json').dumps(d, ensure_ascii=False) + '\n')

    after = format_lessons_for_prompt(get_recent_lessons())

    assert before == after, (
        'lessons が同一日内で変化している = system prefix の prompt cache が '
        '毎回 invalidate され cold write 課金になる'
    )


def test_lessons_refresh_across_days(tmp_path, monkeypatch):
    """日付が変われば新しい lessons を取り込むこと (学習が止まらない)。"""
    import lib.factcheck_lessons as fl
    import json as _json

    path = tmp_path / 'lessons.jsonl'
    now = datetime.now()
    with open(path, 'w', encoding='utf-8') as f:
        for i in range(20):
            f.write(_json.dumps(
                _mk(now - timedelta(days=5, hours=i), 'high', f'旧{i}', f'旧指摘{i}'),
                ensure_ascii=False) + '\n')
    monkeypatch.setattr(fl, 'LESSONS_PATH', path)

    old = format_lessons_for_prompt(get_recent_lessons())
    assert '旧指摘' in old

    # 前日ぶん (= 当日除外の対象外) が積まれたら、翌日には取り込まれること。
    with open(path, 'a', encoding='utf-8') as f:
        for i in range(20):
            f.write(_json.dumps(
                _mk(now - timedelta(days=1), 'critical', f'新{i}', f'新指摘{i}'),
                ensure_ascii=False) + '\n')

    new = format_lessons_for_prompt(get_recent_lessons())
    assert new != old, 'critical な新規 lessons が翌日以降も反映されない'
    assert '新指摘' in new


def test_critical_lessons_are_prioritised(tmp_path, monkeypatch):
    """critical は high より古くても優先して prompt に載ること。

    旧実装は sort(key=(sev!='critical', ts), reverse=True) で reverse が
    第1キーにも効き、critical 優先が反転して critical が切り捨てられていた。
    """
    import lib.factcheck_lessons as fl
    import json as _json

    path = tmp_path / 'lessons.jsonl'
    now = datetime.now()
    with open(path, 'w', encoding='utf-8') as f:
        # 新しい high を大量に (max_count を埋めるだけの数)
        for i in range(30):
            f.write(_json.dumps(
                _mk(now - timedelta(days=1, minutes=i), 'high', f'high{i}', f'high指摘{i}'),
                ensure_ascii=False) + '\n')
        # 古い critical
        for i in range(3):
            f.write(_json.dumps(
                _mk(now - timedelta(days=10), 'critical', f'crit{i}', f'crit指摘{i}'),
                ensure_ascii=False) + '\n')
    monkeypatch.setattr(fl, 'LESSONS_PATH', path)

    got = get_recent_lessons(max_count=12)
    sevs = [l['severity'] for l in got]
    assert sevs[:3] == ['critical'] * 3, f'critical が優先されていない: {sevs}'


def test_lessons_respects_max_count(tmp_path, monkeypatch):
    """prompt 膨張防止の上限が効いていること。"""
    import lib.factcheck_lessons as fl
    import json as _json

    path = tmp_path / 'lessons.jsonl'
    now = datetime.now()
    with open(path, 'w', encoding='utf-8') as f:
        for i in range(200):
            f.write(_json.dumps(
                _mk(now - timedelta(days=3), 'high', f'記事{i}', f'指摘{i}'),
                ensure_ascii=False) + '\n')
    monkeypatch.setattr(fl, 'LESSONS_PATH', path)

    assert len(get_recent_lessons(max_count=12)) <= 12
