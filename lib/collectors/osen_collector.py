#!/usr/bin/env python3
"""OSEN entertainment scraper"""
import sys, re
sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from lib.collectors.korean_base import fetch_html, is_kpop_related, is_urgent, save_signals, make_signal, log


def collect():
    signals = []
    try:
        html = fetch_html('https://www.osen.co.kr/entertainment')
    except Exception as e:
        log(f"OSEN fetch error: {e}")
        return 0

    # OSENは1記事につき画像anchor + タイトルanchorの2連リンクを出す。
    # メインセクションは<strong>、サブセクションは<p class="txt">を使うため両対応
    patterns = [
        r'<a[^>]+href="(/article/[A-Z0-9]+)"[^>]*>\s*<strong>([^<]{5,200})</strong>',
        r'<a[^>]+href="(/article/[A-Z0-9]+)"[^>]*class="btn-txt"[^>]*>\s*<p[^>]*>([^<]{5,200})</p>',
    ]
    seen = set()
    for pat in patterns:
        for m in re.finditer(pat, html, re.DOTALL):
            path, title = m.group(1), m.group(2).strip()
            url = path if path.startswith('http') else 'https://www.osen.co.kr' + path
            if url in seen or len(title) < 5:
                continue
            seen.add(url)
            keywords = is_kpop_related(title)
            if not keywords:
                continue
            signals.append(make_signal('osen', title, url, keywords, is_urgent(title)))
            if len(signals) >= 30:
                break
        if len(signals) >= 30:
            break

    save_signals(signals, source_id='osen')
    urgent_cnt = sum(1 for s in signals if s['urgency'] == 'high')
    log(f"OSEN: {len(signals)} signals ({urgent_cnt} urgent)")
    return len(signals)


if __name__ == '__main__':
    collect()
