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
import urllib.parse
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
    {'name': 'fromis_9', 'slug': 'fromis9'},
    {'name': 'BIGBANG', 'slug': 'big-bang'},
    {'name': 'NCT', 'slug': 'nct'},
    {'name': 'EXO', 'slug': 'exo'},
    {'name': 'CORTIS', 'slug': 'cortis'},
    {'name': 'XG', 'slug': 'xg'},
    {'name': 'MOMOLAND', 'slug': 'momoland'},
    {'name': 'ZEROBASEONE', 'slug': 'zerobaseone'},
    {'name': 'Hearts2Hearts', 'slug': 'hearts2hearts'},
    {'name': 'TREASURE', 'slug': 'treasure'},
    {'name': 'BoA', 'slug': 'boa'},
    {'name': '1VERSE', 'slug': '1verse'},
    {'name': 'MEOVV', 'slug': 'meovv'},
    {'name': 'STAYC', 'slug': 'stayc'},
    # 2026-05-12 追加 (第2弾): TWS / NEXZ / NiziU / IZNA / (G)I-DLE / ALLDAY PROJECT
    {'name': 'TWS', 'slug': 'tws'},
    {'name': 'NEXZ', 'slug': 'nexz'},
    {'name': 'NiziU', 'slug': 'niziu'},
    {'name': 'IZNA', 'slug': 'izna'},
    {'name': '(G)I-DLE', 'slug': 'gidle'},
    {'name': 'ALLDAY PROJECT', 'slug': 'allday-project'},
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

# 個人情報 (group fetchと別 API call、schema-too-complex回避)
MEMBER_DETAILS_SCHEMA = {
    "type": "object",
    "properties": {
        "members": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name_en": {"type": "string"},
                    "height_cm": {"type": "string"},
                    "blood_type": {"type": "string"},
                    "mbti": {"type": "string"},
                    "education": {"type": "string"},
                    "hobbies": {"type": "string"},
                    "solo_works": {"type": "string"},
                    "instagram_personal": {"type": "string"},
                },
                "required": ["name_en"],
                "additionalProperties": False,
            }
        },
    },
    "required": ["members"],
    "additionalProperties": False,
}


# 2026-05-12 (Phase 5): system block に分離し cache_control 1h で固定。
# 60 artist × 週次でも 1h 窓内の連続 fetch で cache_read 0.1x の恩恵。
_PROFILE_SYSTEM = """あなたは K-POP アーティストの包括的プロフィール作成アシスタントです。

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
JSON schema に厳密に従って返却すること。"""


def fetch_profile(client, artist: str, timeout_s: int = int(os.getenv('PROFILE_FETCH_TIMEOUT', '180'))) -> dict:
    today = datetime.now(JST).strftime('%Y-%m-%d')
    prompt = f"""今日: {today}
対象アーティスト: 「{artist}」

検索クエリ例:
- "{artist} members profile site:wikipedia.org"
- "{artist} official Twitter Instagram"
- "{artist} discography {today[:4]}"

web_search で集約して JSON で返却してください。
"""
    use_web_search = os.getenv('PROFILE_USE_WEBSEARCH') == '1'

    try:
        import httpx
        timeout_client = anthropic.Anthropic(timeout=httpx.Timeout(timeout_s, connect=10.0))
        kwargs = {
            'model': 'claude-sonnet-4-6',
            'max_tokens': 4500,
            'system': [{
                "type": "text",
                "text": _PROFILE_SYSTEM,
                "cache_control": {"type": "ephemeral", "ttl": "1h"},
            }],
            'output_config': {"format": {"type": "json_schema", "schema": PROFILE_SCHEMA}},
            'messages': [{"role": "user", "content": prompt}],
        }
        if use_web_search:
            # 2026-05-12 (Phase 3): max_uses 5 → 3 で Web Search 課金節約 (品質維持)。
            kwargs['tools'] = [{"type": "web_search_20260209", "name": "web_search", "max_uses": 3}]
        # 2026-05-12 (Phase 6): cost guard + log_usage
        try:
            from lib.anthropic_cost_guard import guard_before_call, log_usage
            if not guard_before_call('profile_wiki_builder'):
                return {}
        except ImportError:
            log_usage = None
        response = timeout_client.messages.create(**kwargs)
        if log_usage:
            try:
                log_usage('profile_wiki_builder', model='claude-sonnet-4-6', usage=response.usage)
            except Exception:
                pass
        text = next((b.text for b in response.content if b.type == 'text'), '{}')
        return json.loads(text)
    except Exception as e:
        print(f"  err: {type(e).__name__}: {str(e)[:200]}", flush=True)
        return {}


def fetch_member_details(client, artist: str, members: list[dict], timeout_s: int = int(os.getenv('PROFILE_FETCH_TIMEOUT', '180'))) -> dict:
    """個人プロフィール (身長/MBTI/学歴等) を 2nd API call で取得 (schema-too-complex回避)"""
    if not members:
        return {'members': []}
    today = datetime.now(JST).strftime('%Y-%m-%d')
    names = ', '.join((m.get('name_en') or m.get('name_ja') or '') for m in members if m.get('name_en') or m.get('name_ja'))
    # 2026-05-12 (Phase 5): fetch_profile と同じ system block instruction を共有して
    # cache_control 1h で固定。60 artist 連続 fetch で cache_read 0.1x の恩恵。
    member_system = """あなたは K-POP メンバー個人プロフィールリサーチアシスタントです。

各メンバーについて以下を埋めてください (確証無ければ空文字 "")。推測禁止。
- name_en: stage name (対象と完全一致)
- height_cm: 身長 cm数字のみ。例 "162"
- blood_type: A / B / O / AB のいずれか
- mbti: 例 "INFP" (本人/事務所公表値のみ)
- education: 日本語で簡潔に。例 "ソウル芸術高校 → 韓国芸術綜合学校 (中退)"
- hobbies: 3つまでカンマ区切り。例 "絵画, 映画鑑賞, 料理"
- solo_works: 主要なソロ作品1-2作。例 "FLOWER (2023年), ME (2023年)"
- instagram_personal: 個人 Instagram URL (グループ公式とは別)

検索クエリ例: "[artist] member height MBTI Wikipedia" / "[artist] members blood type birthday"

メンバー全員分必ず members[] に入れること (1件も漏らさない)。
JSON schema に厳密に従うこと。"""

    prompt = f"""今日: {today}
対象グループ: 「{artist}」
対象メンバー: {names}

web_search で集約してください。"""
    try:
        import httpx
        timeout_client = anthropic.Anthropic(timeout=httpx.Timeout(timeout_s, connect=10.0))
        kwargs = {
            'model': 'claude-sonnet-4-6',
            'max_tokens': 3500,
            'system': [{
                "type": "text",
                "text": member_system,
                "cache_control": {"type": "ephemeral", "ttl": "1h"},
            }],
            'output_config': {"format": {"type": "json_schema", "schema": MEMBER_DETAILS_SCHEMA}},
            'messages': [{"role": "user", "content": prompt}],
        }
        if os.getenv('PROFILE_USE_WEBSEARCH') == '1':
            # 2026-05-12 (Phase 3): max_uses 5 → 3 で Web Search 課金節約 (品質維持)。
            kwargs['tools'] = [{"type": "web_search_20260209", "name": "web_search", "max_uses": 3}]
        # 2026-05-12 (Phase 6): cost guard + log_usage
        try:
            from lib.anthropic_cost_guard import guard_before_call, log_usage
            if not guard_before_call('profile_wiki_builder'):
                return {}
        except ImportError:
            log_usage = None
        response = timeout_client.messages.create(**kwargs)
        if log_usage:
            try:
                log_usage('profile_wiki_builder', model='claude-sonnet-4-6', usage=response.usage)
            except Exception:
                pass
        text = next((b.text for b in response.content if b.type == 'text'), '{}')
        return json.loads(text)
    except Exception as e:
        print(f"  member_details err: {type(e).__name__}: {str(e)[:200]}", flush=True)
        return {'members': []}


def _merge_member_details(profile: dict, details: dict) -> dict:
    """fetch_member_details の結果を profile['members'] にマージ"""
    detail_map = {}
    for d in (details.get('members') or []):
        key = (d.get('name_en') or '').strip().lower()
        if key:
            detail_map[key] = d
    extra_keys = ['height_cm', 'blood_type', 'mbti', 'education', 'hobbies', 'solo_works', 'instagram_personal']
    for m in (profile.get('members') or []):
        key = (m.get('name_en') or '').strip().lower()
        d = detail_map.get(key, {})
        for k in extra_keys:
            v = (d.get(k) or '').strip()
            if v:
                m[k] = v
    return profile


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


def _member_slug(name_en: str) -> str:
    """name_en → URL safe slug (/artist-{group}-{member}/ 用)"""
    import unicodedata
    s = unicodedata.normalize('NFKD', name_en or '')
    s = ''.join(c for c in s if not unicodedata.combining(c))  # アクセント除去 (Rosé→Rose)
    s = re.sub(r'[^a-zA-Z0-9]+', '-', s).strip('-').lower()
    return s


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


JA_ALIASES = {
    'aespa': ['エスパ'], 'bts': ['防弾少年団', 'バンタン'], 'blackpink': ['ブラックピンク'],
    'newjeans': ['ニュージーンズ'], 'twice': ['トゥワイス'], 'itzy': ['イッジ'],
    'ive': ['アイヴ', 'アイブ'], 'le sserafim': ['ルセラフィム'], 'le-sserafim': ['ルセラフィム'],
    'enhypen': ['エンハイフン'], 'seventeen': ['セブチ', 'セブンティーン'],
    'stray kids': ['スキズ', 'ストレイキッズ'], 'stray-kids': ['スキズ', 'ストレイキッズ'],
    'txt': ['トゥモロー・バイ・トゥゲザー', 'トゥバトゥ', 'TOMORROW X TOGETHER'],
    'nmixx': ['エンミックス'], 'babymonster': ['ベイビーモンスター', 'ベビモン'],
    'riize': ['ライズ'], 'illit': ['アイリット'],
    'boynextdoor': ['ボーイネクストドア', 'BOY NEXT DOOR', 'BND'],
    'kiss of life': ['キスオブライフ', 'KISS OF LIFE', 'KIOF'],
    'kiss-of-life': ['キスオブライフ'], 'iu': ['アイユー'], 'katseye': ['キャットアイ'],
    'fromis9': ['フロミス', 'フロミスナイン'],
}


