#!/usr/bin/env python3
"""build_events.py v3 — 一次情報(PRTIMES+チケットガイド+記事)から events.json 生成

優先度:
1. data/events_manual.json (手動キュレーション、最優先)
2. チケットガイドcollector signals (公演情報、高信頼)
3. PRTIMES signals (プレスリリース、中信頼)
4. event カテゴリ記事 (厳格ファクトチェック)
"""
import json, os, re, urllib.request, urllib.parse, base64
from datetime import datetime, timedelta

OUT = '/home/aiuser/kpopjournal-frontend/public/data/events.json'
SIGNALS = '/home/aiuser/kpop-ai-system/data/trend_signals.jsonl'
MANUAL = '/home/aiuser/kpop-ai-system/data/events_manual.json'
os.makedirs(os.path.dirname(OUT), exist_ok=True)

EXCLUDE = re.compile(
    r'考察|ガイド|徹底|なぜ|全貌|真相|解説|まとめ|入門|初心者|'
    r'〜とは|ルーティン|完全体|秘密|裏側|正体|論$|予想|予測|振り返り'
)

VENUE = re.compile(
    r'(東京ドーム|京セラドーム|国立競技場|さいたまスーパーアリーナ|'
    r'ナゴヤドーム|福岡PayPayドーム|横浜アリーナ|Kアリーナ横浜|'
    r'日本武道館|代々木第一体育館|有明アリーナ|幕張メッセ|'
    r'東京ガーデンシアター|大阪城ホール|ぴあアリーナMM|'
    r'Zepp [一-龠A-Za-z]+|Kアリーナ|インテックス大阪|'
    r'[一-龠ぁ-ん]{2,8}ホール|[一-龠ぁ-ん]{2,8}アリーナ|[一-龠ぁ-ん]{2,8}ドーム)'
)

DATE_YMD = re.compile(r'(20\d{2})[年/\-](\d{1,2})[月/\-](\d{1,2})[日]?')
DATE_MD = re.compile(r'(\d{1,2})月(\d{1,2})日')

ARTIST = re.compile(
    r'(BTS|BLACKPINK|aespa|NewJeans|SEVENTEEN|TWICE|IVE|LE SSERAFIM|ILLIT|'
    r'ITZY|Red Velvet|TXT|Stray Kids|ENHYPEN|NCT|ATEEZ|TWS|'
    r'KISS OF LIFE|&TEAM|BOYNEXTDOOR|RIIZE|ZEROBASEONE|MEOVV|'
    r'IU|LISA|JENNIE|Rosé|JISOO|V|Jungkook|Jimin|JIN|RM|J-HOPE|SUGA|'
    r'BABYMONSTER|TREASURE|NMIXX|SHINee|EXO|MONSTA X|GOT7|ASTRO|DAY6|'
    r'\(G\)I-DLE|BIGBANG|fromis_9|KCON|Hearts2Hearts|JO1|INI|ME:I|NiziU|'
    r'P1Harmony|KickFlip|izna|IS:SUE|EVNNE|MODYSSEY|CORTIS|ALPHA DRIVE ONE|'
    r'KIM JAE HWAN|xikers|YOUNITE|TIFFANY|TAEYANG|YUTA|MAMAMOO|VERNON|THE 8)'
)

# PRTIMES向け: K-POPイベント関連語が含まれない投稿(AI/SaaS/化粧品プレスリリース)を除外
KPOP_EVENT_TERMS = re.compile(
    r'K-POP|KPOP|韓流|FANMEETING|ファンミ|ファンミーティング|'
    r'コンサート|ライブ|ツアー|TOUR|LIVE IN JAPAN|JAPAN TOUR|'
    r'POP-UP STORE|ポップアップ|カムバック|COMEBACK'
)


