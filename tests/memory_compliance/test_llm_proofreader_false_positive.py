"""
memory: feedback_llm_proofreader_false_positive.md
規定: 「列挙文/所属関係/メタ情報をfact扱いしない明示」
"""
import sys
sys.path.insert(0, '/home/aiuser/kpop-ai-system')


def test_proofreader_prompt_excludes_list_enumeration():
    """llm_proofreader プロンプトに「グループ名の列挙はメンバー数誤りでない」明示があること"""
    import inspect
    from pipeline import llm_proofreader
    src = inspect.getsource(llm_proofreader)
    # 列挙関連のexclusion文言
    assert ('列挙' in src and 'メンバー数誤り' in src) or \
           ('TWICE' in src and 'X人' in src), \
           "プロンプトに列挙文exclusionの記述なし"


def test_proofreader_prompt_excludes_metric_comparison():
    """異指標数値併記を矛盾扱いしない明示があること (2026-05-10追加)"""
    import inspect
    from pipeline import llm_proofreader
    src = inspect.getsource(llm_proofreader)
    assert '異なる指標' in src or '比較対象が違う' in src or '首都圏' in src, \
        "プロンプトに比較指標exclusionの記述なし"


def test_proofreader_prompt_excludes_affiliation():
    """所属関係 (JYP所属のTWICE等) を事実関係として処理する明示があること"""
    import inspect
    from pipeline import llm_proofreader
    src = inspect.getsource(llm_proofreader)
    assert '所属' in src or 'JYP' in src or 'HYBE' in src, \
        "プロンプトに所属関係扱いの記述なし"
