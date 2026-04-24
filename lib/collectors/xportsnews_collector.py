#!/usr/bin/env python3
"""Xports News (xportsnews.com) scraper"""
import sys, re
sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from lib.collectors.korean_base import fetch_html, is_kpop_related, is_urgent, save_signals, make_signal, log


def collect():
    signals = []
    try:
        html = fetch_html('https://www.xportsnews.com/?ac=article_list&cate_sub=3001')
    except Exception as e:
        log(f"Xports fetch error: {e}")
        return 0

    patterns = [
        r'<a[^>]+href="([^"]*?article_view[^"]*?)"[^>]*>\s*((?:<[^>]*>|[^<]){10,200})\s*</a>',
        r'<a[^>]+href="([^"]*?xportsnews\.com[^"]*?)"[^>]*>\s*((?:<[^>]*>|[^<]){10,200})\s*</a>',
    ]
    seen = set()
    for pat in patterns:
        for m in re.finditer(pat, html, re.DOTALL):
            path, title = m.group(1), re.sub(r'<[^>]+>', '', m.group(2)).strip()
            url = path if path.startswith('http') else 'https://www.xportsnews.com/' + path.lstrip('/')
            if url in seen or len(title) < 5:
                continue
            seen.add(url)
            kw = is_kpop_related(title)
            if not kw:
                continue
            signals.append(make_signal('xportsnews', title, url, kw, is_urgent(title)))
            if len(signals) >= 20:
                break
        if len(signals) >= 20:
            break
    save_signals(signals)
    log(f"Xports News: {len(signals)}")
    return len(signals)


if __name__ == '__main__':
    collect()
