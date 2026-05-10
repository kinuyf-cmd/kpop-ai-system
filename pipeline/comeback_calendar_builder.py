#!/usr/bin/env python3
"""K-POP Comeback Calendar v0 — Anthropic Web search で最新カムバック日程を集約

機能:
- Claude Sonnet 4.6 + Web search で K-POP公式発表の comeback情報を検索
- 主要22グループ +α の今後3ヶ月のリリース日を収集
- 構造化JSONで保存 → static HTML page生成 → WP固定pageに publish

Output:
- config/comeback_calendar_v2.json
- HTML page in WordPress at /comeback-calendar/

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
    """構造化データをHTMLに変換"""
    today = datetime.now(JST).strftime('%Y年%m月%d日')
    comebacks = sorted(data.get('comebacks', []), key=lambda x: x.get('release_date', '9999'))

    html_parts = [
        '<div class="comeback-calendar">',
        f'<p class="last-updated"><small>最終更新: {today}</small></p>',
        '<p>K-POP主要グループの今後90日間の公式カムバック・リリース情報をまとめています。毎日5時に最新情報に自動更新されます。</p>',
    ]

    if data.get('summary'):
        html_parts.append(f'<div class="summary"><strong>📌 注目ポイント</strong><br>{data["summary"]}</div>')

    # 月別grouping
    by_month = {}
    for cb in comebacks:
        date = cb.get('release_date', '')
        if not date or len(date) < 7: continue
        month = date[:7]
        by_month.setdefault(month, []).append(cb)

    for month in sorted(by_month.keys()):
        html_parts.append(f'<h2>{month[:4]}年{int(month[5:7])}月</h2>')
        html_parts.append('<table class="comeback-table">')
        html_parts.append('<thead><tr><th>日付</th><th>アーティスト</th><th>タイトル</th><th>種別</th><th>信頼度</th></tr></thead>')
        html_parts.append('<tbody>')
        for cb in sorted(by_month[month], key=lambda x: x['release_date']):
            date_disp = cb['release_date'][8:10] + '日' if len(cb['release_date']) >= 10 else cb['release_date']
            type_badge = {
                'album': '🎵 アルバム', 'single': '💿 シングル', 'mv': '🎬 MV',
                'ost': '🎞️ OST', 'tour': '🎤 ツアー', 'fanmeeting': '👥 ファンミ',
                'other': '📌 その他',
            }.get(cb.get('type', 'other'), '📌')
            conf = cb.get('confidence', 'low')
            conf_badge = {'high': '✅ 確定', 'medium': '🔵 公式予定', 'low': '🟡 予想'}.get(conf, '?')
            src = cb.get('source_url', '')
            artist_text = cb['artist']
            if src:
                artist_text = f'<a href="{src}" target="_blank" rel="noopener">{cb["artist"]}</a>'
            html_parts.append(
                f'<tr><td>{date_disp}</td><td><strong>{artist_text}</strong></td>'
                f'<td>{cb.get("title","")}</td><td>{type_badge}</td><td>{conf_badge}</td></tr>'
            )
        html_parts.append('</tbody></table>')

    html_parts.extend([
        '<h3>📚 関連情報</h3>',
        '<ul>',
        '<li>各アーティスト公式 (Twitter/Weverse/Bubble) で最新情報を確認</li>',
        '<li>本ページは Anthropic Claude Web search で日次自動更新</li>',
        '<li>確定/予定/予想は信頼度欄で識別</li>',
        '</ul>',
        '</div>',
        '<style>',
        '.comeback-calendar table { width: 100%; border-collapse: collapse; margin: 1em 0; }',
        '.comeback-calendar th, .comeback-calendar td { padding: 0.5em; border: 1px solid #ddd; text-align: left; }',
        '.comeback-calendar th { background: #f4f4f8; }',
        '.comeback-calendar .summary { background: #fff8e1; padding: 1em; border-left: 4px solid #ffc107; margin: 1em 0; }',
        '.comeback-calendar .last-updated { color: #888; }',
        '</style>',
    ])
    return '\n'.join(html_parts)


def find_or_create_calendar_page(html: str) -> int:
    """WP page slug=comeback-calendar を作成 or 更新"""
    # find existing
    req = urllib.request.Request(
        'https://www.kpopjournal.tokyo/wp-json/wp/v2/pages?slug=comeback-calendar&_fields=id',
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
        'slug': 'comeback-calendar',
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


def main():
    import sys as _sys
    _sys.stdout.reconfigure(line_buffering=True)  # print() を即時flush
    print(f"[calendar] Building K-POP comeback calendar via Claude Web search...", flush=True)
    data = fetch_comebacks_via_claude()
    n = len(data.get('comebacks', []))
    print(f"  fetched {n} entries", flush=True)

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
    print(f"  URL: https://www.kpopjournal.tokyo/comeback-calendar/")

    # Cache purge
    try:
        from lib.frontend_cache import purge_paths
        purge_paths(['/comeback-calendar/'])
    except Exception:
        pass


if __name__ == '__main__':
    main()
