"""Anthropic API 呼び出しが必ず cost_ledger に計上されることを保証する回帰テスト。

背景 (2026-07-21):
  lib/thumbnail_relevance_audit.py と lib/body_enrich.py は client.messages.create を
  呼びながら log_usage() を呼んでいなかった。thumbnail_relevance_audit は日次 cron で
  稼働し 1,592 件の判定を実行済みだが、cost_ledger には 1 件も計上されていなかった。
  台帳が「全API費」を表していると誤認したままコスト分析すると、真因の切り分けを誤る。

  このテストは「messages.create を呼ぶモジュールは log_usage も呼ぶ」を静的に検査する。
"""
import ast
import sys
from pathlib import Path

import pytest

REPO = Path('/home/aiuser/kpop-ai-system')
LIB = REPO / 'lib'

# messages.create を呼ぶが計上が不要なモジュール (理由を明記すること)
EXEMPT = {
    # cost_guard 自身は docstring の使用例として messages.create を含むだけ
    'anthropic_cost_guard.py',
}


def _iter_lib_modules():
    for p in sorted(LIB.glob('*.py')):
        if p.name in EXEMPT:
            continue
        yield p


def _calls_messages_create(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == 'create':
                val = node.func.value
                # client.messages.create(...) の形を拾う
                if isinstance(val, ast.Attribute) and val.attr == 'messages':
                    return True
    return False


def _calls_log_usage(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name) and f.id == 'log_usage':
                return True
            if isinstance(f, ast.Attribute) and f.attr == 'log_usage':
                return True
    return False


@pytest.mark.parametrize('path', list(_iter_lib_modules()), ids=lambda p: p.name)
def test_api_calls_are_logged_to_cost_ledger(path):
    """messages.create を呼ぶモジュールは log_usage で cost_ledger に計上すること。"""
    tree = ast.parse(path.read_text(encoding='utf-8'))
    if not _calls_messages_create(tree):
        pytest.skip('no messages.create')
    assert _calls_log_usage(tree), (
        f'{path.name} は Anthropic API を呼ぶが log_usage() を呼んでいない。'
        ' cost_ledger に計上されず、コスト分析で見落とされる。'
    )
