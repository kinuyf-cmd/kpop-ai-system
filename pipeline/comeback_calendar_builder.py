#!/usr/bin/env python3
"""K-POP Comeback Calendar v0 — Anthropic Web search で最新カムバック日程を集約

機能:
- Claude Sonnet 4.6 + Web search で K-POP公式発表の comeback情報を検索
- 主要22グループ +α の今後3ヶ月のリリース日を収集
- 構造化JSONで保存 → static HTML page生成 → WP固定pageに publish

Output:
- config/comeback_calendar_v2.json
- HTML page in WordPress at /release-calendar/

Cron:
  毎朝 5:00 JST に実行 → 1日1回更新で sticky page 維持
"""
from __future__ import annotations
import os
import sys
import json
import urllib.request
import base64
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, '/home/aiuser/kpop-ai-system')
import anthropic
from dotenv import load_dotenv
load_dotenv('/home/aiuser/kpop-ai-system/.env')

CALENDAR_PATH = Path('/home/aiuser/kpop-ai-system/config/comeback_calendar_v2.json')
WP_USER = os.getenv('WP_USER', '')
WP_PASS = os.getenv('WP_PASS', '')
AUTH = base64.b64encode(f"{WP_USER}:{WP_PASS}".encode()).decode()
JST = timezone(timedelta(hours=9))

# Stage 1: Claude Web search でcomeback情報を集約 (チャンク分割実行)
ARTIST_BATCHES = [
    ['BTS', 'BLACKPINK', 'NewJeans', 'aespa'],
    ['IVE', 'LE SSERAFIM', 'ITZY', 'TWICE'],
    ['SEVENTEEN', 'Stray Kids', 'ENHYPEN', 'TXT'],
    ['ATEEZ', 'TREASURE', 'NMIXX', 'ILLIT'],
    ['BABYMONSTER', 'BOYNEXTDOOR', 'RIIZE', 'TWS'],
    ['KISS OF LIFE', 'CORTIS', 'KATSEYE', 'IU'],
]

SCHEMA = {
    "type": "object",
    "properties": {
        "comebacks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "artist": {"type": "string"},
                    "release_date": {"type": "string"},
                    "title": {"type": "string"},
                    "type": {"type": "string", "enum": ["album", "single", "mv", "ost", "tour", "fanmeeting", "other"]},
                    "source_url": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                },
                "required": ["artist", "release_date", "title", "type", "confidence"],
                "additionalProperties": False,
            },
        },
        "summary": {"type": "string"},
    },
    "required": ["comebacks", "summary"],
    "additionalProperties": False,
}


def _fetch_batch(client: 'anthropic.Anthropic', artists: list[str], today: str, end_date: str) -> dict:
    """1バッチ (4組) のcomeback情報を取得"""
    prompt = f"""今日: {today}
これから {end_date} までの K-POP comeback / リリース情報を調べてください。

検索対象 (4組のみ — 必ず全員調査):
{', '.join(artists)}

各アーティストについて web_search で:
1. 公式発表済の comeback / 新譜リリース日 (今後 90日以内)
2. ツアー/コンサート/ファンミ日程

ヒント: 検索クエリは「[artist] comeback 2026」「[artist] tour 2026」が効率的。
公式情報がないアーティストはスキップしてOK。

結果を JSON schema に従って返却してください。"""

    try:
        response = client.messages.create(
            model='claude-sonnet-4-6',
            max_tokens=4000,
            tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 8}],
            output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
            messages=[{"role": "user", "content": prompt}],
        )
        text = next((b.text for b in response.content if b.type == 'text'), '{}')
        return json.loads(text)
    except Exception as e:
        print(f"  batch err ({artists[0]}...): {e}", flush=True)
        return {"comebacks": [], "summary": ""}


