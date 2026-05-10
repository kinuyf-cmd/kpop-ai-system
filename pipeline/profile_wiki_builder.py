#!/usr/bin/env python3
"""K-POP Artist Profile Wiki Builder

各アーティストの公式profile情報を Claude Web search で集約し、
固定page /artist/{slug}/ として WordPress に publish。

設計:
- 1 artist あたり 1 API call (Claude Sonnet 4.6 + web_search max=5)
- 取得項目: agency, debut_date, fandom_name, members[], official_links, discography hits
- output: config/artist_profiles/{slug}.json
- HTML render → WP page (slug=artist-{slug})
- 既存 fromis9.json schema と互換 (members項目を流用)

実行:
    python3 pipeline/profile_wiki_builder.py             # 全artist
    python3 pipeline/profile_wiki_builder.py BTS aespa   # 指定artistのみ

Cron (weekly refresh):
    0 6 * * 0 cd /home/aiuser/kpop-ai-system && python3 pipeline/profile_wiki_builder.py
"""
from __future__ import annotations
import os
import sys
import json
import urllib.request
import base64
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, '/home/aiuser/kpop-ai-system')
import anthropic
from dotenv import load_dotenv
load_dotenv('/home/aiuser/kpop-ai-system/.env')

PROFILE_DIR = Path('/home/aiuser/kpop-ai-system/config/artist_profiles')
WP_USER = os.getenv('WP_USER', '')
WP_PASS = os.getenv('WP_PASS', '')
AUTH = base64.b64encode(f"{WP_USER}:{WP_PASS}".encode()).decode()
JST = timezone(timedelta(hours=9))

# 初回構築対象 (PV最大化に効く主要グループから)
PRIORITY_ARTISTS = [
    {'name': 'BTS', 'slug': 'bts'},
    {'name': 'BLACKPINK', 'slug': 'blackpink'},
    {'name': 'NewJeans', 'slug': 'newjeans'},
    {'name': 'aespa', 'slug': 'aespa'},
    {'name': 'IVE', 'slug': 'ive'},
    {'name': 'LE SSERAFIM', 'slug': 'le-sserafim'},
    {'name': 'ITZY', 'slug': 'itzy'},
    {'name': 'TWICE', 'slug': 'twice'},
    {'name': 'SEVENTEEN', 'slug': 'seventeen'},
    {'name': 'Stray Kids', 'slug': 'stray-kids'},
    {'name': 'ENHYPEN', 'slug': 'enhypen'},
    {'name': 'TXT', 'slug': 'txt'},
    {'name': 'NMIXX', 'slug': 'nmixx'},
    {'name': 'BABYMONSTER', 'slug': 'babymonster'},
    {'name': 'RIIZE', 'slug': 'riize'},
    {'name': 'ILLIT', 'slug': 'illit'},
    {'name': 'BOYNEXTDOOR', 'slug': 'boynextdoor'},
    {'name': 'KISS OF LIFE', 'slug': 'kiss-of-life'},
    {'name': 'IU', 'slug': 'iu'},
    {'name': 'KATSEYE', 'slug': 'katseye'},
]

PROFILE_SCHEMA = {
    "type": "object",
    "properties": {
        "agency": {"type": "string"},
        "debut_date": {"type": "string"},
        "fandom_name": {"type": "string"},
        "fandom_meaning": {"type": "string"},
        "members": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name_en": {"type": "string"},
                    "name_kr": {"type": "string"},
                    "name_ja": {"type": "string"},
                    "real_name_en": {"type": "string"},
                    "position": {"type": "string"},
                    "birth": {"type": "string"},
                    "nationality": {"type": "string"},
                    "note": {"type": "string"},
                },
                "required": ["name_en", "position", "birth"],
                "additionalProperties": False,
            }
        },
        "discography_highlights": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "year": {"type": "string"},
                    "title": {"type": "string"},
                    "type": {"type": "string", "enum": ["album", "ep", "single", "japanese", "ost"]},
                    "note": {"type": "string"},
                },
                "required": ["year", "title", "type"],
                "additionalProperties": False,
            }
        },
        "official_links": {
            "type": "object",
            "properties": {
                "twitter": {"type": "string"},
                "instagram": {"type": "string"},
                "weverse": {"type": "string"},
                "youtube": {"type": "string"},
                "tiktok": {"type": "string"},
                "japan_official": {"type": "string"},
            },
            "additionalProperties": False,
        },
        "summary_ja": {"type": "string"},
    },
    "required": ["agency", "debut_date", "members", "summary_ja"],
    "additionalProperties": False,
}


