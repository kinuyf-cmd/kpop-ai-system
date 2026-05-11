"""
memory: feedback_llm_prompt_date_context.md
規定: 「LLM記事生成プロンプトには必ず現在日付+年月明記指示を入れる」
"""
import sys, inspect
sys.path.insert(0, '/home/aiuser/kpop-ai-system')


def test_proofreader_prompt_includes_today():
    """llm_proofreader が現在日付をプロンプトに注入していること"""
    from pipeline import llm_proofreader
    src = inspect.getsource(llm_proofreader)
    assert "今日の日付" in src and "datetime.now" in src, \
        "proofreader プロンプトに 'today' 注入が見つからない"


def test_translator_uses_2026_date():
    """translator が現在年(2026)以降のdate concept を扱えること"""
    from pipeline import llm_proofreader
    src = inspect.getsource(llm_proofreader)
    # 「2026年やそれ以降の日付は正常」の言及
    assert '2026年' in src and ('未来' in src or '正常' in src), \
        "future date OK 明示が proofreader プロンプトに無い"