def extract_event(text, url, source):
    if EXCLUDE.search(text):
        return None
    v = VENUE.search(text)
    if not v:
        return None
    a = ARTIST.search(text)

    m_ymd = DATE_YMD.search(text)
    if m_ymd:
        y, mo, da = int(m_ymd.group(1)), int(m_ymd.group(2)), int(m_ymd.group(3))
    else:
        m_md = DATE_MD.search(text)
        if not m_md:
            return None
        mo, da = int(m_md.group(1)), int(m_md.group(2))
        y = datetime.now().year

    try:
        d = datetime(y, mo, da)
        if d < datetime.now() - timedelta(days=1):
            if not m_ymd:
                d = datetime(y + 1, mo, da)
            else:
                return None
        if d > datetime.now() + timedelta(days=31):
            return None
    except ValueError:
        return None

    return {
        'title': text[:80],
        'date': d.strftime('%Y-%m-%d'),
        'venue': v.group(1),
        'artist': a.group(1) if a else '',
        'url': url,
        'source': source,
    }


items = []

# 1) 手動キュレーション
if os.path.exists(MANUAL):
    try:
        manual = json.load(open(MANUAL, encoding='utf-8'))
        if isinstance(manual, list):
            items.extend(manual)
        elif isinstance(manual, dict):
            items.extend(manual.get('items', []))
        print(f"manual: {len(items)}件")
    except Exception as e:
        print(f"manual load error: {e}")

# 2) trend_signals.jsonl から ticket_guide + PRTIMES (K-POP allow-list)
# PRTIMES再有効化 2026-05-07: 厳格K-POPフィルタ (ARTIST + KPOP_EVENT_TERMS 両方マッチ) で誤検出防止
# tickebo enrichment 2026-05-07: og:titleに日付がないため /web/api/evt/sales-list を直接叩いて公演詳細取得
import sys as _sys
_sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from lib.ticket_enricher import fetch_tickebo_performances

tickebo_seen_ids = set()
tickebo_enriched = 0
tickebo_404 = 0
prtimes_added = 0
if os.path.exists(SIGNALS):
    with open(SIGNALS, encoding='utf-8') as f:
        for line in f:
            try:
                sig = json.loads(line)
            except Exception:
                continue
            src = sig.get('source')
            title = sig.get('title', '')
            if src == 'ticket_guide':
                # tickebo: raw_data.event_id を使ってAPI enrichment
                eid = (sig.get('raw_data') or {}).get('event_id')
                if eid and sig.get('source_id') == 'tickebo':
                    if eid in tickebo_seen_ids:
                        continue
                    tickebo_seen_ids.add(eid)
                    enriched = fetch_tickebo_performances(int(eid))
                    if enriched is None:
                        tickebo_404 += 1
                        continue
                    artist = enriched.get('performers', [''])[0] if enriched.get('performers') else ''
                    base_title = enriched.get('title') or title
                    enrich_url = sig.get('url', f'https://ticket.tickebo.jp/show/event.html?info={eid}')
                    for perf in enriched.get('performances', []):
                        if not perf.get('date') or not perf.get('venue'):
                            continue
                        items.append({
                            'title': base_title,
                            'date': perf['date'],
                            'venue': perf['venue'],
                            'artist': artist,
                            'url': enrich_url,
                            'source': 'ticket_guide',
                            'open_time': perf.get('open_time', ''),
                            'start_time': perf.get('start_time', ''),
                        })
                        tickebo_enriched += 1
                else:
                    # PIA等の非tickebo ticket_guide: 従来のtitle regex
                    ev = extract_event(title, sig.get('url', ''), src)
                    if ev:
                        items.append(ev)
            elif src == 'prtimes':
                # K-POP判定: 既知アーティスト名 + イベント関連語 両方必須
                if not (ARTIST.search(title) and KPOP_EVENT_TERMS.search(title)):
                    continue
                ev = extract_event(title, sig.get('url', ''), src)
                if ev:
                    items.append(ev)
                    prtimes_added += 1
            else:
                continue
if tickebo_enriched or tickebo_404:
    print(f"tickebo enrichment: {tickebo_enriched}公演 取得 / {tickebo_404}件 404")
if prtimes_added:
    print(f"prtimes: {prtimes_added}件 K-POP allow-list通過")