def _fetch_recent_articles_for_artist(artist: str, limit: int = 6) -> list[dict]:
    """指定 artist の最新記事を WP REST から取得 + title厳格filter
    artist名 + 日本語aliases で複数 search → title filter → dedupe
    """
    import urllib.parse as _urlp
    aliases = JA_ALIASES.get(artist.lower(), [])
    search_terms = [artist] + aliases
    fetch_n = max(limit * 4, 40)
    seen_ids = set()
    posts_all = []
    for term in search_terms:
        q = _urlp.quote(term)
        url = (f'https://www.kpopjournal.tokyo/wp-json/wp/v2/posts'
               f'?search={q}&per_page={fetch_n}&orderby=date&order=desc'
               f'&_fields=id,slug,title,excerpt,date,featured_media,_links,_embedded&_embed=wp:featuredmedia')
        try:
            req = urllib.request.Request(url, headers={'Authorization': f'Basic {AUTH}'})
            posts = json.loads(urllib.request.urlopen(req, timeout=15).read())
        except Exception:
            continue
        for p in posts:
            pid = p.get('id')
            if pid not in seen_ids:
                seen_ids.add(pid); posts_all.append(p)

    # 日付降順
    posts_all.sort(key=lambda x: x.get('date', ''), reverse=True)

    # title 厳格 filter: \bartist\b (ASCII境界) または日本語alias完全マッチ
    # re.ASCII で \w を [A-Za-z0-9_] に限定 → 日本語前後でも境界成立
    pat = re.compile(rf'\b{re.escape(artist)}\b', re.IGNORECASE | re.ASCII)
    filtered = []
    for p in posts_all:
        title = p.get('title', {}).get('rendered', '') or ''
        if pat.search(title) or any(a in title for a in aliases):
            filtered.append(p)
            if len(filtered) >= limit:
                break
    return filtered


