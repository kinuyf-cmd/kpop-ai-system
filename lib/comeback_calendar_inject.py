"""記事末尾にカムバックカレンダーCTA + Artist Profile Wiki誘導を自動挿入

sticky page promotion + bounce下げ。/comeback-calendar/ + /artist-{slug}/ の
2方向にinternal link流す。

統合方法 (unified_publisher内):
    from lib.comeback_calendar_inject import maybe_inject_calendar_cta
    body_html = maybe_inject_calendar_cta(body_html, artist=artist)
"""
from __future__ import annotations
import os
import json
from datetime import datetime
from pathlib import Path

CALENDAR_PATH = Path('/home/aiuser/kpop-ai-system/config/comeback_calendar_v2.json')
PROFILE_DIR = Path('/home/aiuser/kpop-ai-system/config/artist_profiles')

# artist名→slug map (profile page用)
ARTIST_SLUG_MAP = {
    'BTS': 'bts', 'BLACKPINK': 'blackpink', 'NewJeans': 'newjeans',
    'aespa': 'aespa', 'IVE': 'ive', 'LE SSERAFIM': 'le-sserafim',
    'ITZY': 'itzy', 'TWICE': 'twice', 'SEVENTEEN': 'seventeen',
    'Stray Kids': 'stray-kids', 'ENHYPEN': 'enhypen', 'TXT': 'txt',
    'NMIXX': 'nmixx', 'BABYMONSTER': 'babymonster', 'RIIZE': 'riize',
    'ILLIT': 'illit', 'BOYNEXTDOOR': 'boynextdoor',
    'KISS OF LIFE': 'kiss-of-life', 'IU': 'iu', 'KATSEYE': 'katseye',
}


def _get_recent_comebacks_for_artist(artist: str, limit: int = 3) -> list[dict]:
    """指定artistの今後 limit 件のcomeback情報を取得"""
    if not CALENDAR_PATH.exists():
        return []
    try:
        data = json.loads(CALENDAR_PATH.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError):
        return []
    artist_lower = (artist or '').lower()
    upcoming = []
    today_str = datetime.now().strftime('%Y-%m-%d')
    for cb in data.get('comebacks', []):
        if cb.get('release_date', '') < today_str:
            continue
        if artist_lower and artist_lower in cb.get('artist', '').lower():
            upcoming.append(cb)
    upcoming.sort(key=lambda x: x.get('release_date', '9999'))
    return upcoming[:limit]


def maybe_inject_calendar_cta(body_html: str, artist: str = '') -> str:
    """記事body末尾にカレンダーCTAを挿入。artistマッチがあれば該当行も表示"""
    cta_lines = [
        '<div class="comeback-calendar-cta" style="margin: 2em 0; padding: 1em; background: #fff8e1; border-left: 4px solid #ffc107;">',
        '<h3>📅 関連: K-POP カムバック・カレンダー</h3>',
    ]

    # artist専用の今後予定があれば表示
    relevant = _get_recent_comebacks_for_artist(artist, limit=3) if artist else []
    if relevant:
        cta_lines.append(f'<p><strong>{artist} の今後の予定</strong></p>')
        cta_lines.append('<ul>')
        for cb in relevant:
            date = cb.get('release_date', '')
            title = cb.get('title', '')
            type_label = {
                'album': '🎵 アルバム', 'single': '💿 シングル', 'mv': '🎬 MV',
                'tour': '🎤 ツアー', 'fanmeeting': '👥 ファンミ',
            }.get(cb.get('type', ''), '📌')
            cta_lines.append(f'<li>{date} — {type_label} {title}</li>')
        cta_lines.append('</ul>')

    cta_lines.append(
        '<p>K-POP主要22グループの今後90日の公式カムバック・リリース情報をまとめています。'
        '<a href="https://www.kpopjournal.tokyo/comeback-calendar/" '
        'target="_blank" rel="noopener"><strong>カレンダー全体を見る →</strong></a></p>'
    )

    # Artist profile page誘導 (/artist-{slug}/)
    profile_slug = ARTIST_SLUG_MAP.get(artist)
    if profile_slug and (PROFILE_DIR / f'{profile_slug}.json').exists():
        cta_lines.append(
            f'<p>📖 <a href="https://www.kpopjournal.tokyo/artist-{profile_slug}/" '
            f'target="_blank" rel="noopener"><strong>{artist} のメンバー・所属事務所・公式SNSなど詳細プロフィール →</strong></a></p>'
        )

    cta_lines.append('</div>')

    return body_html + '\n' + '\n'.join(cta_lines)


if __name__ == '__main__':
    import sys
    artist = sys.argv[1] if len(sys.argv) > 1 else 'BTS'
    sample_body = '<p>サンプル記事本文</p>'
    print(maybe_inject_calendar_cta(sample_body, artist=artist))
