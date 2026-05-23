#!/usr/bin/env python3
"""Kstyle (kstyle.com) Japanese K-POP media scraper"""
import sys, re
sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from lib.collectors.korean_base import fetch_html, save_signals, log
from datetime import datetime

KPOP_KW_JP = [
    'K-POP', 'KPOP', 'BTS', 'BLACKPINK', 'aespa', 'NewJeans', 'SEVENTEEN', 'TWICE', 'IVE',
    'LE SSERAFIM', 'ILLIT', 'ITZY', 'Red Velvet', 'TXT', 'Stray Kids', 'ENHYPEN', 'NCT',
    'ATEEZ', 'TWS', 'KISS OF LIFE', 'IU', 'LISA', 'JENNIE', 'JISOO', 'HYBE', 'SM', 'YG', 'JYP',
    'カムバック', 'ライブ', 'ツアー', 'ファンミ', 'アルバム', '新曲', 'リリース',
]
URGENT_JP = ['速報', '緊急', '公式', '発表', '逮捕', '解散', '脱退', '訃報', '結婚', '熱愛']


def collect():
    signals = []
    try:
        html = fetch_html('https://www.kstyle.com/')
    except Exception as e:
        log(f"Kstyle fetch error: {e}")
        return 0

    pattern = re.compile(
        r'<a[^>]+href="([^"]*?article\.ksn\?[^"]*?)"[^>]*>\s*((?:<[^>]*>|[^<]){10,200})\s*</a>',
        re.DOTALL,
    )
    seen = set()
    for m in pattern.finditer(html):
        path, title = m.group(1), re.sub(r'<[^>]+>', '', m.group(2)).strip()
        url = path if path.startswith('http') else 'https://www.kstyle.com/' + path.lstrip('/')
        # 隣接記事タイトル/タイムスタンプ混入除去 (2026-05-08: 18765で発覚)
        # kstyleのリスト<a>は日付+次記事タイトルを内包する場合がある
        title = re.split(r'\s*\d{4}/\d{2}/\d{2}', title, 1)[0]
        title = re.split(r'【PHOTO】|【IMG】|【動画】|【写真】', title, 1)[0]
        title = re.sub(r'\s+', ' ', title).strip()
        # 2026-05-10: 複数記事タイトル連結の検出と切り捨て (18881事案で発覚)
        # 同一<a>内で複数記事ヘッドラインが連結 → 1記事目だけ採用
        # ヘッドライン終端パターン: 「決定！」「続く」「話題」「公開」「謝罪」など完結語の後ろを次記事と判定
        _multi_title_split = re.split(
            r'(?<=決定！)|(?<=続く)|(?<=話題)|(?<=公開)|(?<=謝罪)|(?<=判明)|(?<=開催)|(?<=出演)(?=[A-Z]|[ぁ-んァ-ヶ一-龥])',
            title, maxsplit=1
        )
        if len(_multi_title_split) > 1 and len(_multi_title_split[0]) >= 15:
            title = _multi_title_split[0].strip()
        # 80文字超の長すぎるタイトルは多重連結の可能性高 → 句読点で切る
        if len(title) > 80:
            for _sep in ['…', '！', '。', '？']:
                if _sep in title[:80]:
                    title = title.split(_sep, 1)[0] + _sep
                    break
            else:
                title = title[:80]
        if url in seen or len(title) < 5:
            continue
        seen.add(url)
        matched = [k for k in KPOP_KW_JP if k.lower() in title.lower()]
        if not matched:
            continue
        urgent = any(k in title for k in URGENT_JP)
        signals.append({
            'timestamp': datetime.now().isoformat(),
            'source': 'japanese_media',
            'source_id': 'kstyle',
            'keyword': matched[0],
            'title': title[:300],
            'url': url,
            'engagement_score': 3.0 if urgent else 2.0,
            'language': 'ja',
            'urgency': 'high' if urgent else 'normal',
            'raw_data': {'all_keywords': matched},
        })
        if len(signals) >= 20:
            break
    save_signals(signals)
    log(f"Kstyle: {len(signals)}")
    return len(signals)


if __name__ == '__main__':
    collect()