def render_html(artist: str, profile: dict):
    """Profile JSON → (HTML, hero_photo_url, logo_url) tuple

    hero_photo_url: Wikipedia 集合写真。featured_media (og:image / page-top banner) として upload。
    logo_url: Wikimedia Commons logo file。inline `.ap-hero-photo` で表示 (logoが無ければhero_photo)。
    """
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

    # ── 関連記事 (Hero画像とarticles sectionで再利用) ──
    recent_posts = _fetch_recent_articles_for_artist(artist, limit=20)

    # Hero photo 優先順:
    #   1) profile['hero_photo'] (manual override)
    #   2) Wikipedia pageimage (公式集合写真)
    #   3) 関連記事 featured image (filter付き)
    manual_hero = profile.get('hero_photo', '').strip()
    if not manual_hero:
        try:
            from lib.wikipedia_image import get_artist_image
            manual_hero = get_artist_image(artist) or ''
        except Exception:
            manual_hero = ''

    # Hero photo: ネガティブ/clickbait/個人ソロ/他artistコラボを除いた記事から featured image を1枚採用
    NEG_KW = ('整形', '疑惑', '盗用', '事件', '事故', '訴訟', 'スキャンダル', '死亡',
              '病気', '入院', '引退', '解散', '脱退', '炎上', '中傷', '謝罪', '誹謗',
              '熱愛', '破局', '逮捕', '不仲', '降板', '離婚', '違反', '失言', '盗作',
              ' vs ', 'VS ', 'ＶＳ')
    member_names = []
    for m in members:
        for k in ('name_ja', 'name_en', 'real_name_en'):
            v = m.get(k)
            if v and len(v) >= 2:
                member_names.append(v)
    # 他artist名一覧 (PRIORITY_ARTISTS から自分以外、+ ASCII境界含む regex)
    other_artist_pats = []
    for a in PRIORITY_ARTISTS:
        if a['name'].lower() != artist.lower():
            other_artist_pats.append(re.compile(rf'\b{re.escape(a["name"])}\b', re.I | re.A))
            for alias in JA_ALIASES.get(a['slug'], []) + JA_ALIASES.get(a['name'].lower(), []):
                other_artist_pats.append(re.compile(re.escape(alias)))

    def _is_negative(post):
        title = (post.get('title', {}).get('rendered', '') or '')
        return any(k in title for k in NEG_KW)
    def _is_solo(post):
        title = (post.get('title', {}).get('rendered', '') or '')
        return any(n in title for n in member_names)
    def _is_collab(post):
        title = (post.get('title', {}).get('rendered', '') or '')
        return any(p.search(title) for p in other_artist_pats)

    # title が artist名 (or alias) で始まる記事 = グループ写真期待度最高
    artist_aliases_local = [artist] + JA_ALIASES.get(artist.lower(), []) + JA_ALIASES.get(slug if False else '', [])
    def _starts_with_artist(post):
        title = (post.get('title', {}).get('rendered', '') or '').lstrip('【「『[(')
        return any(title.lower().startswith(a.lower()) for a in artist_aliases_local)

    hero_photo = manual_hero  # manual override最優先
    # 優先度:
    #   1) artist名で始まる + ネガ・コラボ・ソロなし (グループ写真の可能性最大)
    #   2) artist名で始まる + ネガ・コラボなし
    #   3) ネガ・ソロ・コラボなし
    #   4) ネガ・コラボなし
    #   5) ネガなし
    #   6) 全件
    priority = (
        [p for p in recent_posts if _starts_with_artist(p) and not _is_negative(p) and not _is_collab(p) and not _is_solo(p)] +
        [p for p in recent_posts if _starts_with_artist(p) and not _is_negative(p) and not _is_collab(p)] +
        [p for p in recent_posts if not _is_negative(p) and not _is_solo(p) and not _is_collab(p)] +
        [p for p in recent_posts if not _is_negative(p) and not _is_collab(p)] +
        [p for p in recent_posts if not _is_negative(p)] +
        recent_posts
    )
    seen = set()
    ordered = []
    for p in priority:
        pid = p.get('id')
        if pid not in seen:
            seen.add(pid); ordered.append(p)
    # 記事grid もこの priority 順を採用 (artist関連性高い順)
    recent_posts = ordered

    # manual override がある場合は自動取得スキップ
    iterate = [] if manual_hero else ordered
    for p in iterate:
        emb = p.get('_embedded', {}).get('wp:featuredmedia', [])
        if emb and emb[0].get('source_url'):
            sizes = emb[0].get('media_details', {}).get('sizes', {})
            for sz in ('large', 'medium_large', 'full'):
                if sizes.get(sz, {}).get('source_url'):
                    hero_photo = sizes[sz]['source_url']
                    break
            if not hero_photo:
                hero_photo = emb[0]['source_url']
        if hero_photo:
            break

    # ── Logo取得 (inline表示用、Commons SVG/PNG) ──
    logo_url = ''
    try:
        from lib.wikipedia_image import get_artist_logo
        logo_url = get_artist_logo(artist) or ''
    except Exception:
        logo_url = ''

    # ── HERO (左column: logo + photo 縦並び / 右: info, wpautop汚染回避) ──
    stats_html = f'<span class="ap-stat">👥 {len(members)}名</span>'
    if fandom: stats_html += f'<span class="ap-stat">⭐ {fandom}</span>'
    if debut: stats_html += f'<span class="ap-stat">🎂 {_years_since(debut)}</span>'
    tagline = f'{agency}{(" ・ デビュー " + debut[:7].replace("-","年") + "月") if debut else ""}'
    summary_html = f'<p class="ap-hero-summary">{summary}</p>' if summary else ''

    # media column: logo (上) + photo (下) を縦並び。両方なければ avatar fallback
    media_parts = []
    if logo_url:
        media_parts.append(f'<div class="ap-hero-logo"><img src="{logo_url}" alt="{artist} ロゴ" loading="eager"/></div>')
    if hero_photo:
        media_parts.append(f'<div class="ap-hero-photo"><img src="{hero_photo}" alt="{artist}" loading="eager"/></div>')
    if media_parts:
        media_html = f'<div class="ap-hero-media">{"".join(media_parts)}</div>'
    else:
        media_html = f'<div class="ap-hero-avatar">{initial}</div>'

    parts.append(
        f'<div class="ap-hero" style="background:linear-gradient(135deg,{hero_grad[0]},{hero_grad[1]});">'
        f'<div class="ap-hero-inner">'
        f'<div class="ap-hero-badge">IDOL WIKI</div>'
        f'<div class="ap-hero-body">'
        f'{media_html}'
        f'<div class="ap-hero-info">'
        f'<h1 class="ap-hero-name">{artist}</h1>'
        f'<p class="ap-hero-tagline">{tagline}</p>'
        f'<div class="ap-hero-stats">{stats_html}</div>'
        f'{summary_html}'
        f'</div></div></div></div>'
    )

    parts.append('<div class="artist-profile">')
    parts.append(f'<p class="ap-updated">最終更新: {today}</p>')

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

    # ── メンバーカード grid (個別ページlink + 新フィールド表示) ──
    group_slug = artist.lower().replace(' ', '-')
    member_pages_enabled = bool(profile.get('member_pages_enabled'))
    if members:
        parts.append('<h2 class="ap-h2">👥 メンバー</h2>')
        member_cards = []
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
            mslug = _member_slug(name_en)
            member_url = f'/artist-{group_slug}-{mslug}/' if mslug else ''

            inner = (
                f'<div class="ap-member-avatar" style="background:linear-gradient(135deg,{grad[0]},{grad[1]});">{mi}</div>'
                f'<div class="ap-member-name">{display_name}</div>'
            )
            if sub_name: inner += f'<div class="ap-member-en">{sub_name}</div>'
            if birth:
                age_txt = f' ・ {age}歳' if age else ''
                inner += f'<div class="ap-member-birth">{_format_birth(birth)}{age_txt}</div>'
            if position: inner += f'<div class="ap-member-position">{position}</div>'

            # ── 新フィールド: 身長/血液型/MBTI を chip 形式で1行 ──
            stat_chips = []
            h = (m.get('height_cm') or '').strip()
            if h: stat_chips.append(f'<span class="ap-mb-chip">📏 {h}cm</span>')
            bt = (m.get('blood_type') or '').strip()
            if bt: stat_chips.append(f'<span class="ap-mb-chip">🩸 {bt}</span>')
            mbti = (m.get('mbti') or '').strip()
            if mbti: stat_chips.append(f'<span class="ap-mb-chip ap-mb-chip-mbti">🧠 {mbti}</span>')
            if stat_chips:
                inner += f'<div class="ap-member-chips">{"".join(stat_chips)}</div>'

            meta = []
            if real: meta.append(real)
            if natl: meta.append(natl)
            if meta: inner += f'<div class="ap-member-meta">{" ・ ".join(meta)}</div>'

            note = (m.get('note') or '').strip()
            if note:
                inner += f'<div class="ap-member-note">{note}</div>'

            # 個別ページへの link footer (実在グループのみ)
            if member_url and member_pages_enabled:
                inner += f'<a href="{member_url}" class="ap-member-link">▶ {display_name}のページ</a>'

            member_cards.append(f'<div class="ap-member-card">{inner}</div>')
        parts.append(f'<div class="ap-members-grid">{"".join(member_cards)}</div>')

    # ── ディスコグラフィー (single-line + compact card) ──
    disco = profile.get('discography_highlights', [])
    if disco:
        parts.append('<h2 class="ap-h2">🎵 主要ディスコグラフィー</h2>')
        type_meta = {
            'album': ('🎵', '#FF1493', 'アルバム'),
            'ep': ('💿', '#9B59B6', 'ミニ'),
            'single': ('🎶', '#00BCD4', 'シングル'),
            'japanese': ('🇯🇵', '#E91E63', '日本盤'),
            'ost': ('🎞️', '#FFB300', 'OST'),
        }
        disco_items = []
        for d in sorted(disco, key=lambda x: x.get('year', '9999'), reverse=True):
            t = d.get('type', '')
            icon, color, label = type_meta.get(t, ('📌', '#888', '他'))
            note = d.get('note', '')
            note_html = f' <span class="ap-disco-note">{note}</span>' if note else ''
            disco_items.append(
                f'<div class="ap-disco-item" style="border-left-color:{color};">'
                f'<span class="ap-disco-year">{d.get("year","")}</span>'
                f'<span class="ap-disco-title">{d.get("title","")}</span>'
                f'<span class="ap-disco-type" style="color:{color};">{icon} {label}</span>'
                f'{note_html}'
                f'</div>'
            )
        parts.append(f'<div class="ap-disco-list">{"".join(disco_items)}</div>')

    # ── 知っておきたいポイント (data から自動synthesis) ──
    facts = []
    if profile.get('fandom_meaning'):
        facts.append(('💡', 'ファンダム名の由来', profile['fandom_meaning']))
    if debut:
        debut_year = debut[:4]
        facts.append(('🎂', 'デビュー', f'{_format_birth(debut)}（{_years_since(debut)}）に{agency or "事務所"}からデビュー'))
    if members:
        ages = [int(_calc_age(m.get('birth', ''))) for m in members if _calc_age(m.get('birth', ''))]
        if ages:
            avg_age = round(sum(ages) / len(ages), 1)
            youngest = min(ages)
            oldest = max(ages)
            facts.append(('📊', 'メンバー年齢', f'平均 {avg_age}歳（最年少 {youngest}歳 / 最年長 {oldest}歳）'))
        # leader 推定
        leaders = [m.get('name_ja') or m.get('name_en') for m in members
                   if 'リーダー' in (m.get('position') or '')]
        if leaders:
            facts.append(('👑', 'リーダー', '・'.join(filter(None, leaders))))
        # メインボーカル
        main_vocals = [m.get('name_ja') or m.get('name_en') for m in members
                       if 'メインボーカル' in (m.get('position') or '') or 'メインボ' in (m.get('position') or '')]
        if main_vocals:
            facts.append(('🎤', 'メインボーカル', '・'.join(filter(None, main_vocals))))
    # JP aliases (カタカナ表記) を notable_aliases として表示
    aliases = JA_ALIASES.get(artist.lower(), [])
    if aliases:
        facts.append(('🇯🇵', '日本での通称', ' / '.join(aliases)))

    if facts:
        parts.append('<h2 class="ap-h2">💡 知っておきたいポイント</h2>')
        fact_items = []
        for icon, label, val in facts:
            fact_items.append(
                f'<div class="ap-fact-item">'
                f'<div class="ap-fact-icon">{icon}</div>'
                f'<div class="ap-fact-body"><div class="ap-fact-label">{label}</div>'
                f'<div class="ap-fact-val">{val}</div></div></div>'
            )
        parts.append(f'<div class="ap-fact-list">{"".join(fact_items)}</div>')

    # ── 公式SNS pill chips (single-line) ──
    links = profile.get('official_links', {}) or {}
    if any(links.values()):
        parts.append('<h2 class="ap-h2">🔗 公式SNS</h2>')
        sns_meta = {
            'twitter': ('𝕏', '#000', 'X'),
            'instagram': ('📷', 'linear-gradient(45deg,#feda75,#fa7e1e,#d62976,#962fbf,#4f5bd5)', 'Instagram'),
            'weverse': ('💜', '#7B1FA2', 'Weverse'),
            'youtube': ('▶', '#FF0000', 'YouTube'),
            'tiktok': ('🎵', '#000', 'TikTok'),
            'japan_official': ('🇯🇵', '#D62929', '日本公式'),
        }
        sns_chips = []
        for k in ['twitter', 'instagram', 'weverse', 'youtube', 'tiktok', 'japan_official']:
            v = links.get(k)
            if not v: continue
            icon, bg, label = sns_meta[k]
            sns_chips.append(
                f'<a href="{v}" target="_blank" rel="noopener" class="ap-sns-chip">'
                f'<span class="ap-sns-icon" style="background:{bg};">{icon}</span>'
                f'<span class="ap-sns-label">{label}</span>'
                f'</a>'
            )
        parts.append(f'<div class="ap-sns-chips">{"".join(sns_chips)}</div>')

    # ── 最新記事カード (5×4=最大20件、上で取得済み) ──
    if recent_posts:
        parts.append(f'<h2 class="ap-h2">📰 {artist} の最新記事</h2>')
        article_cards = []
        for post in recent_posts:
            title = post.get('title', {}).get('rendered', '')
            slug = post.get('slug', '')
            date_str = post.get('date', '')[:10].replace('-', '/')
            thumb = ''
            embedded = post.get('_embedded', {}).get('wp:featuredmedia', [])
            if embedded and embedded[0].get('source_url'):
                thumb = embedded[0]['source_url']
                sizes = embedded[0].get('media_details', {}).get('sizes', {})
                # 高画質優先: large > medium_large > full > medium
                for sz in ('large', 'medium_large', 'full'):
                    if sizes.get(sz, {}).get('source_url'):
                        thumb = sizes[sz]['source_url']
                        break
            thumb_html = (f'<img src="{thumb}" alt="{title}" loading="lazy"/>'
                          if thumb else '<div class="ap-article-noimg">📰</div>')
            article_cards.append(
                f'<a href="/{slug}/" class="ap-article-card">'
                f'<div class="ap-article-thumb">{thumb_html}</div>'
                f'<div class="ap-article-body">'
                f'<div class="ap-article-title">{title}</div>'
                f'<div class="ap-article-date">{date_str}</div>'
                f'</div></a>'
            )
        parts.append(f'<div class="ap-articles-grid">{"".join(article_cards)}</div>')

    # ── もっと詳しく (外部権威ソース) ──
    try:
        from lib.wikipedia_image import WIKI_TITLE_JA, WIKI_TITLE_EN
        wiki_ja_title = WIKI_TITLE_JA.get(artist, '')
        wiki_en_title = WIKI_TITLE_EN.get(artist, '')
    except Exception:
        wiki_ja_title = wiki_en_title = ''
    ext_chips = []
    if wiki_ja_title:
        wiki_url = f'https://ja.wikipedia.org/wiki/{urllib.parse.quote(wiki_ja_title)}'
        ext_chips.append(f'<a href="{wiki_url}" target="_blank" rel="noopener" class="ap-rel-chip ap-rel-wiki">📖 日本語版Wikipedia</a>')
    if wiki_en_title:
        wiki_en_url = f'https://en.wikipedia.org/wiki/{urllib.parse.quote(wiki_en_title)}'
        ext_chips.append(f'<a href="{wiki_en_url}" target="_blank" rel="noopener" class="ap-rel-chip ap-rel-wiki">🌐 English Wikipedia</a>')
    namu_url = f'https://namu.wiki/w/{urllib.parse.quote(artist)}'
    ext_chips.append(f'<a href="{namu_url}" target="_blank" rel="noopener" class="ap-rel-chip ap-rel-namu">🇰🇷 나무위키</a>')
    if ext_chips:
        parts.append('<h2 class="ap-h2">📚 もっと詳しく</h2>')
        parts.append(f'<div class="ap-rel-chips">{"".join(ext_chips)}</div>')

    # ── 関連 (single-line, pill style) ──
    parts.append('<h2 class="ap-h2">🔗 関連</h2>')
    rel_chips = (
        f'<a href="/release-calendar/" class="ap-rel-chip ap-rel-cal">📅 カムバック予定</a>'
        f'<a href="/?s={artist.replace(" ", "+")}" class="ap-rel-chip ap-rel-search">🔍 関連を全件検索</a>'
        f'<a href="/artists/" class="ap-rel-chip ap-rel-hub">🎤 他のアーティスト</a>'
    )
    parts.append(f'<div class="ap-rel-chips">{rel_chips}</div>')

    parts.append('</div>')  # /artist-profile

    # ── インラインCSS (Idol Wiki — namu風 compact + dense) ──
    parts.append('''<style>
.artist-profile,.ap-hero,.ap-hero *,.ap-h2{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Hiragino Sans","Noto Sans JP",sans-serif}

/* HERO — logo左 (200px), info右 (text白固定, theme override完封, ultra-compact) */
.ap-hero{border-radius:11px;padding:.6em .8em;margin:.15em 0 .35em;color:#fff;box-shadow:0 5px 18px rgba(0,0,0,.12);position:relative;overflow:hidden}
.ap-hero::before{content:"";position:absolute;inset:0;background:radial-gradient(circle at 25% 15%,rgba(255,255,255,.2),transparent 55%);pointer-events:none}
.ap-hero-inner{max-width:1280px;margin:0 auto;position:relative}
.ap-hero-badge{display:inline-block;background:rgba(255,255,255,.3);padding:.16em .65em;border-radius:4px;font-size:.6em;font-weight:800;letter-spacing:.18em;backdrop-filter:blur(8px);margin-bottom:.35em;text-transform:uppercase;color:#fff!important;text-shadow:0 1px 3px rgba(0,0,0,.3)}
.ap-hero-body{display:flex;align-items:center;gap:.75em;flex-wrap:wrap}
.ap-hero-avatar{width:46px;height:46px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:1.35em;font-weight:800;background:rgba(255,255,255,.18);backdrop-filter:blur(12px);border:2px solid rgba(255,255,255,.55);flex-shrink:0;letter-spacing:-.03em}
/* media column — logo(上) + photo(下) を縦並び、同サイズで揃える */
.ap-hero-media{display:flex;flex-direction:column;gap:.45em;width:200px;max-width:32%;flex-shrink:0}
.ap-hero-media .ap-hero-logo,.ap-hero-media .ap-hero-photo{width:100%!important;max-width:100%!important}
.ap-hero-photo{width:200px;max-width:32%;aspect-ratio:4/3;border-radius:9px;overflow:hidden;flex-shrink:0;box-shadow:0 5px 14px rgba(0,0,0,.22);border:2px solid rgba(255,255,255,.5);background:rgba(255,255,255,.08);display:flex;align-items:center;justify-content:center}
.ap-hero-photo img{max-width:100%;max-height:100%;width:auto;height:auto;object-fit:contain;display:block;image-rendering:-webkit-optimize-contrast}
/* logo box — 小型 + paddingタイト + 白背景 */
.ap-hero-logo{width:200px;max-width:32%;aspect-ratio:4/3;border-radius:9px;overflow:hidden;flex-shrink:0;box-shadow:0 5px 14px rgba(0,0,0,.18);border:1.5px solid rgba(255,255,255,.55);background:#fff;display:flex;align-items:center;justify-content:center;padding:.4em .55em}
.ap-hero-logo img{max-width:100%;max-height:100%;width:auto;height:auto;object-fit:contain;display:block}
.ap-hero-info{flex:1;min-width:220px;display:flex;flex-direction:column;justify-content:center}
/* === text-color hard override (article-body theme対策) === */
.ap-hero,.ap-hero *,.article-body .ap-hero,.article-body .ap-hero *{color:#fff!important}
.article-body h1.ap-hero-name,.ap-hero-name{font-size:1.75em!important;font-weight:800!important;margin:0 0 .05em!important;line-height:1.08!important;color:#fff!important;text-shadow:0 2px 14px rgba(0,0,0,.35),0 1px 3px rgba(0,0,0,.2)!important;letter-spacing:-.02em;border:0!important;padding:0!important}
.article-body p.ap-hero-tagline,.ap-hero-tagline{font-size:.85em!important;margin:0 0 .3em!important;font-weight:700!important;color:#fff!important;text-shadow:0 1px 4px rgba(0,0,0,.5),0 0 6px rgba(0,0,0,.3)!important;-webkit-font-smoothing:antialiased;border:0!important;padding:0!important;background:transparent!important;line-height:1.3!important}
.ap-hero-stats{display:flex;gap:.3em;flex-wrap:wrap;margin:0 0 .35em!important}
.ap-stat{background:rgba(255,255,255,.3)!important;padding:.2em .65em!important;border-radius:99px!important;font-size:.7em!important;font-weight:700!important;backdrop-filter:blur(8px);letter-spacing:.01em;color:#fff!important;text-shadow:0 1px 3px rgba(0,0,0,.25)!important;line-height:1.3!important}
.article-body p.ap-hero-summary,.ap-hero-summary{font-size:.85em!important;line-height:1.55!important;margin:0!important;color:#fff!important;font-weight:600!important;text-shadow:0 1px 4px rgba(0,0,0,.55),0 0 8px rgba(0,0,0,.35)!important;-webkit-font-smoothing:antialiased;border:0!important;padding:0!important;background:transparent!important}

.artist-profile{max-width:1280px;margin:0 auto;padding:0 .7em}
.ap-updated{color:#666;font-size:.72em;text-align:right;margin:.05em 0 .15em;letter-spacing:.04em}
.article-body h2.ap-h2,h2.ap-h2{font-size:1.15em!important;font-weight:800!important;margin:1.1em 0 .5em!important;color:#111!important;letter-spacing:-.01em!important;display:flex!important;align-items:center;gap:.4em;border:0!important;border-left:0!important;padding:0 0 .28em 0!important;border-bottom:2px solid #FF1493!important;line-height:1.25!important}
.article-body h2.ap-h2::after,h2.ap-h2::after{content:none}

/* 基本情報 */
.ap-info-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:.35em;margin:.3em 0 .2em}
.ap-info-item{background:#fafbfd;padding:.45em .75em;border-radius:7px;border-left:3px solid #FF1493}
.ap-info-item dt{font-size:.68em;font-weight:800;color:#444;letter-spacing:.05em;margin:0 0 .1em;text-transform:uppercase}
.ap-info-item dd{margin:0;font-size:.9em;color:#111;line-height:1.4;font-weight:500}
.ap-info-item dd small{color:#333;font-size:.82em;font-weight:400}

/* メンバー — visual card (note入り) */
.ap-members-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:.4em;margin:.3em 0 .2em}
.ap-member-card{background:#fff;border-radius:9px;padding:.55em .45em .5em;text-align:center;box-shadow:0 1px 3px rgba(0,0,0,.05);border:1px solid #ececec;transition:transform .18s,box-shadow .18s,border-color .18s}
.ap-member-card:hover{transform:translateY(-2px);box-shadow:0 6px 16px rgba(255,20,147,.13);border-color:#ffe0ed}
.ap-member-avatar{width:50px;height:50px;border-radius:50%;margin:0 auto .25em;display:flex;align-items:center;justify-content:center;font-size:1.3em;font-weight:800;color:#fff;box-shadow:0 2px 8px rgba(0,0,0,.12);letter-spacing:-.02em}
.ap-member-name{font-size:1em;font-weight:800;color:#111;line-height:1.15}
.ap-member-en{font-size:.68em;color:#444;margin-top:.05em;letter-spacing:.02em;font-weight:600}
.ap-member-birth{font-size:.7em;color:#222;margin-top:.22em;font-weight:600}
.ap-member-position{font-size:.7em;color:#222;margin-top:.12em;line-height:1.3;font-weight:500}
.ap-member-meta{font-size:.64em;color:#444;margin-top:.12em;line-height:1.3}
.ap-member-note{font-size:.68em;color:#333;margin-top:.35em;line-height:1.5;text-align:left;background:#fafbfd;border-radius:5px;padding:.3em .45em;border-left:2px solid #FF1493}
.ap-member-chips{display:flex;flex-wrap:wrap;gap:.22em;margin-top:.35em;justify-content:center}
.ap-mb-chip{display:inline-flex;align-items:center;gap:.2em;background:#fdf2f8;border:1px solid #ffd1e6;border-radius:99px;padding:.15em .5em;font-size:.62em;font-weight:700;color:#ad1457;letter-spacing:.01em;line-height:1.3}
.ap-mb-chip-mbti{background:linear-gradient(135deg,#fff8e1,#ffecb3);border-color:#ffd54f;color:#bf6f00}
.ap-member-link{display:block;margin-top:.45em;padding:.32em .5em;background:linear-gradient(135deg,#fce4ec,#f8bbd0);border-radius:6px;color:#ad1457!important;font-size:.68em;font-weight:700;text-decoration:none;text-align:center;letter-spacing:.01em;transition:transform .15s,box-shadow .15s}
.ap-member-link:hover{transform:translateY(-1px);box-shadow:0 3px 8px rgba(255,20,147,.18)}

/* 知っておきたいポイント */
.ap-fact-list{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:.35em;margin:.3em 0 .25em}
.ap-fact-item{display:flex;gap:.5em;align-items:flex-start;background:#fff;padding:.45em .7em;border-radius:7px;border:1px solid #f3f3f3;border-left:3px solid #9B59B6;box-shadow:0 1px 3px rgba(0,0,0,.04)}
.ap-fact-icon{font-size:1.1em;flex-shrink:0;line-height:1.3}
.ap-fact-body{flex:1;min-width:0}
.ap-fact-label{font-size:.68em;font-weight:800;color:#444;letter-spacing:.04em;text-transform:uppercase;margin-bottom:.1em}
.ap-fact-val{font-size:.85em;color:#111;line-height:1.5;font-weight:500}

/* ディスコ — title+type を1行、noteを2行目に */
.ap-disco-list{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:.3em;margin:.3em 0 .2em}
.ap-disco-item{display:grid;grid-template-columns:42px 1fr auto;column-gap:.55em;row-gap:.15em;padding:.4em .7em;background:#fafbfd;border-radius:7px;border-left:3px solid #ddd;font-size:.83em}
.ap-disco-year{font-weight:800;color:#222;font-size:.95em;align-self:center}
.ap-disco-title{color:#111;min-width:0;font-weight:700;line-height:1.3;word-break:break-word;align-self:center}
.ap-disco-type{font-size:.78em;font-weight:700;white-space:nowrap;align-self:center}
.ap-disco-note{grid-column:2 / -1;font-size:.8em;color:#333;line-height:1.45;margin:0}

/* SNS */
.ap-sns-chips{display:flex;flex-wrap:wrap;gap:.35em;margin:.3em 0 .3em}
.ap-sns-chip{display:inline-flex;align-items:center;gap:.4em;padding:.35em .75em .35em .35em;background:#fff;border:1px solid #eee;border-radius:99px;text-decoration:none;color:#222;font-size:.8em;font-weight:600;transition:transform .18s,border-color .18s,box-shadow .18s}
.ap-sns-chip:hover{transform:translateY(-1px);box-shadow:0 3px 10px rgba(0,0,0,.08);border-color:#FF1493}
.ap-sns-icon{width:22px;height:22px;border-radius:50%;display:flex;align-items:center;justify-content:center;color:#fff;font-size:.82em;font-weight:bold;flex-shrink:0}
.ap-sns-label{font-size:.9em}

/* 最新記事 — 5×4 = 最大20件 (desktop固定5列) */
.ap-articles-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:.4em;margin:.3em 0 .2em}
.ap-article-card{display:block;background:#fff;border-radius:7px;overflow:hidden;text-decoration:none;color:#222;box-shadow:0 1px 3px rgba(0,0,0,.05);border:1px solid #f3f3f3;transition:transform .18s,box-shadow .18s}
.ap-article-card:hover{transform:translateY(-2px);box-shadow:0 6px 14px rgba(255,20,147,.1)}
.ap-article-thumb{width:100%;aspect-ratio:16/10;overflow:hidden;background:linear-gradient(135deg,#ffe1ec,#fff8e1);display:flex;align-items:center;justify-content:center}
.ap-article-thumb img{width:100%;height:100%;object-fit:cover;display:block}
.ap-article-noimg{font-size:1.5em;opacity:.45}
.ap-article-body{padding:.4em .5em .45em}
.ap-article-title{font-size:.76em;font-weight:700;line-height:1.32;color:#111;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.ap-article-date{font-size:.62em;color:#555;margin-top:.2em;letter-spacing:.04em;font-weight:500}

/* 関連 */
.ap-rel-chips{display:flex;flex-wrap:wrap;gap:.35em;margin:.35em 0 .25em}
.ap-rel-chip{display:inline-flex;align-items:center;padding:.4em .85em;border-radius:99px;text-decoration:none;font-size:.8em;font-weight:600;transition:transform .18s;border:1px solid transparent}
.ap-rel-chip:hover{transform:translateY(-1px)}
.ap-rel-cal{background:linear-gradient(135deg,#fff8e1,#ffecb3);color:#a68000;border-color:#ffe082}
.ap-rel-search{background:linear-gradient(135deg,#e3f2fd,#bbdefb);color:#0d47a1;border-color:#90caf9}
.ap-rel-hub{background:linear-gradient(135deg,#fce4ec,#f8bbd0);color:#ad1457;border-color:#f48fb1}
.ap-rel-wiki{background:linear-gradient(135deg,#f5f5f5,#e0e0e0);color:#222;border-color:#bdbdbd}
.ap-rel-namu{background:linear-gradient(135deg,#e8f5e9,#c8e6c9);color:#1b5e20;border-color:#a5d6a7}

/* Tablet — 4列 */
@media (max-width:1024px){
  .ap-articles-grid{grid-template-columns:repeat(4,1fr)}
}

/* Mobile — hero は横並び維持 (logo小型化), summary はline-clamp:3 */
@media (max-width:600px){
  .ap-hero{padding:.55em .65em!important;border-radius:9px;margin:.1em 0 .3em!important}
  .ap-hero-badge{font-size:.55em;margin-bottom:.3em;padding:.14em .55em;letter-spacing:.14em}
  .ap-hero-avatar{width:40px;height:40px;font-size:1.15em}
  .ap-hero-body{flex-direction:row!important;gap:.55em!important;align-items:flex-start}
  .ap-hero-media{width:38%!important;max-width:38%!important;gap:.3em!important}
  .ap-hero-photo{width:100%!important;max-width:100%!important;aspect-ratio:4/3!important;border-radius:8px}
  .ap-hero-logo{width:100%!important;max-width:100%!important;margin:0!important;aspect-ratio:4/3!important;border-radius:8px!important;padding:.3em .4em!important;border-width:1px!important}
  .ap-hero-info{flex:1!important;min-width:0!important}
  .article-body h1.ap-hero-name,.ap-hero-name{font-size:1.18em!important;margin:0 0 .03em!important;line-height:1.1!important}
  .article-body p.ap-hero-tagline,.ap-hero-tagline{font-size:.7em!important;margin:0 0 .25em!important;line-height:1.25!important}
  .ap-hero-stats{margin:0 0 .25em!important;gap:.22em!important}
  .article-body p.ap-hero-summary,.ap-hero-summary{font-size:.7em!important;line-height:1.45!important}
  .ap-stat{font-size:.62em!important;padding:.16em .5em!important}
  .article-body h2.ap-h2,h2.ap-h2{font-size:1.02em!important;margin:.9em 0 .4em!important;padding-bottom:.25em!important}
  .artist-profile{padding:0 .55em}
  .ap-info-grid{grid-template-columns:repeat(2,1fr);gap:.35em}
  .ap-info-item{padding:.45em .65em}
  .ap-members-grid{grid-template-columns:repeat(2,1fr);gap:.4em}
  .ap-member-card{padding:.55em .4em .5em}
  .ap-member-avatar{width:46px;height:46px;font-size:1.2em;margin-bottom:.3em}
  .ap-member-name{font-size:.92em}
  .ap-member-en,.ap-member-birth,.ap-member-position{font-size:.7em}
  .ap-member-meta{font-size:.62em}
  .ap-member-note{font-size:.7em;padding:.3em .45em}
  .ap-disco-list{grid-template-columns:1fr;gap:.3em}
  .ap-disco-item{padding:.35em .55em;font-size:.78em}
  .ap-fact-list{grid-template-columns:1fr;gap:.3em}
  .ap-fact-item{padding:.45em .6em}
  .ap-fact-val{font-size:.76em}
  .ap-sns-chips{gap:.35em}
  .ap-sns-chip{font-size:.74em;padding:.32em .65em .32em .32em}
  .ap-sns-icon{width:20px;height:20px;font-size:.75em}
  .ap-articles-grid{grid-template-columns:repeat(2,1fr);gap:.35em}
  .ap-article-title{font-size:.7em}
  .ap-rel-chips{gap:.35em}
  .ap-rel-chip{font-size:.75em;padding:.4em .8em}
}
@media (max-width:380px){
  .ap-info-grid{grid-template-columns:1fr}
  .ap-members-grid{grid-template-columns:repeat(2,1fr)}
}
</style>''')
    return '\n'.join(parts), hero_photo, logo_url


