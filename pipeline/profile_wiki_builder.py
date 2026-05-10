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


def render_html(artist: str, profile: dict) -> str:
    """Profile JSON → WordPress page HTML"""
    today = datetime.now(JST).strftime('%Y年%m月%d日')
    parts = [
        _build_schema_org(artist, profile),
        f'<div class="artist-profile">',
        f'<p class="last-updated"><small>最終更新: {today}</small></p>',
    ]

    # 概要
    summary = profile.get('summary_ja', '')
    if summary:
        parts.append(f'<div class="profile-intro"><p>{summary}</p></div>')

    # 基本情報table
    parts.append('<h2>基本情報</h2>')
    parts.append('<table class="profile-basic">')
    if profile.get('agency'):
        parts.append(f'<tr><th>所属事務所</th><td>{profile["agency"]}</td></tr>')
    if profile.get('debut_date'):
        parts.append(f'<tr><th>デビュー日</th><td>{profile["debut_date"]}</td></tr>')
    if profile.get('fandom_name'):
        f_meaning = f' — {profile["fandom_meaning"]}' if profile.get('fandom_meaning') else ''
        parts.append(f'<tr><th>ファンダム名</th><td><strong>{profile["fandom_name"]}</strong>{f_meaning}</td></tr>')
    parts.append(f'<tr><th>メンバー数</th><td>{len(profile.get("members",[]))}人</td></tr>')
    parts.append('</table>')

    # メンバー
    members = profile.get('members', [])
    if members:
        parts.append('<h2>メンバー</h2>')
        parts.append('<table class="profile-members">')
        parts.append('<thead><tr><th>名前</th><th>ポジション</th><th>生年月日</th><th>出身</th></tr></thead>')
        parts.append('<tbody>')
        for m in members:
            name_disp = m.get('name_ja') or m.get('name_en', '')
            name_en = m.get('name_en', '')
            real = m.get('real_name_en') or m.get('name_kr', '')
            name_html = f'<strong>{name_disp}</strong>'
            if name_en and name_en != name_disp:
                name_html += f'<br><small>{name_en}</small>'
            if real:
                name_html += f'<br><small>本名: {real}</small>'
            parts.append(
                f'<tr><td>{name_html}</td><td>{m.get("position","")}</td>'
                f'<td>{m.get("birth","")}</td><td>{m.get("nationality","")}</td></tr>'
            )
        parts.append('</tbody></table>')

    # ディスコグラフィ
    disco = profile.get('discography_highlights', [])
    if disco:
        parts.append('<h2>主要作品</h2>')
        parts.append('<ul class="profile-disco">')
        type_label = {'album': '🎵 アルバム', 'ep': '💿 EP', 'single': '🎵 シングル',
                      'japanese': '🇯🇵 日本盤', 'ost': '🎞️ OST'}
        for d in sorted(disco, key=lambda x: x.get('year','9999'), reverse=True):
            tl = type_label.get(d.get('type',''), '📌')
            note = f' — {d["note"]}' if d.get('note') else ''
            parts.append(f'<li><strong>{d.get("year","")}</strong> {tl} {d.get("title","")}{note}</li>')
        parts.append('</ul>')

    # 公式リンク
    links = profile.get('official_links', {}) or {}
    if any(links.values()):
        parts.append('<h2>公式SNS / リンク</h2>')
        parts.append('<ul class="profile-links">')
        link_label = {
            'twitter': '🐦 X (Twitter)', 'instagram': '📷 Instagram',
            'weverse': '💜 Weverse', 'youtube': '▶️ YouTube',
            'tiktok': '🎵 TikTok', 'japan_official': '🇯🇵 日本公式',
        }
        for k in ['twitter', 'instagram', 'weverse', 'youtube', 'tiktok', 'japan_official']:
            v = links.get(k)
            if v:
                parts.append(f'<li><a href="{v}" target="_blank" rel="noopener">{link_label[k]}</a></li>')
        parts.append('</ul>')

    # カレンダー誘導
    parts.append('<h2>関連</h2>')
    parts.append(
        f'<p>👉 <a href="/release-calendar/" target="_blank">{artist} を含むK-POP主要グループの今後90日のリリースカレンダー</a></p>'
    )
    parts.append(f'<p>📰 <a href="/?s={artist.replace(" ", "+")}">{artist} の最新ニュース記事</a></p>')

    parts.extend([
        '</div>',
        '<style>',
        '.artist-profile table { width:100%; border-collapse:collapse; margin:1em 0; }',
        '.artist-profile th, .artist-profile td { padding:0.6em; border:1px solid #ddd; text-align:left; vertical-align:top; }',
        '.artist-profile .profile-basic th { width:30%; background:#f4f4f8; }',
        '.artist-profile .profile-members th { background:#f4f4f8; }',
        '.artist-profile .profile-intro { background:#f8f4ff; padding:1em; border-left:4px solid #9c27b0; margin:1em 0; }',
        '.artist-profile .last-updated { color:#888; }',
        '</style>',
    ])
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
