"""2026-05-12 修正: auto_comeback_article.py が headline 3本だけで GPT を呼んで
いた (source_reader / web_search 統合無し) ため、クラスタ偽陽性 + 本文未読の
ガベージインで捏造記事を量産していた問題の再発防止 test。

breaking_news_detector の publish_breaking と同じ source_reader + web_search
統合パターンに整合させた。
"""
import sys
sys.path.insert(0, '/home/aiuser/kpop-ai-system')


def test_auto_comeback_imports_source_reader():
    """auto_comeback_article.py が source_reader を呼んでいること"""
    src = open('/home/aiuser/kpop-ai-system/pipeline/auto_comeback_article.py').read()
    assert 'from lib.source_reader import read_sources' in src, \
        'source_reader 未統合 — ガベージイン再発リスク'
    assert 'read_sources(sigs)' in src, 'read_sources 呼び出し無し'


def test_auto_comeback_blocks_on_short_source_text():
    """source_text が 200字未満なら生成中止する分岐があること"""
    src = open('/home/aiuser/kpop-ai-system/pipeline/auto_comeback_article.py').read()
    assert "len(source_text) < 200" in src, '短ソース skip 分岐欠如'
    assert "捏造リスクで生成中止" in src, '捏造リスクメッセージ欠如'


def test_auto_comeback_artist_cluster_relevance_check():
    """artist 名がソース本文/タイトルに含まれない (cluster 偽陽性) を BLOCK"""
    src = open('/home/aiuser/kpop-ai-system/pipeline/auto_comeback_article.py').read()
    assert "クラスタ偽陽性" in src, 'cluster 偽陽性チェック欠如'


def test_auto_comeback_uses_web_search():
    """breaking_news_detector の _enrich_with_web_search を再利用"""
    src = open('/home/aiuser/kpop-ai-system/pipeline/auto_comeback_article.py').read()
    assert "_enrich_with_web_search" in src, 'web_search 未統合'


def test_auto_comeback_prompt_includes_source_body():
    """LLM プロンプトに「ソース記事本文」セクションが必須"""
    src = open('/home/aiuser/kpop-ai-system/pipeline/auto_comeback_article.py').read()
    assert "ソース記事本文" in src, 'プロンプトにソース本文未含'
    assert "ソース記事に書かれていない事実は絶対に追加しない" in src, '推測禁止指示欠如'
