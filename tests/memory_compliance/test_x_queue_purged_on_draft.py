"""
2026-05-11: post_publish_hook で記事を draft 化する際に x_post_queue から
該当 pid を除去していなかったため、x_scheduler が15分毎に
"WP not-publish — skip" を吐き続けるループ事故が発生 (直近1h で 6/7件)。

memory: feedback_recurrence_prevention.md (4層: 設定JSON+共通lib+学習対象+error_patterns)
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, '/home/aiuser/kpop-ai-system')


def _make_queue(tmp_path: Path, pids: list[int]) -> Path:
    p = tmp_path / 'x_post_queue.json'
    p.write_text(json.dumps({
        'updated': '2026-05-11 09:00',
        'count': len(pids),
        'queue': [
            {'title': f't{i}', 'url': f'https://example.com/{i}',
             'post_id': pid, 'genre': '', 'artist': '', 'priority': 'normal',
             'queued_at': '2026-05-11T09:00:00'}
            for i, pid in enumerate(pids)
        ],
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    return p


def test_purge_existing_pid_returns_count_and_writes_new_queue(tmp_path, monkeypatch):
    """existing pid を渡すと removed > 0、queue から消えていること"""
    import lib.post_publish_hook as hook
    qpath = _make_queue(tmp_path, [100, 200, 300])
    monkeypatch.setattr(hook, 'X_QUEUE_PATH', str(qpath))

    removed = hook._purge_from_x_queue(200)
    assert removed == 1, f'除去件数1のはず: {removed}'

    after = json.loads(qpath.read_text())
    pids_after = [e['post_id'] for e in after['queue']]
    assert pids_after == [100, 300]
    assert after['count'] == 2


def test_purge_nonexistent_pid_returns_zero(tmp_path, monkeypatch):
    """存在しないpidなら removed=0、queue 不変"""
    import lib.post_publish_hook as hook
    qpath = _make_queue(tmp_path, [100, 200])
    monkeypatch.setattr(hook, 'X_QUEUE_PATH', str(qpath))

    removed = hook._purge_from_x_queue(99999)
    assert removed == 0

    after = json.loads(qpath.read_text())
    assert [e['post_id'] for e in after['queue']] == [100, 200]


def test_purge_handles_missing_queue_file(tmp_path, monkeypatch):
    """queue file 不在時は例外を出さず 0 返す"""
    import lib.post_publish_hook as hook
    monkeypatch.setattr(hook, 'X_QUEUE_PATH', str(tmp_path / 'nonexistent.json'))
    assert hook._purge_from_x_queue(123) == 0