# 3) event カテゴリ記事
auth = base64.b64encode(b"kpop-bot:vl1H 1brV m4Pq Z1sm F8lZ 3nzh").decode()
try:
    cr = urllib.request.Request(
        "https://www.kpopjournal.tokyo/wp-json/wp/v2/categories?slug=event&_fields=id",
        headers={'Authorization': f'Basic {auth}'},
    )
    cid = json.loads(urllib.request.urlopen(cr, timeout=20).read())[0]['id']
    q = urllib.parse.urlencode({
        'categories': cid, 'per_page': 30, 'status': 'publish', '_fields': 'id,slug,title',
    })
    req = urllib.request.Request(
        f"https://www.kpopjournal.tokyo/wp-json/wp/v2/posts?{q}",
        headers={'Authorization': f'Basic {auth}'},
    )
    posts = json.loads(urllib.request.urlopen(req, timeout=20).read())
    for p in posts:
        title = re.sub(r'<[^>]+>', '', p['title']['rendered'])
        url = f"https://www.kpopjournal.tokyo/{p['slug']}/"
        ev = extract_event(title, url, 'article')
        if ev:
            ev['slug'] = p['slug']
            items.append(ev)
except Exception as e:
    print(f"article fetch error: {e}")

# 重複除去 (会場名の表記ゆれを正規化してdedup: 全角/半角・空白・session prefix・ローマ字↔漢字)
def _normalize_venue(v: str) -> str:
    v = re.sub(r'^【[^】]*】\s*', '', v)  # 「【1部】京王アリーナTOKYO」 → 「京王アリーナTOKYO」
    v = re.sub(r'\s+', '', v)
    v = v.lower()
    aliases = {
        # ローマ字 ↔ 漢字
        'keioarenatokyo': '京王アリーナtokyo',
        # 略称統一
        '国立代々木競技場第一体育館': '代々木第一体育館',
        '代々木第一体育館': '代々木第一体育館',
        # 会場の館号バリエーション
        'マリンメッセ福岡b館': 'マリンメッセ福岡',
    }
    return aliases.get(v, v)

seen = set()
unique = []
for it in items:
    if not it.get('date') or not it.get('venue'):
        continue
    key = f"{it.get('artist', '')}-{it['date']}-{_normalize_venue(it['venue'])}"
    if key in seen:
        continue
    seen.add(key)
    unique.append(it)

def _find_related_article(event_title, event_artist):
    """イベントに該当する記事を検索し、slugを返す"""
    q_text = event_artist if event_artist else event_title[:20]
    try:
        search_url = (
            f"https://www.kpopjournal.tokyo/wp-json/wp/v2/posts"
            f"?search={urllib.parse.quote(q_text)}&per_page=3&_fields=slug,title"
        )
        req = urllib.request.Request(search_url, headers={'Authorization': f'Basic {auth}'})
        found = json.loads(urllib.request.urlopen(req, timeout=10).read())
        for p in found:
            t = re.sub(r'<[^>]+>', '', p.get('title', {}).get('rendered', ''))
            if event_artist and event_artist in t:
                if any(kw in t for kw in ['ライブ', 'ツアー', 'コンサート', 'ファンミ', 'ショーケース']):
                    return p['slug']
        if found:
            return found[0]['slug']
    except Exception:
        pass
    return None


unique.sort(key=lambda x: x['date'])

# 各イベントに関連記事slug紐付け (article以外)
for it in unique:
    if it.get('source') != 'article' and not it.get('slug'):
        slug = _find_related_article(it.get('title', ''), it.get('artist', ''))
        if slug:
            it['slug'] = slug
final_items = unique[:12]
json.dump(
    {'updated_at': datetime.now().isoformat(), 'items': final_items},
    open(OUT, 'w', encoding='utf-8'),
    ensure_ascii=False,
    indent=2,
)

print(f"events.json: {len(unique)}件")
for it in unique[:5]:
    print(f"  {it['date']} {it.get('artist', '')}: {it['title'][:50]} @ {it['venue']} [{it['source']}]")

# 0件継続検知 + Discord通知 (silent rot 再発防止 / 2026-04-24障害の教訓)
import sys as _sys
_sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from lib.event_data_health import record_and_alert
print(record_and_alert('events', OUT, len(final_items)))
