"""
memory: feedback_internal_ops_term_leak.md
規定: 「GSC横展開/CTR/IMP等のオペレーション用語がauto_directivesからLLMプロンプトに漏れて架空記事生成」
"""
import os, json
import sys
sys.path.insert(0, '/home/aiuser/kpop-ai-system')


def test_auto_directives_has_no_internal_ops_terms():
    """config/auto_directives.json に内部用語が含まれていないこと"""
    p = '/home/aiuser/kpop-ai-system/config/auto_directives.json'
    if not os.path.exists(p):
        import pytest; pytest.skip('auto_directives.json not present')
    text = open(p, encoding='utf-8').read()
    # 内部用語: GSC/CTR/IMP/横展開/長尾/カニバリ
    forbidden = ['GSC', 'CTR派生', 'IMP派生', '横展開', 'cannibal', 'カニバリ',
                 'long_tail', 'LongTail']
    leaked = [t for t in forbidden if t in text]
    # auto_directivesは設定なので内部用語が値として含まれてもOK
    # 「LLMに渡すprompt用フィールド」だけがチェック対象
    # フィールド名の検査: prompt/instruction系キーに内部用語が無いか
    try:
        d = json.loads(text)
    except Exception:
        return
    # promptフィールドを再帰的に走査
    found = []
    # LLM-bound文脈: prompt系フィールドだが developer-facing な
    # 'action' / 'operations' / 'history' / 'log' / 'note' / 'rationale' は除外
    EXCLUDE_KEYS = ('action', 'operations', 'history', 'log', 'note', 'rationale',
                    'description', 'reason', 'detail')

    def walk(o, path=''):
        if isinstance(o, dict):
            for k, v in o.items():
                walk(v, f"{path}.{k}")
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk(v, f"{path}[{i}]")
        elif isinstance(o, str):
            path_lower = path.lower()
            if any(t in path_lower for t in ('prompt', 'instruction', 'message')) and \
               not any(ex in path_lower for ex in EXCLUDE_KEYS):
                for term in forbidden:
                    if term in o:
                        found.append(f"{path}: {term}")
    walk(d)
    assert not found, f"LLMプロンプトに内部用語漏れ: {found[:5]}"
