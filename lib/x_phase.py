"""X自動投稿の段階(Phase)状態。

2026-10-17 Phase3 開始時に新設。Phase をコード定数でなく状態ファイルで持つことで、
tools/x_auto_repause_guard.py が悪化を検知したときにコードを書き換えずに1段降格できる。

  2 = 記事帯のキュー経路は URL なし(traffic 経路の自己リプURLのみ。8/17 owner決定)
  3 = 記事帯(ARTICLE_HOURS)のキュー経路にも自己リプURLを付ける。本文は具体必須
"""
import json
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl

STATE_FILE = Path('/home/aiuser/kpop-ai-system/data/x_phase_state.json')
DEFAULT_PHASE = 2


def _load() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def get_phase() -> int:
    """現在の Phase。状態ファイルが無い/壊れている場合は安全側の Phase2。"""
    try:
        return int(_load().get('phase', DEFAULT_PHASE))
    except (TypeError, ValueError):
        return DEFAULT_PHASE


def set_phase(phase: int, reason: str) -> None:
    state = _load()
    history = state.get('history', [])
    history.append({'ts': datetime.now().isoformat(timespec='seconds'),
                    'from': state.get('phase'), 'to': phase, 'reason': reason})
    state.update({'phase': phase,
                  'since': datetime.now().isoformat(timespec='seconds'),
                  'history': history})
    # 非原子書き込みで0バイト化した前例があるため tmp+replace
    tmp = STATE_FILE.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp, STATE_FILE)


def with_utm(url: str, campaign: str) -> str:
    """X 由来の流入を GA4 で投稿経路別に数えるための UTM を付ける。"""
    if not url:
        return url
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query) if not k.startswith('utm_')]
    query += [('utm_source', 'x'), ('utm_medium', 'social'), ('utm_campaign', campaign)]
    return urlunsplit(parts._replace(query=urlencode(query)))
