"""記事末尾にカムバックカレンダーCTA + Artist Profile Wiki誘導を自動挿入

sticky page promotion + bounce下げ。/release-calendar/ + /artist-{slug}/ の
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


def inject_profile_inline_links(body_html: str) -> str:
    """本文中のartist名 (1度目出現) を /artist-{slug}/ へのlinkに変換。
    既存linkは触らない。同artistの2度目以降は変換しない (link spam防止)。"""
    if not body_html:
        return body_html

    # 既存 profile JSON が存在するartistのみ対象 (空page誘導防止)
    available_slugs = set()
    if PROFILE_DIR.exists():
        for p in PROFILE_DIR.glob('*.json'):
            available_slugs.add(p.stem)

    result = body_html
    used = set()
    # 長い名前から優先 (LE SSERAFIM > IVE 等の部分マッチ防止)
    for artist, slug in sorted(ARTIST_SLUG_MAP.items(), key=lambda x: -len(x[0])):
        if slug not in available_slugs or slug in used:
            continue
        # 既にlink内にあるartist名は触らない (negative lookbehind/ahead)
        # シンプルに: 最初の出現のみ置換、ただし既存<a>内は除外
        import re
        # \w境界で囲み、artist名がword一部にならないようにする
        # 韓国語/日本語の前後はOK ("BTSの" は match させたい)
        pattern = re.compile(r'(?<![A-Za-z0-9])' + re.escape(artist) + r'(?![A-Za-z0-9])')
        # 既存<a>...</a>を一時退避してからmatch
        anchor_re = re.compile(r'<a\b[^>]*>.*?</a>', re.DOTALL)
        anchors = []
        def _stash(m):
            anchors.append(m.group(0))
            return f'\x00ANCHOR{len(anchors)-1}\x00'
        stashed = anchor_re.sub(_stash, result)

        # 最初の1回のみlink化
        replaced_once = [False]
        def _link(m):
            if replaced_once[0]:
                return m.group(0)
            replaced_once[0] = True
            return f'<a href="/artist-{slug}/" rel="noopener">{m.group(0)}</a>'
        new_stashed = pattern.sub(_link, stashed, count=1)

        # anchor復元
        for i, a in enumerate(anchors):
            new_stashed = new_stashed.replace(f'\x00ANCHOR{i}\x00', a)
        if replaced_once[0]:
            used.add(slug)
            result = new_stashed
    return result


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

    # カレンダー全体リンクは存在しない /release-calendar/(404)を避け、
    # 稼働中のイベントカレンダー /events/ に統一(オーナー指示 2026-05-26)。
    cta_lines.append(
        '<p>K-POPの公式カムバック・ライブ・イベント情報をまとめています。'
        '<a href="https://www.kpopjournal.tokyo/events/" '
        'rel="noopener"><strong>イベントカレンダーを見る →</strong></a></p>'
    )

    # アーティスト詳細は Idol Wiki(/artists/{slug}/、稼働中)へ誘導。
    # 旧 /artist-{slug}/ は 404 だった([1]導線改善も兼ねる)。
    profile_slug = ARTIST_SLUG_MAP.get(artist)
    if profile_slug:
        cta_lines.append(
            f'<p>📖 <a href="https://www.kpopjournal.tokyo/artists/{profile_slug}/" '
            f'rel="noopener"><strong>{artist} のメンバー・所属事務所・公式SNSなど詳細プロフィール →</strong></a></p>'
        )

    cta_lines.append('</div>')

    return body_html + '\n' + '\n'.join(cta_lines)


if __name__ == '__main__':
    import sys
    artist = sys.argv[1] if len(sys.argv) > 1 else 'BTS'
    sample_body = '<p>サンプル記事本文</p>'
    print(maybe_inject_calendar_cta(sample_body, artist=artist))
