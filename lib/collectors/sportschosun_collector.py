#!/usr/bin/env python3
"""Sports Chosun scraper"""
import sys, re
sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from lib.collectors.korean_base import fetch_html, is_kpop_related, is_urgent, save_signals, make_signal, log


def collect():
    signals = []
    try:
        html = fetch_html('https://sports.chosun.com/entertainment')
    except Exception as e:
        log(f"Sports Chosun fetch error: {e}")
        return 0

    patterns = [
        r'<a[^>]+href="(https://www\.sportschosun\.com/entertainment/[^"]+)"[^>]*>\s*((?:<[^>]*>|[^<]){10,200})\s*</a>',
        r'<a[^>]+href="(https://sports\.chosun\.com/entertainment/[^"]+)"[^>]*>\s*((?:<[^>]*>|[^<]){10,200})\s*</a>',
    ]
    seen = set()
    for pat in patterns:
        for m in re.finditer(pat, html, re.DOTALL):
            path, title = m.group(1), re.sub(r'<[^>]+>', '', m.group(2)).strip()
            url = path if path.startswith('http') else 'https://sports.chosun.com' + path
            if url in seen or len(title) < 5:
                continue
            seen.add(url)
            keywords = is_kpop_related(title)
            if not keywords:
                continue
            signals.append(make_signal('sports_chosun', title, url, keywords, is_urgent(title)))
            if len(signals) >= 20:
                break
        if len(signals) >= 20:
            break

    save_signals(signals)
    log(f"Sports Chosun: {len(signals)}")
    return len(signals)


if __name__ == '__main__':
    collect()
