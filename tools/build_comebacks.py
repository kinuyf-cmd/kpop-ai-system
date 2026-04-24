#!/usr/bin/env python3
"""build_comebacks.py v3 — 厳格ファクトチェック版

判断基準:
- 「カムバック」「新曲リリース」「アルバム発売」等の明示的表現のみ
- 日付明示必須
- アーティスト名明確
- 手動キュレーション優先
"""
import json, os, re
from datetime import datetime, timedelta

OUT = '/home/aiuser/kpopjournal-frontend/public/data/comebacks.json'
SIGNALS = '/home/aiuser/kpop-ai-system/data/trend_signals.jsonl'
MANUAL = '/home/aiuser/kpop-ai-system/data/comebacks_manual.json'
os.makedirs(os.path.dirname(OUT), exist_ok=True)

COMEBACK_KW = re.compile(
    r'カムバック|カムバ|新曲リリース|新曲発売|新アルバム|ミニアルバム|'
    r'フルアルバム|新ミニ|新EP|comeback|release'
)
EXCLUDE = re.compile(r'考察|予想|予測|噂|情報|説|解説|ガイド')

ARTIST = re.compile(
    r'(BTS|BLACKPINK|aespa|NewJeans|SEVENTEEN|TWICE|IVE|LE SSERAFIM|ILLIT|'
    r'ITZY|Red Velvet|TXT|Stray Kids|ENHYPEN|NCT|ATEEZ|TWS|'
    r'KISS OF LIFE|&TEAM|BOYNEXTDOOR|RIIZE|ZEROBASEONE|MEOVV|'
    r'IU|LISA|JENNIE|Rosé|JISOO)'
)
DATE_YMD = re.compile(r'(20\d{2})[年/\-](\d{1,2})[月/\-](\d{1,2})')
DATE_MD = re.compile(r'(\d{1,2})月(\d{1,2})日')

comebacks = []

# 手動優先
if os.path.exists(MANUAL):
    try:
        m = json.load(open(MANUAL, encoding='utf-8'))
        comebacks.extend(m if isinstance(m, list) else m.get('items', []))
    except Exception:
        pass

# trend_signals.jsonl から抽出
if os.path.exists(SIGNALS):
    with open(SIGNALS, encoding='utf-8') as f:
        for line in f:
            try:
                sig = json.loads(line)
            except Exception:
                continue
            title = sig.get('title', '')
            if EXCLUDE.search(title):
                continue
            if not COMEBACK_KW.search(title):
                continue
            a = ARTIST.search(title)
            if not a:
                continue

            m_ymd = DATE_YMD.search(title)
            if m_ymd:
                try:
                    d = datetime(int(m_ymd.group(1)), int(m_ymd.group(2)), int(m_ymd.group(3)))
                except ValueError:
                    continue
            else:
                m_md = DATE_MD.search(title)
                if not m_md:
                    continue
                try:
                    d = datetime(datetime.now().year, int(m_md.group(1)), int(m_md.group(2)))
                    if d < datetime.now() - timedelta(days=7):
                        d = datetime(datetime.now().year + 1, int(m_md.group(1)), int(m_md.group(2)))
                except ValueError:
                    continue

            if d > datetime.now() + timedelta(days=60):
                continue

            comebacks.append({
                'artist': a.group(1),
                'date': d.strftime('%Y-%m-%d'),
                'title': title[:80],
                'source': sig.get('source', 'signal'),
            })

# 重複除去 + 未来のみ
seen = set()
future = []
for c in comebacks:
    try:
        if datetime.strptime(c['date'], '%Y-%m-%d') < datetime.now() - timedelta(days=1):
            continue
    except ValueError:
        continue
    key = f"{c['artist']}-{c['date']}"
    if key in seen:
        continue
    seen.add(key)
    future.append(c)

future.sort(key=lambda x: x['date'])

json.dump(
    {'updated_at': datetime.now().isoformat(), 'items': future[:8]},
    open(OUT, 'w', encoding='utf-8'),
    ensure_ascii=False,
    indent=2,
)

print(f"comebacks.json: {len(future)}件 (厳格版)")
for c in future[:5]:
    print(f"  {c['date']} {c['artist']}: {c.get('title', '')[:50]} [{c.get('source', '?')}]")
