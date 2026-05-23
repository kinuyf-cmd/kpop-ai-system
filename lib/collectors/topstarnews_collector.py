#!/usr/bin/env python3
"""TopStarNews (topstarnews.net) scraper"""
import sys, re
sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from lib.collectors.korean_base import fetch_html, is_kpop_related, is_urgent, save_signals, make_signal, log, clean_title


def collect():
    signals = []
    try:
        html = fetch_html('https://www.topstarnews.net/news/articleList.html?sc_section_code=S1N1')
    except Exception as e:
        log(f"TopStar fetch error: {e}")
        return 0

    pattern = re.compile(
        r'<a[^>]+href="([^"]*?articleView[^"]*?)"[^>]*>\s*((?:<[^>]*>|[^<]){10,200})\s*</a>',
        re.DOTALL,
    )
    seen = set()
    for m in pattern.finditer(html):
        path, title = m.group(1), clean_title(m.group(2))
        url = path if path.startswith('http') else 'https://www.topstarnews.net' + path
        # 2026-05-11: 連結タイトル除去 etc は korean_base.clean_title に共通化
        if url in seen or len(title) < 5:
            continue
        seen.add(url)
        kw = is_kpop_related(title)
        if not kw:
            continue
        signals.append(make_signal('topstarnews', title, url, kw, is_urgent(title)))
        if len(signals) >= 20:
            break
    save_signals(signals)
    log(f"TopStarNews: {len(signals)}")
    return len(signals)


if __name__ == '__main__':
    collect()