def _build_meta_description(artist: str, profile: dict) -> str:
    """og:description / meta description 用クリーン文 (160字以内)"""
    summary = (profile.get('summary_ja') or '').strip()
    if summary:
        text = re.sub(r'\s+', ' ', summary)
        if len(text) > 158:
            text = text[:156].rstrip() + '…'
        return text
    # fallback
    members = profile.get('members') or []
    agency = profile.get('agency', '')
    debut = (profile.get('debut_date') or '')[:4]
    fandom = profile.get('fandom_name', '')
    parts = [f'{artist}のプロフィール']
    if agency: parts.append(f'所属事務所: {agency}')
    if debut: parts.append(f'デビュー: {debut}年')
    if members: parts.append(f'{len(members)}人組')
    if fandom: parts.append(f'ファンダム: {fandom}')
    return '。'.join(parts) + '。メンバー・代表曲・公式SNS・最新記事を網羅。'


def _build_member_schema_org(group_artist: str, group_slug: str, member: dict) -> str:
    """Schema.org Person JSON-LD for member page"""
    name_en = member.get('name_en', '')
    name_kr = member.get('name_kr', '')
    name_ja = member.get('name_ja', '')
    mslug = _member_slug(name_en)
    schema = {
        "@context": "https://schema.org",
        "@type": "Person",
        "name": name_en,
        "alternateName": name_ja or name_kr,
        "url": f"https://www.kpopjournal.tokyo/artist-{group_slug}-{mslug}/",
        "memberOf": {
            "@type": "MusicGroup",
            "name": group_artist,
            "url": f"https://www.kpopjournal.tokyo/artist-{group_slug}/",
        },
    }
    if member.get('birth'):
        schema["birthDate"] = member['birth']
    if member.get('nationality'):
        schema["nationality"] = member['nationality']
    ig = member.get('instagram_personal')
    if ig:
        schema["sameAs"] = [ig]
    return f'<script type="application/ld+json">{json.dumps(schema, ensure_ascii=False)}</script>'