def fetch_profile(client, artist: str, timeout_s: int = 180) -> dict:
    today = datetime.now(JST).strftime('%Y-%m-%d')
    prompt = f"""今日: {today}
K-POP アーティスト「{artist}」の包括的プロフィールを web_search で集約してください。

検索クエリ例:
- "{artist} members profile site:wikipedia.org"
- "{artist} official Twitter Instagram"
- "{artist} discography 2026"

必要項目:
1. agency (所属事務所、英語表記)
2. debut_date (YYYY-MM-DD形式)
3. fandom_name (公式ファンダム名)
4. fandom_meaning (名前の由来 — 日本語で1-2文)
5. members[]: 全メンバー
   - name_en (Romanized stage name): 例 "Karina"
   - name_kr (한글 본명): 例 "유지민"
   - name_ja (カタカナ): 例 "カリナ"
   - real_name_en (Romanized real name): 例 "Yu Jimin"
   - position: 例 "リーダー、メインボーカル"
   - birth (YYYY-MM-DD)
   - nationality (例: 韓国/日本/中国/米国)
   - note (任意の補足)
6. discography_highlights[]: 代表作 5-10件 (年/title/type)
7. official_links: 公式SNS URL (twitter/instagram/weverse/youtube/tiktok/japan_official)
8. summary_ja: 200-300字でグループ概要 (日本語、ファン向けの読み応えある文章)

ソロアーティストの場合は members に1人だけ入れる。
"""
    use_web_search = os.getenv('PROFILE_USE_WEBSEARCH') == '1'

    try:
        import httpx
        timeout_client = anthropic.Anthropic(timeout=httpx.Timeout(timeout_s, connect=10.0))
        kwargs = {
            'model': 'claude-sonnet-4-6',
            'max_tokens': 4500,
            'output_config': {"format": {"type": "json_schema", "schema": PROFILE_SCHEMA}},
            'messages': [{"role": "user", "content": prompt}],
        }
        if use_web_search:
            kwargs['tools'] = [{"type": "web_search_20260209", "name": "web_search", "max_uses": 3}]
        response = timeout_client.messages.create(**kwargs)
        text = next((b.text for b in response.content if b.type == 'text'), '{}')
        return json.loads(text)
    except Exception as e:
        print(f"  err: {type(e).__name__}: {str(e)[:200]}", flush=True)
        return {}


def _build_schema_org(artist: str, profile: dict) -> str:
    """Schema.org MusicGroup JSON-LD (Google rich snippets用)"""
    members = profile.get('members', []) or []
    same_as = []
    for k in ['twitter', 'instagram', 'weverse', 'youtube', 'tiktok']:
        v = (profile.get('official_links') or {}).get(k)
        if v: same_as.append(v)

    schema = {
        "@context": "https://schema.org",
        "@type": "MusicGroup" if len(members) > 1 else "Person",
        "name": artist,
        "url": f"https://www.kpopjournal.tokyo/artist-{artist.lower().replace(' ', '-')}/",
    }
    if profile.get('debut_date'):
        schema["foundingDate"] = profile['debut_date']
    if profile.get('agency'):
        schema["recordLabel"] = profile['agency']
    if same_as:
        schema["sameAs"] = same_as
    if len(members) > 1:
        schema["member"] = [
            {
                "@type": "Person",
                "name": (m.get('name_en') or m.get('name_ja','')).strip(),
                "alternateName": m.get('name_kr','') or m.get('name_ja',''),
            }
            for m in members if (m.get('name_en') or m.get('name_ja',''))
        ]
    return f'<script type="application/ld+json">{json.dumps(schema, ensure_ascii=False)}</script>'


