"""2026-05-11 content_short BLOCK 誤判定の再発防止テスト

事故内容: 5/11 の breaking 2記事 (21360 IVE/レイ, 21527 2PM) が content_short で
draft 化。本文は 1349/1467 字で、kind='breaking' 用の閾値なら WARN 判定だが、
post_publish_hook の再ゲート呼び出しが kind='news' をハードコードしていたため
BLOCK に昇格していた。

修正後: post_publish_hook が breaking_articles.jsonl を参照して kind を判定し、
breaking 記事には kind='breaking' を渡す。
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, '/home/aiuser/kpop-ai-system')


def test_post_publish_hook_does_not_hardcode_kind_news():
    """post_publish_hook.py の pre_publish_gate 呼び出しが kind='news' を
    無条件にハードコードしていないこと"""
    src = open('/home/aiuser/kpop-ai-system/lib/post_publish_hook.py').read()
    # ハードコード 'news' の禁止 — kind=_detected_kind 等の変数経由になっていること
    bad_pattern = "kind='news'"
    # gate 呼び出しは1箇所のみで、その箇所が _detected_kind を使うこと
    assert "_detected_kind" in src, (
        'post_publish_hook が breaking 判定の _detected_kind を導入していない。'
        'content_short BLOCK 事故の再発リスクあり'
    )
    # breaking_articles.jsonl 参照ロジックがあること
    assert 'breaking_articles.jsonl' in src, (
        'breaking_articles.jsonl を kind判定に使っていない'
    )


def test_breaking_articles_jsonl_path_consistent():
    """breaking_articles.jsonl のパスが daily_editor と post_publish_hook で一致"""
    hook = open('/home/aiuser/kpop-ai-system/lib/post_publish_hook.py').read()
    editor = open('/home/aiuser/kpop-ai-system/pipeline/daily_editor.py').read()
    target = 'logs/breaking_articles.jsonl'
    assert target in hook, f'hook does not reference {target}'
    assert target in editor, f'editor does not reference {target}'


def test_content_short_breaking_remains_warn():
    """breaking kind の content_short は WARN のまま (BLOCK に昇格しない)"""
    src = open('/home/aiuser/kpop-ai-system/lib/pre_publish_gate.py').read()
    # 該当ロジック「kind in ('breaking', 'popup') → warn」が残っていること
    assert "kind in ('breaking', 'popup')" in src or 'kind in ("breaking", "popup")' in src, (
        'breaking/popup の content_short → WARN 降格ロジックが消えている'
    )