def render_member_html(group_artist: str, group_slug: str, member: dict, profile: dict) -> tuple[str, str]:
    """個別メンバーページ HTML 生成。
    returns (html, hero_photo_url)
    """
    today = datetime.now(JST).strftime('%Y年%m月%d日')
    name_en = member.get('name_en', '')
    name_kr = member.get('name_kr', '')
    name_ja = member.get('name_ja', '')
    real = member.get('real_name_en', '')
    position = member.get('position', '')
    birth = member.get('birth', '')
    age = _calc_age(birth)
    natl = member.get('nationality', '')
    note = member.get('note', '')
    height = (member.get('height_cm') or '').strip()
    blood = (member.get('blood_type') or '').strip()
    mbti = (member.get('mbti') or '').strip()
    edu = (member.get('education') or '').strip()
    hobbies = (member.get('hobbies') or '').strip()
    solo = (member.get('solo_works') or '').strip()
    ig = (member.get('instagram_personal') or '').strip()

    mslug = _member_slug(name_en)
    display_name = name_ja or name_en
    member_idx = next((i for i, m in enumerate(profile.get('members', [])) if m.get('name_en') == name_en), 0)
    grad = _GRAD_POOL[(hash(group_artist) + member_idx) % len(_GRAD_POOL)]
    initial = (name_en or name_ja or '?')[0].upper()

    # メンバー画像取得を試行 (Wikipedia の各種 title pattern を試す)
    member_photo = ''
    try:
        from lib.wikipedia_image import _fetch_pageimage
        wiki_titles_to_try = [
            f"{name_en}_(singer)",
            f"{name_en}_({group_artist}_member)",
            f"{name_en}_({group_artist})",
            f"{name_en}_(rapper)",
            name_en,
        ]
        for wt in wiki_titles_to_try:
            for lang in ('en', 'ja'):
                try:
                    img = _fetch_pageimage(lang, wt)
                    if img:
                        member_photo = img
                        break
                except Exception:
                    continue
            if member_photo:
                break
    except Exception:
        pass

    parts = [_build_member_schema_org(group_artist, group_slug, member)]

    # ── HERO ──
    photo_html = (
        f'<div class="apm-hero-photo"><img src="{member_photo}" alt="{display_name}" loading="eager"/></div>'
        if member_photo else
        f'<div class="apm-hero-avatar" style="background:linear-gradient(135deg,{grad[0]},{grad[1]});">{initial}</div>'
    )
    stat_chips = []
    if birth: stat_chips.append(f'<span class="apm-stat">🎂 {age}歳</span>')
    if height: stat_chips.append(f'<span class="apm-stat">📏 {height}cm</span>')
    if blood: stat_chips.append(f'<span class="apm-stat">🩸 {blood}</span>')
    if mbti: stat_chips.append(f'<span class="apm-stat apm-stat-mbti">🧠 {mbti}</span>')
    if natl: stat_chips.append(f'<span class="apm-stat">🌍 {natl}</span>')

    sub_name_html = ''
    if name_en and name_en != display_name:
        sub_name_html += f'<p class="apm-hero-en">{name_en}</p>'
    if name_kr:
        sub_name_html += f'<p class="apm-hero-kr">{name_kr}</p>'

    parts.append(
        f'<div class="apm-hero" style="background:linear-gradient(135deg,{grad[0]},{grad[1]});">'
        f'<div class="apm-hero-inner">'
        f'<a href="/artist-{group_slug}/" class="apm-hero-back">← {group_artist} メンバー一覧へ</a>'
        f'<div class="apm-hero-body">'
        f'{photo_html}'
        f'<div class="apm-hero-info">'
        f'<div class="apm-hero-badge">IDOL WIKI · MEMBER</div>'
        f'<h1 class="apm-hero-name">{display_name}</h1>'
        f'{sub_name_html}'
        f'<p class="apm-hero-affiliation">{group_artist} ・ {position}</p>'
        f'<div class="apm-hero-stats">{"".join(stat_chips)}</div>'
        f'</div></div></div></div>'
    )

    parts.append('<div class="artist-profile">')
    parts.append(f'<p class="ap-updated">最終更新: {today}</p>')

    # ── プロフィール grid ──
    parts.append('<h2 class="ap-h2">📋 プロフィール</h2>')
    info_items = []
    if real and name_kr:
        info_items.append(f'<div class="ap-info-item"><dt>本名</dt><dd>{real} / {name_kr}</dd></div>')
    elif real:
        info_items.append(f'<div class="ap-info-item"><dt>本名</dt><dd>{real}</dd></div>')
    if birth:
        info_items.append(f'<div class="ap-info-item"><dt>生年月日</dt><dd>{_format_birth(birth)} <small>({age}歳)</small></dd></div>')
    if height:
        info_items.append(f'<div class="ap-info-item"><dt>身長</dt><dd>{height} cm</dd></div>')
    if blood:
        info_items.append(f'<div class="ap-info-item"><dt>血液型</dt><dd>{blood}型</dd></div>')
    if mbti:
        info_items.append(f'<div class="ap-info-item"><dt>MBTI</dt><dd>{mbti}</dd></div>')
    if natl:
        info_items.append(f'<div class="ap-info-item"><dt>国籍</dt><dd>{natl}</dd></div>')
    info_items.append(f'<div class="ap-info-item"><dt>所属</dt><dd><a href="/artist-{group_slug}/">{group_artist}</a></dd></div>')
    if position:
        info_items.append(f'<div class="ap-info-item"><dt>ポジション</dt><dd>{position}</dd></div>')
    if edu:
        info_items.append(f'<div class="ap-info-item"><dt>出身校</dt><dd>{edu}</dd></div>')
    if hobbies:
        info_items.append(f'<div class="ap-info-item"><dt>趣味</dt><dd>{hobbies}</dd></div>')
    parts.append(f'<dl class="ap-info-grid">{"".join(info_items)}</dl>')

    # ── プロフィール詳細 (note) ──
    if note:
        parts.append('<h2 class="ap-h2">💡 プロフィール詳細</h2>')
        parts.append(f'<div class="apm-bio">{note}</div>')

    # ── ソロ作品 ──
    if solo:
        parts.append('<h2 class="ap-h2">🎵 ソロ作品</h2>')
        works = [w.strip() for w in solo.split(',') if w.strip()]
        work_items = ''.join(f'<div class="apm-solo-item">{w}</div>' for w in works)
        parts.append(f'<div class="apm-solo-list">{work_items}</div>')

    # ── 公式SNS ──
    sns_chips = []
    if ig:
        sns_chips.append(
            f'<a href="{ig}" target="_blank" rel="noopener" class="ap-sns-chip">'
            f'<span class="ap-sns-icon" style="background:linear-gradient(45deg,#feda75,#fa7e1e,#d62976,#962fbf,#4f5bd5);">📷</span>'
            f'<span class="ap-sns-label">個人 Instagram</span></a>'
        )
    # group SNS chips をフォールバック
    g_links = profile.get('official_links', {}) or {}
    g_meta = {
        'twitter': ('𝕏', '#000', f'{group_artist} 公式X'),
        'instagram': ('📷', 'linear-gradient(45deg,#feda75,#fa7e1e,#d62976,#962fbf,#4f5bd5)', f'{group_artist} 公式IG'),
        'youtube': ('▶', '#FF0000', f'{group_artist} 公式YouTube'),
    }
    for k in ['twitter', 'instagram', 'youtube']:
        v = g_links.get(k)
        if v:
            icon, bg, label = g_meta[k]
            sns_chips.append(
                f'<a href="{v}" target="_blank" rel="noopener" class="ap-sns-chip">'
                f'<span class="ap-sns-icon" style="background:{bg};">{icon}</span>'
                f'<span class="ap-sns-label">{label}</span></a>'
            )
    if sns_chips:
        parts.append('<h2 class="ap-h2">🔗 公式SNS</h2>')
        parts.append(f'<div class="ap-sns-chips">{"".join(sns_chips)}</div>')

    # ── 関連記事 (member名で検索) ──
    recent = _fetch_recent_articles_for_artist(display_name, limit=10)
    if recent:
        parts.append(f'<h2 class="ap-h2">📰 {display_name} 関連記事</h2>')
        article_cards = []
        for post in recent:
            title = post.get('title', {}).get('rendered', '')
            slug = post.get('slug', '')
            date_str = post.get('date', '')[:10].replace('-', '/')
            thumb = ''
            embedded = post.get('_embedded', {}).get('wp:featuredmedia', [])
            if embedded and embedded[0].get('source_url'):
                thumb = embedded[0]['source_url']
                sizes = embedded[0].get('media_details', {}).get('sizes', {})
                for sz in ('large', 'medium_large', 'full'):
                    if sizes.get(sz, {}).get('source_url'):
                        thumb = sizes[sz]['source_url']
                        break
            thumb_html = (f'<img src="{thumb}" alt="{title}" loading="lazy"/>'
                          if thumb else '<div class="ap-article-noimg">📰</div>')
            article_cards.append(
                f'<a href="/{slug}/" class="ap-article-card">'
                f'<div class="ap-article-thumb">{thumb_html}</div>'
                f'<div class="ap-article-body">'
                f'<div class="ap-article-title">{title}</div>'
                f'<div class="ap-article-date">{date_str}</div>'
                f'</div></a>'
            )
        parts.append(f'<div class="ap-articles-grid">{"".join(article_cards)}</div>')

    # ── 同グループの他メンバー ──
    other_members = [m for m in profile.get('members', []) if m.get('name_en') != name_en]
    if other_members:
        parts.append(f'<h2 class="ap-h2">👥 {group_artist} の他のメンバー</h2>')
        omc = []
        for i, om in enumerate(other_members):
            om_name_ja = om.get('name_ja', '')
            om_name_en = om.get('name_en', '')
            om_disp = om_name_ja or om_name_en
            om_mi = (om_name_en or om_name_ja or '?')[0].upper()
            om_grad = _GRAD_POOL[(hash(group_artist) + i + 1) % len(_GRAD_POOL)]
            om_slug = _member_slug(om_name_en)
            om_pos = om.get('position', '')
            omc.append(
                f'<a href="/artist-{group_slug}-{om_slug}/" class="ap-member-card apm-other-card">'
                f'<div class="ap-member-avatar" style="background:linear-gradient(135deg,{om_grad[0]},{om_grad[1]});">{om_mi}</div>'
                f'<div class="ap-member-name">{om_disp}</div>'
                f'{f"<div class=ap-member-en>{om_name_en}</div>" if om_name_ja and om_name_en else ""}'
                f'<div class="ap-member-position">{om_pos}</div>'
                f'</a>'
            )
        parts.append(f'<div class="ap-members-grid">{"".join(omc)}</div>')

    # ── 関連 ──
    parts.append('<h2 class="ap-h2">🔗 関連</h2>')
    parts.append(
        f'<div class="ap-rel-chips">'
        f'<a href="/artist-{group_slug}/" class="ap-rel-chip ap-rel-hub">🎤 {group_artist} グループページ</a>'
        f'<a href="/?s={display_name}" class="ap-rel-chip ap-rel-search">🔍 {display_name} 関連を全件検索</a>'
        f'<a href="/release-calendar/" class="ap-rel-chip ap-rel-cal">📅 カムバック予定</a>'
        f'</div>'
    )

    parts.append('</div>')  # /artist-profile

    # ── インラインCSS (member page) ──
    parts.append('''<style>
.artist-profile,.apm-hero,.apm-hero *,.ap-h2{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Hiragino Sans","Noto Sans JP",sans-serif}

/* HERO (member) — back link + photo + info */
.apm-hero{border-radius:11px;padding:.7em .9em .8em;margin:.15em 0 .45em;color:#fff;box-shadow:0 5px 18px rgba(0,0,0,.12);position:relative;overflow:hidden}
.apm-hero::before{content:"";position:absolute;inset:0;background:radial-gradient(circle at 25% 15%,rgba(255,255,255,.2),transparent 55%);pointer-events:none}
.apm-hero-inner{max-width:1280px;margin:0 auto;position:relative}
.apm-hero-back{display:inline-block;color:#fff!important;font-size:.72em;font-weight:700;margin-bottom:.5em;text-decoration:none;background:rgba(255,255,255,.22);padding:.28em .8em;border-radius:99px;backdrop-filter:blur(8px);text-shadow:0 1px 3px rgba(0,0,0,.25);letter-spacing:.02em;transition:transform .15s,background .15s}
.apm-hero-back:hover{transform:translateX(-2px);background:rgba(255,255,255,.32)}
.apm-hero-body{display:flex;align-items:center;gap:.85em;flex-wrap:wrap}
.apm-hero-photo{width:200px;max-width:32%;aspect-ratio:4/5;border-radius:9px;overflow:hidden;flex-shrink:0;box-shadow:0 5px 14px rgba(0,0,0,.22);border:2px solid rgba(255,255,255,.55);background:rgba(255,255,255,.08);display:flex;align-items:center;justify-content:center}
.apm-hero-photo img{width:100%;height:100%;object-fit:cover;object-position:center 20%;display:block;image-rendering:-webkit-optimize-contrast}
.apm-hero-avatar{width:96px;height:96px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:2.4em;font-weight:800;color:#fff;background:rgba(255,255,255,.18);backdrop-filter:blur(12px);border:2px solid rgba(255,255,255,.55);flex-shrink:0;letter-spacing:-.03em;box-shadow:0 5px 14px rgba(0,0,0,.18)}
.apm-hero-info{flex:1;min-width:240px;display:flex;flex-direction:column;justify-content:center}
.apm-hero-badge{display:inline-block;background:rgba(255,255,255,.3);padding:.16em .65em;border-radius:4px;font-size:.58em;font-weight:800;letter-spacing:.18em;backdrop-filter:blur(8px);margin-bottom:.35em;text-transform:uppercase;color:#fff!important;text-shadow:0 1px 3px rgba(0,0,0,.3);align-self:flex-start}
.article-body h1.apm-hero-name,.apm-hero-name{font-size:2em!important;font-weight:800!important;margin:0 0 .05em!important;line-height:1.08!important;color:#fff!important;text-shadow:0 2px 14px rgba(0,0,0,.4),0 1px 3px rgba(0,0,0,.25)!important;letter-spacing:-.02em;border:0!important;padding:0!important}
.article-body p.apm-hero-en,.apm-hero-en{font-size:.85em!important;margin:0 0 .05em!important;font-weight:600!important;color:#fff!important;opacity:.95;text-shadow:0 1px 3px rgba(0,0,0,.4)!important;letter-spacing:.02em;border:0!important;padding:0!important;background:transparent!important}
.article-body p.apm-hero-kr,.apm-hero-kr{font-size:.78em!important;margin:0 0 .25em!important;font-weight:600!important;color:#fff!important;opacity:.85;text-shadow:0 1px 3px rgba(0,0,0,.4)!important;border:0!important;padding:0!important;background:transparent!important}
.article-body p.apm-hero-affiliation,.apm-hero-affiliation{font-size:.78em!important;margin:0 0 .4em!important;font-weight:600!important;color:#fff!important;text-shadow:0 1px 3px rgba(0,0,0,.45)!important;border:0!important;padding:0!important;background:transparent!important;line-height:1.3!important}
.apm-hero-stats{display:flex;gap:.3em;flex-wrap:wrap;margin:0!important}
.apm-stat{background:rgba(255,255,255,.3);padding:.22em .65em;border-radius:99px;font-size:.7em;font-weight:700;backdrop-filter:blur(8px);letter-spacing:.01em;color:#fff!important;text-shadow:0 1px 3px rgba(0,0,0,.25);line-height:1.3}
.apm-stat-mbti{background:linear-gradient(135deg,rgba(255,243,176,.4),rgba(255,213,79,.4));border:1px solid rgba(255,213,79,.5)}

/* Member-page sections */
.apm-bio{background:#fafbfd;padding:.8em 1em;border-radius:8px;border-left:3px solid #FF1493;color:#222;line-height:1.7;font-size:.92em;margin:.3em 0 .3em}
.apm-solo-list{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:.35em;margin:.3em 0 .3em}
.apm-solo-item{background:linear-gradient(135deg,#fff8fc,#fdf0f9);padding:.5em .8em;border-radius:7px;border-left:3px solid #9B59B6;font-size:.88em;color:#222;font-weight:600;line-height:1.4}

/* Other-members link card override */
.apm-other-card{cursor:pointer;color:#222!important;text-decoration:none!important}
.apm-other-card:hover{box-shadow:0 6px 16px rgba(255,20,147,.18);border-color:#ffb6d5}

/* Mobile */
@media (max-width:600px){
  .apm-hero{padding:.55em .7em!important;border-radius:9px;margin:.1em 0 .35em!important}
  .apm-hero-back{font-size:.62em;padding:.22em .6em;margin-bottom:.4em}
  .apm-hero-body{flex-direction:row!important;gap:.6em!important;align-items:flex-start}
  .apm-hero-photo{width:36%!important;max-width:36%!important;aspect-ratio:4/5!important;border-radius:8px}
  .apm-hero-avatar{width:64px!important;height:64px!important;font-size:1.6em!important}
  .apm-hero-info{flex:1!important;min-width:0!important}
  .apm-hero-badge{font-size:.52em;margin-bottom:.3em}
  .article-body h1.apm-hero-name,.apm-hero-name{font-size:1.3em!important}
  .article-body p.apm-hero-en,.apm-hero-en{font-size:.72em!important}
  .article-body p.apm-hero-kr,.apm-hero-kr{font-size:.7em!important}
  .article-body p.apm-hero-affiliation,.apm-hero-affiliation{font-size:.68em!important;margin-bottom:.3em!important}
  .apm-stat{font-size:.6em;padding:.18em .5em}
  .apm-bio{padding:.6em .75em;font-size:.85em}
  .apm-solo-list{grid-template-columns:1fr;gap:.25em}
  .apm-solo-item{padding:.4em .65em;font-size:.82em}
}
</style>''')

    return '\n'.join(parts), member_photo