_GRAD_POOL = [
    ('#FF1493', '#FF6B9D'), ('#9B59B6', '#6C5CE7'), ('#00BCD4', '#2196F3'),
    ('#FF6B9D', '#FF8A65'), ('#E91E63', '#FF1493'), ('#26A69A', '#00897B'),
    ('#FFB300', '#FF8F00'), ('#AB47BC', '#9B59B6'), ('#42A5F5', '#00BCD4'),
    ('#EC407A', '#FF1493'),
]


def _calc_age(birth_str: str) -> str:
    """YYYY-MM-DD → 年齢"""
    try:
        bd = datetime.strptime(birth_str[:10], '%Y-%m-%d')
        today = datetime.now()
        age = today.year - bd.year - ((today.month, today.day) < (bd.month, bd.day))
        return str(age)
    except Exception:
        return ''


def _format_birth(birth_str: str) -> str:
    """YYYY-MM-DD → 1994年9月12日"""
    try:
        bd = datetime.strptime(birth_str[:10], '%Y-%m-%d')
        return f'{bd.year}年{bd.month}月{bd.day}日'
    except Exception:
        return birth_str


def _years_since(date_str: str) -> str:
    try:
        dd = datetime.strptime(date_str[:10], '%Y-%m-%d')
        years = datetime.now().year - dd.year
        return f'{years}年目'
    except Exception:
        return ''


def _fetch_recent_articles_for_artist(artist: str, limit: int = 6) -> list[dict]:
    """指定 artist の最新記事を WP REST から取得 (search経由)"""
    import urllib.parse as _urlp
    q = _urlp.quote(artist)
    url = (f'https://www.kpopjournal.tokyo/wp-json/wp/v2/posts'
           f'?search={q}&per_page={limit}&orderby=date&order=desc'
           f'&_fields=id,slug,title,date,featured_media,_links,_embedded&_embed=wp:featuredmedia')
    try:
        req = urllib.request.Request(url, headers={'Authorization': f'Basic {AUTH}'})
        return json.loads(urllib.request.urlopen(req, timeout=10).read())
    except Exception:
        return []


