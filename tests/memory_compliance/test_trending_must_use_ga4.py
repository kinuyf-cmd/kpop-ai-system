"""
memory: feedback_trending_must_use_ga4.md
規定: sidebar の「今日読まれている記事」は kpj_api_trending (GA4 metrics_yesterday.json
       ベース) 経由で表示する。WP_Query(orderby=comment_count) 直書きは禁止
       (KpopJournal はコメント機能未使用のため comment_count=0 が大半で
       「新着順と区別つかない」虚偽表示になる)。
"""
import os, re

SIDEBAR = '/home/aiuser/kpop-ai-system/wordpress/kpopjournal-theme/sidebar.php'
FUNCTIONS = '/home/aiuser/kpop-ai-system/wordpress/kpopjournal-theme/functions.php'


def test_sidebar_uses_kpj_api_trending():
    """sidebar.php が kpj_api_trending() 経由で trending を取得していること"""
    assert os.path.exists(SIDEBAR), f"sidebar.php 不在: {SIDEBAR}"
    src = open(SIDEBAR, encoding='utf-8').read()
    assert 'kpj_api_trending' in src, \
        "sidebar.php に kpj_api_trending 呼出が無い (GA4 trending 経路未使用)"


def _strip_php_comments(src: str) -> str:
    """PHP の // と /* */ コメントを除去 (regex 簡易版)。"""
    src = re.sub(r'/\*.*?\*/', '', src, flags=re.DOTALL)
    src = re.sub(r'//[^\n]*', '', src)
    return src


def test_sidebar_no_top_level_comment_count_orderby():
    """sidebar.php で orderby=comment_count を top-level (fallback以外) で使っていないこと

    具体的には: kpj_api_trending 経路の if ブロックを通る前に
    orderby=comment_count を使った WP_Query があれば NG。
    fallback (`if (empty($trending_posts))` 内) に出現するのは許容。
    PHP コメントは除去してから判定する。
    """
    src = _strip_php_comments(open(SIDEBAR, encoding='utf-8').read())
    m_api = re.search(r'kpj_api_trending', src)
    m_cc = re.search(r"orderby[\s'\"]*=>?[\s'\"]*comment_count", src)
    if m_cc:
        assert m_api and m_api.start() < m_cc.start(), \
            "sidebar.php で kpj_api_trending より前に orderby=comment_count が出現 (top-level 直書きは禁止)"


def test_functions_defines_kpj_api_trending():
    """functions.php に kpj_api_trending エンドポイント実装があること"""
    assert os.path.exists(FUNCTIONS), f"functions.php 不在: {FUNCTIONS}"
    src = open(FUNCTIONS, encoding='utf-8').read()
    assert re.search(r'function\s+kpj_api_trending\s*\(', src), \
        "functions.php に kpj_api_trending() 関数定義が無い"


def test_functions_kpj_api_trending_reads_ga4_top_landing_pages():
    """kpj_api_trending 内で metrics['ga4']['top_landing_pages'] を参照していること

    memo の「旧実装は list 形式期待で常に空扱い」を再発させない gate。
    """
    src = open(FUNCTIONS, encoding='utf-8').read()
    # 単純 substring チェック (PHPの配列アクセス記法を許容)
    assert "top_landing_pages" in src, \
        "functions.php に 'top_landing_pages' 参照が無い (GA4 metrics dict 経路を踏んでいない疑い)"
    assert "'ga4'" in src or '"ga4"' in src, \
        "functions.php に 'ga4' キー参照が無い (memo通りの dict 経路ではない可能性)"