def _ensure_featured_media(artist: str, slug: str, profile: dict, hero_photo_url: str) -> int:
    """Wikipedia/外部 hero画像を WPメディアにアップロード→ media_id を返す
    すでにアップ済み (filename hash 一致) なら再利用。失敗時は 0。
    """
    if not hero_photo_url:
        return 0
    try:
        from lib.wp_image_uploader import download_and_upload_to_wp
        # 最高解像度を取得するため Special:FilePath にリダイレクト解決
        # (thumb URL の filename を取り出して原寸版を取得)
        candidates = [hero_photo_url]
        m = re.search(r'/thumb/[^/]+/[^/]+/([^/]+?)/\d+px-', hero_photo_url)
        if m:
            # thumb URL内 filenameは既にURL encoded (%2C, %28 等) — 二重 encode を避ける
            filename = m.group(1)
            for lang in ('en', 'ja'):
                candidates.insert(0,
                    f'https://{lang}.wikipedia.org/wiki/Special:FilePath/{filename}')
        r = None
        for c in candidates:
            r = download_and_upload_to_wp(c, article_title=f'idolwiki_{slug}')
            if r and r.get('media_id'):
                break
        if r and r.get('media_id'):
            mid = r['media_id']
            # alt_text を artist 名に更新
            try:
                req = urllib.request.Request(
                    f'https://www.kpopjournal.tokyo/wp-json/wp/v2/media/{mid}',
                    data=json.dumps({'alt_text': f'{artist} 公式集合写真'}).encode(),
                    method='POST',
                    headers={'Authorization': f'Basic {AUTH}', 'Content-Type': 'application/json'})
                urllib.request.urlopen(req, timeout=15).read()
            except Exception:
                pass
            return mid
    except Exception as e:
        print(f"  hero upload err: {e}", flush=True)
    return 0