def render_html(artist: str, profile: dict) -> str:
    """Profile JSON → WordPress page HTML (namu-wiki スタイル v2)"""
    today = datetime.now(JST).strftime('%Y年%m月%d日')
    members = profile.get('members', []) or []
    debut = profile.get('debut_date', '')
    agency = profile.get('agency', '')
    fandom = profile.get('fandom_name', '')
    summary = profile.get('summary_ja', '')

    # Hero gradient (artist名から決定的に選択)
    hero_grad = _GRAD_POOL[hash(artist) % len(_GRAD_POOL)]
    initial = artist[0].upper()

    # 国籍breakdown
    natl_count = {}
    for m in members:
        n = m.get('nationality', '不明')
        natl_count[n] = natl_count.get(n, 0) + 1
    natl_str = ' / '.join(f'{k} {v}名' for k, v in natl_count.items())

    parts = [_build_schema_org(artist, profile)]

    # ── HERO ──
    parts.append(f'''<div class="ap-hero" style="background:linear-gradient(135deg,{hero_grad[0]},{hero_grad[1]});">
  <div class="ap-hero-inner">
    <div class="ap-hero-avatar" style="background:rgba(255,255,255,0.18);">{initial}</div>
    <div class="ap-hero-info">
      <h1 class="ap-hero-name">{artist}</h1>
      <p class="ap-hero-tagline">{agency}{(" ・ デビュー " + debut[:7].replace("-","年") + "月") if debut else ""}</p>
      <div class="ap-hero-stats">
        <span class="ap-stat">👥 {len(members)}名</span>
        {(f'<span class="ap-stat">⭐ {fandom}</span>') if fandom else ''}
        {(f'<span class="ap-stat">🎂 {_years_since(debut)}</span>') if debut else ''}
      </div>
    </div>
  </div>
</div>''')

    parts.append('<div class="artist-profile">')
    parts.append(f'<p class="ap-updated">最終更新: {today}</p>')

    # 概要
    if summary:
        parts.append(f'<div class="ap-intro"><p>{summary}</p></div>')

    # 基本情報 grid
    parts.append('<h2 class="ap-h2">📋 基本情報</h2>')
    parts.append('<dl class="ap-info-grid">')
    if agency:
        parts.append(f'<div class="ap-info-item"><dt>所属事務所</dt><dd>{agency}</dd></div>')
    if debut:
        debut_disp = _format_birth(debut)
        parts.append(f'<div class="ap-info-item"><dt>デビュー</dt><dd>{debut_disp} <small>({_years_since(debut)})</small></dd></div>')
    if fandom:
        meaning = profile.get('fandom_meaning', '')
        meaning_html = f'<br><small>{meaning}</small>' if meaning else ''
        parts.append(f'<div class="ap-info-item"><dt>ファンダム</dt><dd><strong>{fandom}</strong>{meaning_html}</dd></div>')
    parts.append(f'<div class="ap-info-item"><dt>メンバー数</dt><dd>{len(members)}名</dd></div>')
    if natl_str:
        parts.append(f'<div class="ap-info-item"><dt>国籍</dt><dd>{natl_str}</dd></div>')
    parts.append('</dl>')

    # ── メンバーカード grid ──
    if members:
        parts.append('<h2 class="ap-h2">👥 メンバー</h2>')
        parts.append('<div class="ap-members-grid">')
        for i, m in enumerate(members):
            name_ja = m.get('name_ja', '')
            name_en = m.get('name_en', '')
            real = m.get('real_name_en') or m.get('name_kr', '')
            position = m.get('position', '')
            birth = m.get('birth', '')
            age = _calc_age(birth)
            natl = m.get('nationality', '')
            grad = _GRAD_POOL[(hash(artist) + i) % len(_GRAD_POOL)]
            mi = (name_en or name_ja or '?')[0].upper()

            display_name = name_ja or name_en
            sub_name = name_en if name_ja and name_en and name_ja != name_en else ''

            parts.append(f'''<div class="ap-member-card">
  <div class="ap-member-avatar" style="background:linear-gradient(135deg,{grad[0]},{grad[1]});">{mi}</div>
  <div class="ap-member-name">{display_name}</div>
  {f'<div class="ap-member-en">{sub_name}</div>' if sub_name else ''}
  {f'<div class="ap-member-real"><small>本名: {real}</small></div>' if real else ''}
  <div class="ap-member-position">{position}</div>
  {f'<div class="ap-member-birth">{_format_birth(birth)}{f" ({age}歳)" if age else ""}</div>' if birth else ''}
  {f'<div class="ap-member-natl">🌏 {natl}</div>' if natl else ''}
</div>''')
        parts.append('</div>')

    # ── ディスコグラフィー timeline ──
    disco = profile.get('discography_highlights', [])
    if disco:
        parts.append('<h2 class="ap-h2">🎵 主要ディスコグラフィー</h2>')
        parts.append('<div class="ap-disco-timeline">')
        type_meta = {
            'album': ('🎵', '#FF1493', 'アルバム'),
            'ep': ('💿', '#9B59B6', 'ミニアルバム'),
            'single': ('🎶', '#00BCD4', 'シングル'),
            'japanese': ('🇯🇵', '#E91E63', '日本盤'),
            'ost': ('🎞️', '#FFB300', 'OST'),
        }
        for d in sorted(disco, key=lambda x: x.get('year', '9999'), reverse=True):
            t = d.get('type', '')
            icon, color, label = type_meta.get(t, ('📌', '#888', 'その他'))
            note = d.get('note', '')
            parts.append(f'''<div class="ap-disco-item">
  <div class="ap-disco-year">{d.get("year","")}</div>
  <div class="ap-disco-icon" style="background:{color};">{icon}</div>
  <div class="ap-disco-body">
    <div class="ap-disco-title"><strong>{d.get("title","")}</strong></div>
    <div class="ap-disco-meta"><span class="ap-disco-type" style="color:{color};">{label}</span>{f" / {note}" if note else ""}</div>
  </div>
</div>''')
        parts.append('</div>')

    # ── 公式SNS rich cards ──
    links = profile.get('official_links', {}) or {}
    if any(links.values()):
        parts.append('<h2 class="ap-h2">🔗 公式SNS</h2>')
        parts.append('<div class="ap-sns-grid">')
        sns_meta = {
            'twitter': ('𝕏', '#000', 'X (Twitter)'),
            'instagram': ('📷', 'linear-gradient(45deg,#feda75,#fa7e1e,#d62976,#962fbf,#4f5bd5)', 'Instagram'),
            'weverse': ('💜', '#7B1FA2', 'Weverse'),
            'youtube': ('▶', '#FF0000', 'YouTube'),
            'tiktok': ('🎵', '#000', 'TikTok'),
            'japan_official': ('🇯🇵', '#D62929', '日本公式'),
        }
        for k in ['twitter', 'instagram', 'weverse', 'youtube', 'tiktok', 'japan_official']:
            v = links.get(k)
            if not v: continue
            icon, bg, label = sns_meta[k]
            parts.append(f'''<a href="{v}" target="_blank" rel="noopener" class="ap-sns-card">
  <div class="ap-sns-icon" style="background:{bg};">{icon}</div>
  <div class="ap-sns-label">{label}</div>
</a>''')
        parts.append('</div>')

    # ── 最新記事カード grid ──
    recent_posts = _fetch_recent_articles_for_artist(artist, limit=6)
    if recent_posts:
        parts.append(f'<h2 class="ap-h2">📰 {artist} の最新記事</h2>')
        parts.append('<div class="ap-articles-grid">')
        for post in recent_posts:
            title = post.get('title', {}).get('rendered', '')
            slug = post.get('slug', '')
            date_str = post.get('date', '')[:10].replace('-', '/')
            # featured_media URL
            thumb = ''
            embedded = post.get('_embedded', {}).get('wp:featuredmedia', [])
            if embedded and embedded[0].get('source_url'):
                thumb = embedded[0]['source_url']
                # WP のmedium-large サムネがあれば優先
                sizes = embedded[0].get('media_details', {}).get('sizes', {})
                if sizes.get('medium_large', {}).get('source_url'):
                    thumb = sizes['medium_large']['source_url']
                elif sizes.get('medium', {}).get('source_url'):
                    thumb = sizes['medium']['source_url']
            thumb_html = (f'<img src="{thumb}" alt="{title}" loading="lazy" />'
                          if thumb else '<div class="ap-article-noimg">📰</div>')
            parts.append(f'''<a href="/{slug}/" class="ap-article-card">
  <div class="ap-article-thumb">{thumb_html}</div>
  <div class="ap-article-body">
    <div class="ap-article-title">{title}</div>
    <div class="ap-article-date">{date_str}</div>
  </div>
</a>''')
        parts.append('</div>')

    # ── 関連リンク ──
    parts.append('<h2 class="ap-h2">🔗 関連</h2>')
    parts.append('<div class="ap-related">')
    parts.append(f'<a href="/release-calendar/" class="ap-related-card ap-related-cal">'
                 f'<span class="ap-related-icon">📅</span>'
                 f'<div><strong>{artist} の今後の予定</strong><br><small>カムバック・カレンダーで確認 →</small></div></a>')
    parts.append(f'<a href="/?s={artist.replace(" ", "+")}" class="ap-related-card ap-related-news">'
                 f'<span class="ap-related-icon">🔍</span>'
                 f'<div><strong>{artist} 関連を全件検索</strong><br><small>サイト内検索 →</small></div></a>')
    parts.append(f'<a href="/artists/" class="ap-related-card ap-related-hub">'
                 f'<span class="ap-related-icon">🎤</span>'
                 f'<div><strong>他のアーティスト</strong><br><small>全プロフィール →</small></div></a>')
    parts.append('</div>')

    parts.append('</div>')  # /artist-profile

    # ── インラインCSS (namu-wiki風) ──
    parts.append('''<style>
/* ========== Hero ========== */
.ap-hero { border-radius: 16px; padding: 2.5em 1.5em; margin: 1em 0 2em; color: white; box-shadow: 0 8px 32px rgba(0,0,0,0.12); }
.ap-hero-inner { display: flex; align-items: center; gap: 1.5em; max-width: 900px; margin: 0 auto; flex-wrap: wrap; }
.ap-hero-avatar { width: 100px; height: 100px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 3em; font-weight: bold; backdrop-filter: blur(10px); border: 3px solid rgba(255,255,255,0.4); flex-shrink: 0; }
.ap-hero-info { flex: 1; min-width: 200px; }
.ap-hero-name { font-size: 2.5em; font-weight: 800; margin: 0 0 0.2em; line-height: 1.1; color: white; text-shadow: 0 2px 8px rgba(0,0,0,0.2); }
.ap-hero-tagline { font-size: 1em; opacity: 0.95; margin: 0 0 1em; }
.ap-hero-stats { display: flex; gap: 0.6em; flex-wrap: wrap; }
.ap-stat { background: rgba(255,255,255,0.22); padding: 0.4em 0.9em; border-radius: 99px; font-size: 0.85em; font-weight: 600; backdrop-filter: blur(8px); }

/* ========== Sections ========== */
.artist-profile { max-width: 900px; margin: 0 auto; padding: 0 1em; }
.ap-updated { color: #999; font-size: 0.85em; text-align: right; margin: 0.5em 0; }
.ap-h2 { font-size: 1.5em; font-weight: 700; margin: 2em 0 1em; padding-bottom: 0.4em; border-bottom: 3px solid #FF1493; }
.ap-intro { background: linear-gradient(135deg, #fff8fc, #f8f4ff); padding: 1.4em 1.6em; border-radius: 12px; margin: 1em 0 2em; border-left: 4px solid #FF1493; line-height: 1.7; }

/* ========== 基本情報 grid ========== */
.ap-info-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 0.8em; margin: 1em 0; }
.ap-info-item { background: #f8f9fb; padding: 1em 1.2em; border-radius: 10px; border-left: 3px solid #FF1493; }
.ap-info-item dt { font-size: 0.78em; font-weight: 700; color: #888; letter-spacing: 0.05em; margin: 0 0 0.3em; text-transform: uppercase; }
.ap-info-item dd { margin: 0; font-size: 1em; color: #222; line-height: 1.5; }
.ap-info-item dd small { color: #666; }

/* ========== Members grid ========== */
.ap-members-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 1em; margin: 1em 0; }
.ap-member-card { background: white; border-radius: 12px; padding: 1.2em 1em; text-align: center; box-shadow: 0 2px 8px rgba(0,0,0,0.06); border: 1px solid #f0f0f0; transition: transform 0.2s, box-shadow 0.2s; }
.ap-member-card:hover { transform: translateY(-3px); box-shadow: 0 8px 20px rgba(255,20,147,0.12); }
.ap-member-avatar { width: 70px; height: 70px; border-radius: 50%; margin: 0 auto 0.7em; display: flex; align-items: center; justify-content: center; font-size: 2em; font-weight: 800; color: white; box-shadow: 0 4px 12px rgba(0,0,0,0.1); }
.ap-member-name { font-size: 1.15em; font-weight: 700; color: #222; margin-bottom: 0.1em; }
.ap-member-en { font-size: 0.85em; color: #999; margin-bottom: 0.3em; }
.ap-member-real { font-size: 0.75em; color: #aaa; margin-bottom: 0.4em; }
.ap-member-position { font-size: 0.85em; color: #555; margin: 0.5em 0 0.3em; line-height: 1.3; }
.ap-member-birth { font-size: 0.8em; color: #777; }
.ap-member-natl { font-size: 0.75em; color: #999; margin-top: 0.2em; }

/* ========== Discography timeline ========== */
.ap-disco-timeline { position: relative; padding-left: 0; }
.ap-disco-item { display: flex; align-items: flex-start; gap: 0.9em; padding: 0.7em 0; border-bottom: 1px dashed #eee; }
.ap-disco-year { font-size: 1em; font-weight: 700; color: #888; flex-shrink: 0; width: 50px; padding-top: 0.2em; }
.ap-disco-icon { width: 36px; height: 36px; border-radius: 50%; display: flex; align-items: center; justify-content: center; color: white; font-size: 1.1em; flex-shrink: 0; }
.ap-disco-body { flex: 1; }
.ap-disco-title { font-size: 1em; color: #222; }
.ap-disco-meta { font-size: 0.8em; color: #888; margin-top: 0.2em; }
.ap-disco-type { font-weight: 600; }

/* ========== SNS grid ========== */
.ap-sns-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 0.8em; margin: 1em 0; }
.ap-sns-card { display: flex; align-items: center; gap: 0.8em; padding: 0.9em 1em; background: white; border-radius: 10px; border: 1px solid #eee; text-decoration: none; color: #222; transition: transform 0.2s, box-shadow 0.2s; }
.ap-sns-card:hover { transform: translateY(-2px); box-shadow: 0 4px 14px rgba(0,0,0,0.08); }
.ap-sns-icon { width: 36px; height: 36px; border-radius: 8px; display: flex; align-items: center; justify-content: center; color: white; font-size: 1.2em; font-weight: bold; flex-shrink: 0; }
.ap-sns-label { font-size: 0.9em; font-weight: 600; }

/* ========== Articles grid (関連記事カード) ========== */
.ap-articles-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 1em; margin: 1em 0; }
.ap-article-card { display: block; background: white; border-radius: 12px; overflow: hidden; text-decoration: none; color: #222; box-shadow: 0 2px 8px rgba(0,0,0,0.06); border: 1px solid #f0f0f0; transition: transform 0.2s, box-shadow 0.2s; }
.ap-article-card:hover { transform: translateY(-3px); box-shadow: 0 8px 20px rgba(255,20,147,0.12); }
.ap-article-thumb { width: 100%; aspect-ratio: 16/9; overflow: hidden; background: linear-gradient(135deg,#ffe1ec,#fff8e1); display: flex; align-items: center; justify-content: center; }
.ap-article-thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
.ap-article-noimg { font-size: 2.5em; opacity: 0.5; }
.ap-article-body { padding: 0.8em 1em; }
.ap-article-title { font-size: 0.95em; font-weight: 600; line-height: 1.4; color: #222; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
.ap-article-date { font-size: 0.75em; color: #999; margin-top: 0.4em; }

/* ========== Related ========== */
.ap-related { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 0.8em; margin: 1em 0; }
.ap-related-card { display: flex; align-items: center; gap: 0.8em; padding: 1em 1.2em; border-radius: 12px; text-decoration: none; color: #222; transition: transform 0.2s; }
.ap-related-card:hover { transform: translateY(-2px); }
.ap-related-icon { font-size: 1.6em; }
.ap-related-cal { background: linear-gradient(135deg, #fff8e1, #ffecb3); border-left: 4px solid #ffc107; }
.ap-related-news { background: linear-gradient(135deg, #e3f2fd, #bbdefb); border-left: 4px solid #2196F3; }
.ap-related-hub { background: linear-gradient(135deg, #fce4ec, #f8bbd0); border-left: 4px solid #e91e63; }

/* ========== Mobile ========== */
@media (max-width: 600px) {
  .ap-hero { padding: 1.8em 1em; }
  .ap-hero-name { font-size: 1.8em; }
  .ap-hero-avatar { width: 80px; height: 80px; font-size: 2.4em; }
  .ap-h2 { font-size: 1.25em; }
  .ap-members-grid { grid-template-columns: repeat(2, 1fr); gap: 0.7em; }
  .ap-member-card { padding: 0.9em 0.6em; }
  .ap-member-avatar { width: 56px; height: 56px; font-size: 1.6em; }
  .ap-member-name { font-size: 1em; }
}
</style>''')
    return '\n'.join(parts)