def fetch_comebacks_via_claude() -> dict:
    """全バッチを順次実行して統合 (incremental save付き)"""
    today = datetime.now(JST).strftime('%Y-%m-%d')
    end_date = (datetime.now(JST) + timedelta(days=90)).strftime('%Y-%m-%d')
    client = anthropic.Anthropic()

    # 既存データを base にして上書き (timeout時の進捗保護)
    existing_comebacks = []
    if CALENDAR_PATH.exists():
        try:
            existing_comebacks = json.loads(CALENDAR_PATH.read_text(encoding='utf-8')).get('comebacks', [])
        except Exception:
            pass

    all_comebacks = list(existing_comebacks)
    summaries = []
    for i, batch in enumerate(ARTIST_BATCHES, 1):
        print(f"  [{i}/{len(ARTIST_BATCHES)}] {','.join(batch)} ...", flush=True)
        result = _fetch_batch(client, batch, today, end_date)
        n = len(result.get('comebacks', []))
        print(f"    → {n} entries", flush=True)

        # このバッチで取得したアーティストの古いentryを削除 (上書き) してから新規append
        batch_artists_lower = [a.lower() for a in batch]
        all_comebacks = [cb for cb in all_comebacks
                         if not any(a in (cb.get('artist','').lower()) for a in batch_artists_lower)]
        all_comebacks.extend(result.get('comebacks', []))
        if result.get('summary'):
            summaries.append(result['summary'])

        # incremental save (timeoutで死んでも進捗は残る)
        seen = set(); deduped = []
        for cb in all_comebacks:
            key = (cb.get('artist',''), cb.get('release_date',''), cb.get('title','')[:30])
            if key not in seen:
                seen.add(key); deduped.append(cb)
        partial = {
            "comebacks": deduped,
            "summary": "\n\n".join(summaries[:3]),
            "last_updated": datetime.now(JST).isoformat(),
            "_progress": f"{i}/{len(ARTIST_BATCHES)}",
        }
        with open(CALENDAR_PATH, 'w', encoding='utf-8') as f:
            json.dump(partial, f, ensure_ascii=False, indent=2)

    # 最終de-dup
    seen = set(); deduped = []
    for cb in all_comebacks:
        key = (cb.get('artist',''), cb.get('release_date',''), cb.get('title','')[:30])
        if key not in seen:
            seen.add(key); deduped.append(cb)

    return {
        "comebacks": deduped,
        "summary": "\n\n".join(summaries[:3]),
    }


