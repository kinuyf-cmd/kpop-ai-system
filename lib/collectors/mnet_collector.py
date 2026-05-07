#!/usr/bin/env python3
"""Mnet (엠넷) entertainment/music show scraper"""
import sys, re
sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from lib.collectors.korean_base import fetch_html, is_kpop_related, is_urgent, save_signals, make_signal, log


def collect():
    signals = []

    # Mnet関連: M COUNTDOWN / MAMA 等の音楽番組情報
    # mnet.com はSSL問題があるため、Soompi/AllkpopのMnet関連記事を収集
    import ssl
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    # Mnet公式サイトはアクセス不可のため、M COUNTDOWN関連ニュースを韓国メディアから収集
    urls = [
        'https://search.naver.com/search.naver?where=news&query=M+COUNTDOWN+%EC%97%A0%EC%B9%B4%EC%9A%B4%ED%8A%B8%EB%8B%A4%EC%9A%B4',
        'https://search.naver.com/search.naver?where=news&query=Mnet+%EC%97%A0%EB%84%B7+%EC%BC%80%EC%9D%B4%ED%8C%9D',
    ]

    for base_url in urls:
        try:
            import urllib.request
            req = urllib.request.Request(base_url, headers={'User-Agent': 'Mozilla/5.0'})
            html = urllib.request.urlopen(req, timeout=15, context=ctx).read().decode('utf-8', errors='ignore')
        except Exception as e:
            log(f"Mnet fetch error ({base_url}): {e}")
            continue

        patterns = [
            r'<a[^>]+href="([^"]*(?:news|article|program)[^"]*)"[^>]*>\s*((?:<[^>]*>|[^<]){10,200})\s*</a>',
        ]
        seen = set()
        for pat in patterns:
            for m in re.finditer(pat, html, re.DOTALL):
                path, title = m.group(1), re.sub(r'<[^>]+>', '', m.group(2)).strip()
                if path.startswith('/'):
                    domain = base_url.split('/')[2]
                    url = f'https://{domain}{path}'
                elif path.startswith('http'):
                    url = path
                else:
                    continue
                if url in seen or len(title) < 5:
                    continue
                seen.add(url)
                keywords = is_kpop_related(title)
                if not keywords:
                    continue
                signals.append(make_signal('mnet', title, url, keywords, is_urgent(title)))
                if len(signals) >= 20:
                    break

    save_signals(signals)
    urgent_cnt = sum(1 for s in signals if s['urgency'] == 'high')
    log(f"Mnet: {len(signals)} signals ({urgent_cnt} urgent)")
    return len(signals)


if __name__ == '__main__':
    collect()
