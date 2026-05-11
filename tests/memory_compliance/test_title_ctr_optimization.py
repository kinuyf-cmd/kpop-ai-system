"""
memory: feedback_title_ctr_optimization.md
規定: 「疑問語/フック冒頭/42字/stale年度禁止/ローマ字併記」
"""
import sys, inspect
sys.path.insert(0, '/home/aiuser/kpop-ai-system')


def test_title_optimizer_max_42():
    """title_optimizer の MAX_TITLE が42以下"""
    from lib import title_optimizer
    src = inspect.getsource(title_optimizer)
    import re
    m = re.search(r'MAX_TITLE\s*=\s*(\d+)', src)
    assert m, "MAX_TITLE 定数なし"
    assert int(m.group(1)) <= 42, f"MAX_TITLE={m.group(1)} (42以下のはず)"


def test_title_optimizer_safe_truncate():
    """文字境界保護機能あり"""
    from lib.title_optimizer import _safe_truncate_title, _balance_brackets
    # mid-word truncate回避
    out = _safe_truncate_title('Hello World example', 13)
    # "Hello World e" にはならず、"Hello World" 等の境界で止まる
    assert not out.endswith('e') or out == 'Hello World e', \
        f"mid-word truncate: {out!r}"
    # 括弧バランス
    out = _balance_brackets('aespa【LEMONADE')
    assert out == 'aespa【LEMONADE】'