def find_or_create_profile_page(slug: str, artist: str, html: str,
                                profile: dict, hero_photo_url: str = '') -> int:
    page_slug = f'artist-{slug}'
    title = f'Idol Wiki | {artist}'
    excerpt = _build_meta_description(artist, profile)

    # find existing
    req = urllib.request.Request(
        f'https://www.kpopjournal.tokyo/wp-json/wp/v2/pages?slug={page_slug}&_fields=id,featured_media',
        headers={'Authorization': f'Basic {AUTH}'})
    try:
        existing = json.loads(urllib.request.urlopen(req, timeout=15).read())
    except Exception:
        existing = []

    # wpautop 汚染回避: 改行を除去 + Gutenberg HTML block で wrap
    # (WPは <!-- wp:html --> block 内のHTMLに自動 <p> を挿入しない)
    html_oneline = re.sub(r'\n+', '', html.strip())
    wrapped = f'<!-- wp:html -->{html_oneline}<!-- /wp:html -->'

    payload = {
        'title': title,
        'content': wrapped,
        'excerpt': excerpt,
        'status': 'publish',
        'slug': page_slug,
    }

    # featured_media = Wikipedia hero (本人画像) を upload → og:image + Next.js page-top banner
    # inline は logo 表示で重複しない (banner=本人画像 / inline=ロゴ)
    if hero_photo_url and 'wikipedia' in hero_photo_url:
        existing_mid = (existing[0].get('featured_media', 0) if existing else 0)
        need_upload = True
        if existing_mid:
            try:
                m = json.loads(urllib.request.urlopen(urllib.request.Request(
                    f'https://www.kpopjournal.tokyo/wp-json/wp/v2/media/{existing_mid}?_fields=source_url',
                    headers={'Authorization': f'Basic {AUTH}'}), timeout=10).read())
                src = m.get('source_url', '')
                # 既に idolwiki_ プレフィックスならスキップ (idempotent)
                if 'buzzlab_idolwiki_' in src:
                    need_upload = False
                    payload['featured_media'] = existing_mid
            except Exception:
                pass
        if need_upload:
            mid = _ensure_featured_media(artist, slug, profile, hero_photo_url)
            if mid:
                payload['featured_media'] = mid
            else:
                payload['featured_media'] = 0
    else:
        payload['featured_media'] = 0

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


def find_or_create_member_page(group_slug: str, group_artist: str,
                                member: dict, html: str, profile: dict,
                                hero_photo_url: str = '') -> int:
    """個別メンバー用 WP page を find/create。URL: /artist-{group_slug}-{member_slug}/"""
    name_en = member.get('name_en', '')
    name_ja = member.get('name_ja', '')
    display_name = name_ja or name_en
    mslug = _member_slug(name_en)
    if not mslug:
        return 0
    page_slug = f'artist-{group_slug}-{mslug}'
    title = f'{display_name} (BLACKPINK) プロフィール・身長・MBTI・誕生日' if group_artist == 'BLACKPINK' else f'{display_name} ({group_artist}) プロフィール・身長・MBTI・誕生日'

    # excerpt
    parts_ex = [f'{display_name}（{group_artist}）のプロフィール']
    if member.get('birth'):
        parts_ex.append(f'生年月日: {_format_birth(member["birth"])}')
    if member.get('height_cm'): parts_ex.append(f'身長: {member["height_cm"]}cm')
    if member.get('blood_type'): parts_ex.append(f'血液型: {member["blood_type"]}型')
    if member.get('mbti'): parts_ex.append(f'MBTI: {member["mbti"]}')
    excerpt = '。'.join(parts_ex) + '。本名・出身校・趣味・ソロ作品まで網羅。'
    if len(excerpt) > 158:
        excerpt = excerpt[:156] + '…'

    # find existing
    req = urllib.request.Request(
        f'https://www.kpopjournal.tokyo/wp-json/wp/v2/pages?slug={page_slug}&_fields=id,featured_media',
        headers={'Authorization': f'Basic {AUTH}'})
    try:
        existing = json.loads(urllib.request.urlopen(req, timeout=15).read())
    except Exception:
        existing = []

    html_oneline = re.sub(r'\n+', '', html.strip())
    wrapped = f'<!-- wp:html -->{html_oneline}<!-- /wp:html -->'

    payload = {
        'title': title,
        'content': wrapped,
        'excerpt': excerpt,
        'status': 'publish',
        'slug': page_slug,
    }

    # featured_media (個別メンバーの Wikipedia photo upload)
    if hero_photo_url and 'wikipedia' in hero_photo_url:
        existing_mid = (existing[0].get('featured_media', 0) if existing else 0)
        need_upload = True
        if existing_mid:
            try:
                m = json.loads(urllib.request.urlopen(urllib.request.Request(
                    f'https://www.kpopjournal.tokyo/wp-json/wp/v2/media/{existing_mid}?_fields=source_url',
                    headers={'Authorization': f'Basic {AUTH}'}), timeout=10).read())
                src = m.get('source_url', '')
                if f'idolwiki_member_{mslug}' in src:
                    need_upload = False
                    payload['featured_media'] = existing_mid
            except Exception:
                pass
        if need_upload:
            try:
                from lib.wp_image_uploader import download_and_upload_to_wp
                candidates = [hero_photo_url]
                mm = re.search(r'/thumb/[^/]+/[^/]+/([^/]+?)/\d+px-', hero_photo_url)
                if mm:
                    filename = mm.group(1)
                    for lang in ('en', 'ja'):
                        candidates.insert(0, f'https://{lang}.wikipedia.org/wiki/Special:FilePath/{filename}')
                r = None
                for c in candidates:
                    r = download_and_upload_to_wp(c, article_title=f'idolwiki_member_{mslug}')
                    if r and r.get('media_id'):
                        break
                if r and r.get('media_id'):
                    mid = r['media_id']
                    try:
                        urllib.request.urlopen(urllib.request.Request(
                            f'https://www.kpopjournal.tokyo/wp-json/wp/v2/media/{mid}',
                            data=json.dumps({'alt_text': f'{display_name} ({group_artist}) 写真'}).encode(),
                            method='POST',
                            headers={'Authorization': f'Basic {AUTH}', 'Content-Type': 'application/json'}),
                            timeout=15).read()
                    except Exception:
                        pass
                    payload['featured_media'] = mid
            except Exception as e:
                print(f"    member photo upload err: {e}", flush=True)

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
        print(f"  WP publish err ({display_name}): {e}", flush=True)
        return 0


