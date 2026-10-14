"""速報の対象絞り込み(2026-10-14 owner決定)の回帰テスト。

- 主要アーティスト一覧(config/breaking_priority_artists.json)に入る対象は通す
- 一覧外は、タイトルが日本に関わる話題のときだけ通す
- 純韓国エンタメ(hallyu)は日本に関わる話題のときだけ、上限は当日の公開実績で数える
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pipeline.breaking_news_detector as bnd  # noqa: E402


def _sig(title, url, eng=3.0, src='osen'):
    return {'title': title, 'url': url, 'engagement_score': eng, 'source_id': src}


def _patch(monkeypatch, tmp_path, log_lines=()):
    log = tmp_path / 'breaking.jsonl'
    log.write_text(''.join(json.dumps(x, ensure_ascii=False) + '\n' for x in log_lines), encoding='utf-8')
    monkeypatch.setattr(bnd, 'BREAKING_LOG', str(log))
    monkeypatch.setattr(bnd, 'is_processed', lambda url: False)
    monkeypatch.setattr(bnd, '_is_stale_source', lambda s: False)


def test_priority_artist_passes(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    c = bnd.detect_breaking([_sig('세븐틴, 새 앨범 발매 확정', 'u1')])
    assert [x[0] for x in c] == ['세븐틴']


def test_member_alias_maps_to_priority_group(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    assert bnd._priority_ok('셔누', '셔누, 솔로 앨범 발매')
    assert bnd._priority_ok('지드래곤', '지드래곤, 신곡 공개')


def test_non_priority_artist_dropped(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    c = bnd.detect_breaking([_sig('에이핑크, 15주년 콘서트 개최', 'u2')])
    assert c == []


def test_non_priority_artist_with_japan_topic_passes(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    c = bnd.detect_breaking([_sig('에이핑크, 일본 도쿄 콘서트 개최', 'u3')])
    assert [x[0] for x in c] == ['에이핑크']


def test_hallyu_requires_japan_topic(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    assert bnd.detect_breaking([_sig('김구라, 아들 근황 공개', 'u4')]) == []
    c = bnd.detect_breaking([_sig('김구라, 일본 예능 출연', 'u5')])
    assert [(x[0], x[2]) for x in c] == [('김구라', 'hallyu')]


def test_hallyu_daily_cap_counts_published_today(monkeypatch, tmp_path):
    today = bnd.datetime.now().strftime('%Y-%m-%d')
    done = [{'date': today, 'type': 'hallyu', 'status': 'publish', 'artist': f'x{i}'}
            for i in range(bnd.HALLYU_LIMIT)]
    _patch(monkeypatch, tmp_path, done)
    assert bnd.detect_breaking([_sig('김구라, 일본 예능 출연', 'u6')]) == []


def test_hallyu_cap_ignores_yesterday_and_skipped(monkeypatch, tmp_path):
    today = bnd.datetime.now().strftime('%Y-%m-%d')
    lines = [{'date': '2000-01-01', 'type': 'hallyu', 'status': 'publish'}] * 5
    lines += [{'date': today, 'type': 'hallyu', 'status': 'skipped'}] * 5
    _patch(monkeypatch, tmp_path, lines)
    assert bnd._hallyu_published_today() == 0