def render_html(data: dict) -> str:
    """構造化データをHTMLに変換 (compact card grid版)"""
    today = datetime.now(JST).strftime('%Y年%m月%d日')
    comebacks = sorted(data.get('comebacks', []), key=lambda x: x.get('release_date', '9999'))

    type_meta = {
        'album':      ('🎵', '#FF1493', 'アルバム'),
        'single':     ('💿', '#9B59B6', 'シングル'),
        'ep':         ('💿', '#9B59B6', 'EP'),
        'mv':         ('🎬', '#00BCD4', 'MV'),
        'ost':        ('🎞️', '#FFB300', 'OST'),
        'tour':       ('🎤', '#26A69A', 'ツアー'),
        'fanmeeting': ('👥', '#EC407A', 'ファンミ'),
        'other':      ('📌', '#888', 'その他'),
    }
    conf_meta = {
        'high':   ('✅', '#16A34A', '確定'),
        'medium': ('🔵', '#2196F3', '公式予定'),
        'low':    ('🟡', '#EAB308', '予想'),
    }

    parts = [
        '<div class="rc-page">'
        '<div class="rc-hero">'
        '<h1 class="rc-hero-title">📅 K-POP リリース・カレンダー</h1>'
        '<p class="rc-hero-sub">主要22組の今後90日間の公式カムバック・ツアー情報</p>'
        f'<p class="rc-hero-meta">最終更新: {today} ・ 毎朝5時自動更新</p>'
        '</div>'
    ]

    if data.get('summary'):
        sm = (data['summary'] or '').strip()[:200]
        parts.append(f'<div class="rc-summary"><strong>📌 注目</strong> {sm}…</div>')

    # 月別grouping
    by_month = {}
    for cb in comebacks:
        date = cb.get('release_date', '')
        if not date or len(date) < 7: continue
        month = date[:7]
        by_month.setdefault(month, []).append(cb)

    for month in sorted(by_month.keys()):
        cards = []
        for cb in sorted(by_month[month], key=lambda x: x['release_date']):
            date_str = cb['release_date']
            day = date_str[8:10] if len(date_str) >= 10 else '?'
            mon_short = int(date_str[5:7]) if len(date_str) >= 7 else 0
            t = cb.get('type', 'other')
            ticon, tcolor, tlabel = type_meta.get(t, type_meta['other'])
            c = cb.get('confidence', 'low')
            cicon, ccolor, clabel = conf_meta.get(c, conf_meta['low'])
            src = cb.get('source_url', '')
            artist = cb['artist']
            artist_link = (f'<a href="{src}" target="_blank" rel="noopener">{artist}</a>' if src else artist)
            cards.append(
                f'<div class="rc-card">'
                f'<div class="rc-card-date" style="background:{tcolor};">'
                f'<div class="rc-day">{day}</div>'
                f'<div class="rc-mon">{mon_short}月</div>'
                f'</div>'
                f'<div class="rc-card-body">'
                f'<div class="rc-card-artist">{artist_link}</div>'
                f'<div class="rc-card-title">{cb.get("title","")}</div>'
                f'<div class="rc-card-tags">'
                f'<span class="rc-tag" style="color:{tcolor};">{ticon} {tlabel}</span>'
                f'<span class="rc-tag rc-conf" style="color:{ccolor};">{cicon} {clabel}</span>'
                f'</div>'
                f'</div>'
                f'</div>'
            )
        parts.append(f'<h2 class="rc-month">{month[:4]}年{int(month[5:7])}月</h2>')
        parts.append(f'<div class="rc-grid">{"".join(cards)}</div>')

    parts.append(
        '<div class="rc-foot">'
        '<div class="rc-foot-links">'
        '<a href="/artists/" class="rc-foot-link">🎤 アーティスト一覧</a>'
        '<a href="/category/news/" class="rc-foot-link">📰 最新ニュース</a>'
        '</div>'
        '<p class="rc-disclaimer"><small>本ページは Claude Web search で日次自動更新 ・ 確定/予定/予想は信頼度バッジで識別</small></p>'
        '</div>'
        '</div>'
    )
    parts.extend([
        '''<style>
.rc-page { max-width: 980px; margin: 0 auto; padding: 0 0.8em; }
.rc-hero { background: linear-gradient(135deg, #FF1493, #FF8A65); border-radius: 14px; padding: 1.5em 1.4em; margin: 0.5em 0 1.2em; color: white; box-shadow: 0 6px 24px rgba(255,20,147,0.18); }
.rc-hero-title { font-size: 1.6em; font-weight: 800; margin: 0 0 0.3em; color: white; line-height: 1.2; }
.rc-hero-sub { font-size: 0.92em; margin: 0 0 0.5em; opacity: 0.95; }
.rc-hero-meta { font-size: 0.78em; margin: 0; opacity: 0.85; }
.rc-summary { background: linear-gradient(135deg, #fff8e1, #ffecb3); padding: 0.9em 1.1em; border-radius: 10px; border-left: 3px solid #ffc107; margin: 0.8em 0 1.5em; font-size: 0.9em; line-height: 1.55; }
.rc-month { font-size: 1.2em; font-weight: 700; margin: 1.5em 0 0.7em; padding-bottom: 0.3em; border-bottom: 2px solid #FF1493; }
.rc-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 0.7em; margin: 0.8em 0; }
.rc-card { display: flex; align-items: stretch; background: white; border-radius: 10px; overflow: hidden; box-shadow: 0 1px 4px rgba(0,0,0,0.06); border: 1px solid #f0f0f0; transition: transform 0.18s, box-shadow 0.18s; }
.rc-card:hover { transform: translateY(-2px); box-shadow: 0 6px 16px rgba(255,20,147,0.12); }
.rc-card-date { width: 70px; flex-shrink: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; color: white; padding: 0.7em 0.3em; }
.rc-day { font-size: 1.7em; font-weight: 800; line-height: 1; }
.rc-mon { font-size: 0.7em; opacity: 0.92; margin-top: 0.15em; }
.rc-card-body { flex: 1; min-width: 0; padding: 0.7em 0.85em; }
.rc-card-artist { font-size: 1em; font-weight: 700; color: #222; line-height: 1.2; }
.rc-card-artist a { color: #FF1493; text-decoration: none; }
.rc-card-artist a:hover { text-decoration: underline; }
.rc-card-title { font-size: 0.85em; color: #555; margin-top: 0.2em; line-height: 1.3; word-break: break-word; }
.rc-card-tags { display: flex; gap: 0.6em; flex-wrap: wrap; margin-top: 0.4em; font-size: 0.72em; font-weight: 600; }
.rc-tag { background: #f8f9fb; padding: 0.18em 0.5em; border-radius: 99px; }
.rc-foot { margin: 2em 0 1em; padding: 1em 1.2em; background: #fafbfd; border-radius: 10px; }
.rc-foot-h { font-size: 1em; margin: 0 0 0.6em; }
.rc-foot-links { display: flex; gap: 0.6em; flex-wrap: wrap; margin-bottom: 0.7em; }
.rc-foot-link { display: inline-flex; align-items: center; padding: 0.45em 0.9em; background: white; border: 1px solid #eee; border-radius: 99px; text-decoration: none; color: #222; font-size: 0.85em; font-weight: 600; transition: transform 0.18s; }
.rc-foot-link:hover { transform: translateY(-1px); border-color: #FF1493; color: #FF1493; }
.rc-disclaimer { color: #999; font-size: 0.78em; margin: 0.6em 0 0; line-height: 1.5; }

@media (max-width: 600px) {
  .rc-page { padding: 0 0.5em; }
  .rc-hero { padding: 1.1em 0.9em; }
  .rc-hero-title { font-size: 1.3em; }
  .rc-hero-sub { font-size: 0.82em; }
  .rc-hero-meta { font-size: 0.7em; }
  .rc-summary { font-size: 0.82em; padding: 0.7em 0.9em; }
  .rc-month { font-size: 1.05em; }
  .rc-grid { grid-template-columns: 1fr; gap: 0.5em; }
  .rc-card-date { width: 56px; }
  .rc-day { font-size: 1.4em; }
  .rc-card-body { padding: 0.6em 0.7em; }
  .rc-card-artist { font-size: 0.92em; }
  .rc-card-title { font-size: 0.78em; }
  .rc-card-tags { font-size: 0.68em; }
  .rc-foot-link { font-size: 0.78em; padding: 0.4em 0.7em; }
}
</style>''',
    ])
    return '\n'.join(parts)


