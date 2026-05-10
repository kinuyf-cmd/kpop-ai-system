#!/usr/bin/env python3
"""TopStarNews (topstarnews.net) scraper"""
import sys, re
sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from lib.collectors.korean_base import fetch_html, is_kpop_related, is_urgent, save_signals, make_signal, log


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
        path, title = m.group(1), re.sub(r'<[^>]+>', '', m.group(2)).strip()
        url = path if path.startswith('http') else 'https://www.topstarnews.net' + path
        # 2026-05-10: 連結タイトル除去 (kstyle同様の問題)
        # topstarnewsは記者名/日付/隣接記事タイトルが連結する場合がある
        title = re.sub(r'\s+', ' ', title)
        # 記者署名でカット (例: "기자\n전혜원 기자\n05.10")
        title = re.split(r'\s*\d{2}\.\d{2} \d{2}:\d{2}', title, 1)[0]
        title = re.split(r'\s+\S+ 기자(\s|$)', title, 1)[0]
        # 完結語で次記事を分離
        m_split = re.split(
            r'(?<=했다)|(?<=됐다)|(?<=했다고)|(?<=공개)|(?<=발매)|(?<=출연)|(?<=결정)|(?<=컴백)|(?<=합류)(?=[A-Z]|[가-힯])',
            title, maxsplit=1
        )
        if len(m_split) > 1 and len(m_split[0]) >= 10:
            title = m_split[0].strip()
        # 80字超は句読点で切断
        if len(title) > 80:
            for sep in ['…', '!', '?', '。', '．']:
                if sep in title[:80]:
                    title = title.split(sep, 1)[0] + sep
                    break
            else:
                title = title[:80]
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