def find_or_create_profile_page(slug: str, artist: str, html: str) -> int:
    page_slug = f'artist-{slug}'
    title = f'{artist} メンバー・所属・公式情報まとめ'

    # find existing
    req = urllib.request.Request(
        f'https://www.kpopjournal.tokyo/wp-json/wp/v2/pages?slug={page_slug}&_fields=id',
        headers={'Authorization': f'Basic {AUTH}'})
    try:
        existing = json.loads(urllib.request.urlopen(req, timeout=15).read())
    except Exception:
        existing = []

    payload = {
        'title': title,
        'content': html,
        'status': 'publish',
        'slug': page_slug,
    }
    if existing:
        url = f'https://www.kpopjournal.tokyo/wp-json/wp/v2/pages/{existing[0]["id"]}'
    else:
        url = 'https://www.kpopjournal.tokyo/wp-json/wp/v2/pages'

    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), method='POST',
        headers={'Authorization': f'Basic {AUTH}', 'Content-Type': 'application/json'})
    try:
        r = json.loads(urllib.request.urlopen(req, timeout=30).read())
        return r.get('id', 0)
    except Exception as e:
        print(f"  WP publish err: {e}", flush=True)
        return 0


def build_one(client, artist: str, slug: str) -> bool:
    print(f"[{artist}] fetching profile...", flush=True)
    profile = fetch_profile(client, artist)
    if not profile or not profile.get('members'):
        print(f"  ✗ skipped (no data)", flush=True)
        return False

    n_members = len(profile.get('members', []))
    print(f"  ✓ agency={profile.get('agency','?')} members={n_members}", flush=True)

    # Save JSON
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    out_path = PROFILE_DIR / f'{slug}.json'
    profile['_last_updated'] = datetime.now(JST).isoformat()
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)
    print(f"  saved {out_path}", flush=True)

    # Render + publish
    html = render_html(artist, profile)
    page_id = find_or_create_profile_page(slug, artist, html)
    print(f"  page_id={page_id} URL=https://www.kpopjournal.tokyo/artist-{slug}/", flush=True)

    # Cache purge
    try:
        from lib.frontend_cache import purge_paths
        purge_paths([f'/artist-{slug}/'])
    except Exception:
        pass

    # GSC indexing API (sticky pageを早期indexさせる)
    try:
        from lib.gsc_indexing import notify_url_updated
        full_url = f'https://www.kpopjournal.tokyo/artist-{slug}/'
        r = notify_url_updated(full_url)
        if r.get('status') == 'ok':
            print(f"  GSC indexed", flush=True)
    except Exception as e:
        print(f"  GSC submit err: {e}", flush=True)

    return page_id > 0


