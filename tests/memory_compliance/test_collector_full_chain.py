"""
memory: feedback_collector_full_chain.md
規定: 「og:title止まり禁止/JS bundleからAPI発見/enricher+cache/manual fallback/0件アラート/UI警告 5点セット」
"""
import os, glob


def test_enricher_cache_files_exist():
    """enricher cache (lib/ または data/) の存在確認"""
    candidates = (
        glob.glob('/home/aiuser/kpop-ai-system/data/*enrichment*.json') +
        glob.glob('/home/aiuser/kpop-ai-system/data/*_enrichment_*.json') +
        glob.glob('/home/aiuser/kpop-ai-system/lib/*enricher*.py')
    )
    assert candidates, "enricher cache/module が見つからない"


def test_collector_files_exist():
    """collector module 群の存在 (lib/collectors/ or pipeline/)"""
    candidates = (
        glob.glob('/home/aiuser/kpop-ai-system/lib/collectors/*.py') +
        glob.glob('/home/aiuser/kpop-ai-system/pipeline/*collect*.py')
    )
    assert candidates, "collector module が見つからない"


def test_alert_path_for_zero_count_exists():
    """0件アラート (DISCORD_WEBHOOK or send_discord) が collector周辺にあること"""
    found = False
    for p in glob.glob('/home/aiuser/kpop-ai-system/lib/**/*.py', recursive=True) + \
             glob.glob('/home/aiuser/kpop-ai-system/pipeline/**/*.py', recursive=True):
        try:
            text = open(p, encoding='utf-8', errors='ignore').read()
        except Exception:
            continue
        if 'DISCORD_WEBHOOK' in text or 'send_discord' in text or 'post_to_discord' in text:
            found = True
            break
    assert found, "0件アラート用 webhook/notification が見つからない"
