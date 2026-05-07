#!/usr/bin/env python3
"""Newsen entertainment scraper"""
import sys, re
sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from lib.collectors.korean_base import fetch_html, is_kpop_related, is_urgent, save_signals, make_signal, log


def collect():
    signals = []
    try:
        import urllib.request
        req = urllib.request.Request('https://www.newsen.com/news_list.php?code=100600',
                                     headers={'User-Agent': 'Mozilla/5.0'})
        raw = urllib.request.urlopen(req, timeout=15).read()
        # Newsenは EUC-KR エンコーディング
        html = raw.decode('euc-kr', errors='ignore')
    except Exception as e:
        log(f"Newsen fetch error: {e}")
        return 0

    patterns = [
        r'<a[^>]+href="(\./news_view\.php\?uid=[^"]+)"[^>]*>((?:<[^>]*>|[^<]){5,200})</a>',
    ]
    seen = set()
    for pat in patterns:
        for m in re.finditer(pat, html, re.DOTALL):
            path, title = m.group(1), re.sub(r'<[^>]+>', '', m.group(2)).strip()
            url = path.replace('./', 'https://www.newsen.com/') if path.startswith('./') else (path if path.startswith('http') else 'https://www.newsen.com/' + path)
            if url in seen or len(title) < 5:
                continue
            seen.add(url)
            keywords = is_kpop_related(title)
            if not keywords:
                continue
            signals.append(make_signal('newsen', title, url, keywords, is_urgent(title)))
            if len(signals) >= 30:
                break
        if len(signals) >= 30:
            break

    save_signals(signals)
    urgent_cnt = sum(1 for s in signals if s['urgency'] == 'high')
    log(f"Newsen: {len(signals)} signals ({urgent_cnt} urgent)")
    return len(signals)


if __name__ == '__main__':
    collect()