def update_frontend_slug_list():
    """frontend が /artists/ で参照する profile slug list をpublic/dataに書き出す"""
    slugs = sorted(p.stem for p in PROFILE_DIR.glob('*.json') if p.stem != 'fromis9')
    out = Path('/home/aiuser/kpopjournal-frontend/public/data/artist-profile-slugs.json')
    if not out.parent.exists():
        return
    out.write_text(json.dumps(slugs), encoding='utf-8')
    print(f"  frontend slug list updated: {len(slugs)} slugs", flush=True)


def update_internal_link_dictionary():
    """profile JSON存在artistを internal_link_dictionary.jsonに反映"""
    dict_path = Path('/home/aiuser/kpop-ai-system/config/internal_link_dictionary.json')
    if not dict_path.exists():
        return
    try:
        d = json.loads(dict_path.read_text(encoding='utf-8'))
    except Exception:
        return

    artist_to_slug = {a['name']: a['slug'] for a in PRIORITY_ARTISTS}
    changed = False
    for artist, slug in artist_to_slug.items():
        if not (PROFILE_DIR / f'{slug}.json').exists():
            continue
        new_url = f'/artist-{slug}/'
        if d.get(artist) != new_url:
            d[artist] = new_url
            changed = True
        # long-tail keywords
        for suffix in ['メンバー', '事務所', 'ファンダム', 'プロフィール']:
            kw = f'{artist}{suffix}'
            if d.get(kw) != new_url:
                d[kw] = new_url
                changed = True
    if changed:
        dict_path.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f"  internal_link_dictionary updated ({len(d)} entries)", flush=True)


def main():
    sys.stdout.reconfigure(line_buffering=True)
    args = sys.argv[1:]

    if args:
        # 引数指定
        targets = []
        for a in args:
            for art in PRIORITY_ARTISTS:
                if a.lower() == art['name'].lower() or a.lower() == art['slug']:
                    targets.append(art)
                    break
            else:
                # priority外のartist (slugは推測)
                targets.append({'name': a, 'slug': a.lower().replace(' ', '-')})
    else:
        targets = PRIORITY_ARTISTS

    print(f"Building profiles for {len(targets)} artists", flush=True)
    client = anthropic.Anthropic()

    success = 0
    for i, art in enumerate(targets, 1):
        print(f"\n[{i}/{len(targets)}] {art['name']}", flush=True)
        if build_one(client, art['name'], art['slug']):
            success += 1

    print(f"\n=== Done: {success}/{len(targets)} succeeded ===", flush=True)

    # internal_link_dictionary 更新
    update_internal_link_dictionary()

    # frontend slug list 更新 (/artists/ハブで /artist-{slug}/にlinkするため)
    update_frontend_slug_list()


if __name__ == '__main__':
    main()