def build_member_pages(group_artist: str, group_slug: str) -> int:
    """指定グループの全メンバー個別ページを生成 + publish。returns success count."""
    json_path = PROFILE_DIR / f'{group_slug}.json'
    if not json_path.exists():
        print(f"  ✗ no JSON: {json_path}", flush=True)
        return 0
    profile = json.loads(json_path.read_text(encoding='utf-8'))
    members = profile.get('members', []) or []
    if not members:
        return 0

    print(f"  building {len(members)} member pages for {group_artist}", flush=True)
    success = 0
    for m in members:
        name_en = m.get('name_en', '')
        if not name_en:
            continue
        mslug = _member_slug(name_en)
        print(f"    → {m.get('name_ja', name_en)} (/artist-{group_slug}-{mslug}/)", flush=True)
        html, photo = render_member_html(group_artist, group_slug, m, profile)
        pid = find_or_create_member_page(group_slug, group_artist, m, html, profile, photo)
        if pid > 0:
            success += 1
            # frontend cache purge + GSC
            try:
                from lib.frontend_cache import purge_paths
                purge_paths([f'/artist-{group_slug}-{mslug}/'])
            except Exception:
                pass
            try:
                from lib.gsc_indexing import notify_url_updated
                notify_url_updated(f'https://www.kpopjournal.tokyo/artist-{group_slug}-{mslug}/')
            except Exception:
                pass
        print(f"      page_id={pid}", flush=True)
    return success


def _fetch_wikipedia_facts(artist: str) -> dict:
    """Wikipedia infobox から birth_date / real_name (English) を抽出。
    LLM hallucination 検出のための ground truth として使用。"""
    import urllib.parse as _up
    try:
        url = f'https://en.wikipedia.org/wiki/{_up.quote(artist.replace(" ", "_"))}'
        req = urllib.request.Request(url, headers={'User-Agent': 'KPJ-Verify/1.0'})
        with urllib.request.urlopen(req, timeout=15) as r:
            html = r.read().decode('utf-8', errors='ignore')
    except Exception:
        return {}
    facts = {}
    # birth date: <span class="bday">YYYY-MM-DD</span> (hCard microformat)
    m = re.search(r'<span class="bday">(\d{4}-\d{2}-\d{2})</span>', html)
    if m:
        facts['birth_date'] = m.group(1)
    # real name: infobox th "Born" の隣の td
    m = re.search(r'<th[^>]*>Born</th>\s*<td[^>]*>(.*?)</td>', html, re.S)
    if m:
        born_html = m.group(1)
        # 最初の <a href="/wiki/...">Name</a> もしくは plain text 名前
        n = re.search(r'<a [^>]*>([A-Z][a-z]+(?: [A-Z][a-z]+)+)</a>', born_html)
        if not n:
            n = re.search(r'>([A-Z][a-z]+(?: [A-Z][a-z]+)+)<', born_html)
        if n:
            facts['real_name_en_wikipedia'] = n.group(1)
    return facts


def _check_hallucination(profile: dict, wiki_facts: dict) -> list[str]:
    """profile (LLM 出力) と Wikipedia 確定値の主要 field 不一致を検出。
    Returns: list of discrepancy descriptions (空なら no hallucination)。"""
    if not wiki_facts:
        return []  # Wikipedia 取れない → 検証 skip
    issues = []
    members = profile.get('members') or []
    if not members:
        return issues
    # 1st member の birth/real_name と比較 (solo artist 想定、group も主役)
    m = members[0]
    wiki_birth = wiki_facts.get('birth_date')
    llm_birth = m.get('birth') or ''
    if wiki_birth and llm_birth and wiki_birth != llm_birth:
        issues.append(f"birth_date: LLM={llm_birth!r} vs Wikipedia={wiki_birth!r}")
    wiki_realname = wiki_facts.get('real_name_en_wikipedia', '').strip()
    llm_realname = (m.get('real_name_en') or '').strip()
    if wiki_realname and llm_realname:
        # 表記揺れ吸収のため lowercase + space 削除で比較
        norm = lambda s: re.sub(r'[-\s]+', '', s.lower())
        if norm(wiki_realname) != norm(llm_realname):
            issues.append(
                f"real_name_en: LLM={llm_realname!r} vs Wikipedia={wiki_realname!r}")
    return issues


def build_one(client, artist: str, slug: str) -> bool:
    print(f"[{artist}] fetching profile...", flush=True)
    profile = fetch_profile(client, artist)
    if not profile or not profile.get('members'):
        print(f"  ✗ skipped (no data)", flush=True)
        return False

    n_members = len(profile.get('members', []))
    print(f"  ✓ agency={profile.get('agency','?')} members={n_members}", flush=True)

    # 2nd call: 個人プロフィール (身長/MBTI/学歴等) を別 API call で取得
    print(f"  fetching member personal details...", flush=True)
    details = fetch_member_details(client, artist, profile.get('members', []))
    profile = _merge_member_details(profile, details)
    n_with_detail = sum(1 for m in profile.get('members', []) if m.get('mbti') or m.get('height_cm') or m.get('blood_type'))
    print(f"  ✓ detail filled: {n_with_detail}/{n_members}", flush=True)

    # 2026-05-15: Wikipedia diff hallucination guard
    # niche artist (Hyolyn / Aiki / SeeYa 等) で LLM web search が
    # 本名/生年月日を捏造する事故への防壁
    wiki_facts = _fetch_wikipedia_facts(artist)
    discrepancies = _check_hallucination(profile, wiki_facts)
    if discrepancies:
        print(f"  ⚠ HALLUCINATION ALERT: {discrepancies}", flush=True)
        # quarantine: 既存 JSON を上書きせず *.hallucination_quarantine.json に保存
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        quarantine_path = PROFILE_DIR / f'{slug}.hallucination_quarantine.json'
        profile['_hallucination_alert'] = discrepancies
        profile['_wikipedia_ground_truth'] = wiki_facts
        with open(quarantine_path, 'w', encoding='utf-8') as f:
            json.dump(profile, f, ensure_ascii=False, indent=2)
        print(f"  quarantined → {quarantine_path} (既存 JSON は上書き skip)", flush=True)
        return False  # quarantine 時は page render も skip

    # Save JSON
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    out_path = PROFILE_DIR / f'{slug}.json'
    profile['_last_updated'] = datetime.now(JST).isoformat()
    if wiki_facts:
        profile['_wikipedia_verified'] = True
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)
    print(f"  saved {out_path}", flush=True)

    # Render + publish
    html, hero_photo, _logo = render_html(artist, profile)
    page_id = find_or_create_profile_page(slug, artist, html, profile, hero_photo)
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
    slugs = sorted(p.stem for p in PROFILE_DIR.glob('*.json'))
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


def render_only_one(artist: str, slug: str) -> bool:
    """既存 profile JSON から HTML だけ再生成して publish (Claude API skip)"""
    json_path = PROFILE_DIR / f'{slug}.json'
    if not json_path.exists():
        print(f"  ✗ no JSON: {json_path}", flush=True)
        return False
    profile = json.loads(json_path.read_text(encoding='utf-8'))
    html, hero_photo, _logo = render_html(artist, profile)
    page_id = find_or_create_profile_page(slug, artist, html, profile, hero_photo)
    print(f"  page_id={page_id} URL=https://www.kpopjournal.tokyo/artist-{slug}/", flush=True)
    try:
        from lib.frontend_cache import purge_paths
        purge_paths([f'/artist-{slug}/'])
    except Exception:
        pass
    return page_id > 0


def main():
    sys.stdout.reconfigure(line_buffering=True)
    args = sys.argv[1:]
    if '--help' in args or '-h' in args:
        print('usage: python3 -m pipeline.profile_wiki_builder [--render-only|--members] [artist_slug ...]')
        print('  --render-only  既存JSONからHTML再生成のみ (Claude API skip)')
        print('  --members      member個別page生成')
        print('  artist_slug    PRIORITY_ARTISTS の slug or name (省略時は全件)')
        sys.exit(0)
    render_only = '--render-only' in args
    members_only = '--members' in args
    if render_only:
        args = [a for a in args if a != '--render-only']
    if members_only:
        args = [a for a in args if a != '--members']

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
    elif render_only or members_only:
        # 単独 → 既存JSON全件
        targets = []
        slug_to_name = {a['slug']: a['name'] for a in PRIORITY_ARTISTS}
        for p in sorted(PROFILE_DIR.glob('*.json')):
            slug = p.stem
            name = slug_to_name.get(slug, slug)
            targets.append({'name': name, 'slug': slug})
    else:
        targets = PRIORITY_ARTISTS

    if members_only:
        mode = 'MEMBERS-ONLY'
    elif render_only:
        mode = 'RENDER-ONLY'
    else:
        mode = 'FULL'
    print(f"[{mode}] {len(targets)} artists", flush=True)
    client = None if (render_only or members_only) else anthropic.Anthropic()

    success = 0
    member_success = 0
    for i, art in enumerate(targets, 1):
        print(f"\n[{i}/{len(targets)}] {art['name']}", flush=True)
        if members_only:
            n = build_member_pages(art['name'], art['slug'])
            member_success += n
            print(f"  ✓ {n} member pages published", flush=True)
        elif render_only:
            if render_only_one(art['name'], art['slug']):
                success += 1
        else:
            if build_one(client, art['name'], art['slug']):
                success += 1

    if members_only:
        print(f"\n=== Done: {member_success} member pages succeeded ===", flush=True)
    else:
        print(f"\n=== Done: {success}/{len(targets)} succeeded ===", flush=True)

    # internal_link_dictionary 更新
    update_internal_link_dictionary()

    # frontend slug list 更新 (/artists/ハブで /artist-{slug}/にlinkするため)
    update_frontend_slug_list()


if __name__ == '__main__':
    main()