def find_or_create_calendar_page(html: str) -> int:
    """WP page slug=release-calendar を作成 or 更新"""
    # find existing
    req = urllib.request.Request(
        'https://www.kpopjournal.tokyo/wp-json/wp/v2/pages?slug=release-calendar&_fields=id',
        headers={'Authorization': f'Basic {AUTH}'})
    try:
        existing = json.loads(urllib.request.urlopen(req, timeout=15).read())
    except Exception:
        existing = []

    title = 'K-POP カムバック・カレンダー (今後90日)'
    if existing:
        page_id = existing[0]['id']
        url = f'https://www.kpopjournal.tokyo/wp-json/wp/v2/pages/{page_id}'
        method = 'POST'
    else:
        url = 'https://www.kpopjournal.tokyo/wp-json/wp/v2/pages'
        method = 'POST'
        page_id = None

    payload = {
        'title': title,
        'content': html,
        'status': 'publish',
        'slug': 'release-calendar',
    }
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), method=method,
        headers={'Authorization': f'Basic {AUTH}', 'Content-Type': 'application/json'})
    try:
        r = json.loads(urllib.request.urlopen(req, timeout=30).read())
        return r.get('id', 0)
    except Exception as e:
        print(f"WP publish err: {e}")
        return 0


def _load_manual_seed() -> list[dict]:
    """data/comebacks_manual.json から手動キュレーション分をload"""
    p = Path('/home/aiuser/kpop-ai-system/data/comebacks_manual.json')
    if not p.exists():
        return []
    try:
        d = json.loads(p.read_text(encoding='utf-8'))
        items = d.get('items', []) if isinstance(d, dict) else d
        out = []
        type_map = {'シングル': 'single', 'ミニアルバム': 'ep', 'フルアルバム': 'album',
                    'アルバム': 'album', 'EP': 'ep', 'OST': 'ost', 'ツアー': 'tour'}
        for it in items:
            out.append({
                'artist': it.get('artist', ''),
                'release_date': it.get('date', ''),
                'title': it.get('title', ''),
                'type': type_map.get(it.get('type', ''), 'other'),
                'source_url': it.get('source_url', ''),
                'confidence': 'high',  # 手動curationはhigh
            })
        return out
    except Exception as e:
        print(f"  manual seed load err: {e}", flush=True)
        return []


def main():
    import sys as _sys
    _sys.stdout.reconfigure(line_buffering=True)  # print() を即時flush
    print(f"[calendar] Building K-POP comeback calendar...", flush=True)

    # 1. Manual curation を base にload (web search失敗時の最低保証)
    manual = _load_manual_seed()
    print(f"  manual seed: {len(manual)} entries", flush=True)

    # 2. Claude Web search で補強
    print(f"  Claude web search...", flush=True)
    data = fetch_comebacks_via_claude()
    n_claude = len(data.get('comebacks', []))
    print(f"  claude fetched: {n_claude} entries", flush=True)

    # 3. Merge: manual + claude (de-dup by artist+date+title)
    all_items = list(manual) + data.get('comebacks', [])
    seen = set(); deduped = []
    for cb in all_items:
        key = (cb.get('artist','').lower(), cb.get('release_date',''), cb.get('title','')[:30])
        if key in seen:
            continue
        seen.add(key); deduped.append(cb)
    data['comebacks'] = deduped
    n = len(deduped)
    print(f"  merged total: {n} entries", flush=True)

    # Save JSON
    CALENDAR_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CALENDAR_PATH, 'w', encoding='utf-8') as f:
        json.dump({**data, 'last_updated': datetime.now(JST).isoformat()},
                  f, ensure_ascii=False, indent=2)
    print(f"  saved {CALENDAR_PATH}")

    # Render HTML + publish
    html = render_html(data)
    page_id = find_or_create_calendar_page(html)
    print(f"  published page_id={page_id}")
    print(f"  URL: https://www.kpopjournal.tokyo/release-calendar/")

    # Cache purge
    try:
        from lib.frontend_cache import purge_paths
        purge_paths(['/release-calendar/'])
    except Exception:
        pass

    # GSC indexing
    try:
        from lib.gsc_indexing import notify_url_updated
        r = notify_url_updated('https://www.kpopjournal.tokyo/release-calendar/')
        if r.get('status') == 'ok':
            print(f"  GSC indexed")
    except Exception as e:
        print(f"  GSC submit err: {e}")


if __name__ == '__main__':
    main()
