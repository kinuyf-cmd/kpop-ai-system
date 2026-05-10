"""KPOP_KW自動拡張サジェスト (2026-05-10)

trend_signals.jsonl から「artist識別失敗だがK-pop関連と思しき」signalを集計し、
未登録のグループ/個人候補を抽出してDiscordに通知。

人間が判断: 確認後、`config/pending_kpop_kw_additions.json` を編集 → 採用候補を
`lib/collectors/korean_base.py` の KPOP_KW に手動追加。

cron: 毎週月曜 9:00 JST
"""
import os
import sys
import json
import re
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from dotenv import load_dotenv
load_dotenv('/home/aiuser/kpop-ai-system/.env')
from lib.collectors.korean_base import is_kpop_related, KPOP_KW

SIGNALS_PATH = '/home/aiuser/kpop-ai-system/data/trend_signals.jsonl'
LOG_PATH = '/home/aiuser/kpop-ai-system/logs/kpop_kw_suggestions.jsonl'
DISCORD_WEBHOOK = os.getenv('DISCORD_WEBHOOK_URL', '')

# K-pop関連シグナルだが artist 不明 → 候補抽出
DAYS_LOOKBACK = 7
MIN_OCCURRENCES = 3


def extract_candidates(title: str) -> list[str]:
    """タイトル先頭の固有名詞っぽい連続文字を候補に"""
    candidates = []
    # ハングル: 連続2-15文字 (アーティスト名候補)
    for m in re.finditer(r'[가-힯]{2,15}', title):
        candidates.append(m.group())
    # ASCII大文字: 連続2-20文字 (英名グループ)
    for m in re.finditer(r'\b[A-Z][A-Z0-9 ]{1,19}[A-Z0-9]\b', title):
        candidates.append(m.group().strip())
    # カタカナ: 連続2-15文字
    for m in re.finditer(r'[゠-ヿ]{2,15}', title):
        candidates.append(m.group())
    return candidates


def main():
    cutoff = (datetime.now() - timedelta(days=DAYS_LOOKBACK)).isoformat()
    kpop_kw_lower = {kw.lower() for kw in KPOP_KW}

    # K-pop関連だがartist不明のsignalを集計
    candidate_counter = Counter()
    examples = {}  # candidate → sample title

    if not os.path.exists(SIGNALS_PATH):
        print(f"signals not found: {SIGNALS_PATH}")
        return 0

    with open(SIGNALS_PATH, encoding='utf-8') as f:
        for line in f:
            try:
                d = json.loads(line)
                if d.get('timestamp', '') < cutoff:
                    continue
                title = d.get('title', '')
                # 既にartist識別できるならskip
                arts = is_kpop_related(title)
                if arts and arts[0] not in {'K-POP','KPOP','케이팝','컴백','신곡','발매','데뷔','콘서트','팬미팅'}:
                    continue
                # 候補抽出
                for cand in extract_candidates(title):
                    if cand.lower() in kpop_kw_lower:
                        continue
                    if len(cand) < 2 or cand.isdigit():
                        continue
                    candidate_counter[cand] += 1
                    if cand not in examples:
                        examples[cand] = title[:80]
            except (json.JSONDecodeError, ValueError):
                pass

    # 出現3回以上の候補を採用候補に
    suggestions = [(c, n, examples[c]) for c, n in candidate_counter.most_common(30)
                   if n >= MIN_OCCURRENCES]

    print(f"=== KPOP_KW expansion candidates ({DAYS_LOOKBACK}d) ===")
    print(f"total candidates >= {MIN_OCCURRENCES}回: {len(suggestions)}\n")
    for c, n, title in suggestions[:20]:
        print(f"  [{n}回] {c}  - 例: {title}")

    # JSON出力 (人間がreview)
    out = {
        'ts': datetime.now().isoformat(),
        'lookback_days': DAYS_LOOKBACK,
        'candidates': [{'name': c, 'count': n, 'example': t} for c, n, t in suggestions],
    }
    Path(os.path.dirname(LOG_PATH)).mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, 'a', encoding='utf-8') as f:
        f.write(json.dumps(out, ensure_ascii=False) + '\n')

    # Discord通知 (10件以上の候補があれば)
    if suggestions and DISCORD_WEBHOOK:
        try:
            import urllib.request
            msg = [f"📋 KPOP_KW 候補 {len(suggestions)}件 (直近{DAYS_LOOKBACK}日)"]
            for c, n, t in suggestions[:10]:
                msg.append(f"- [{n}回] `{c}` — {t[:50]}")
            msg.append(f"\n review → `lib/collectors/korean_base.py` KPOP_KW に手動追加")
            req = urllib.request.Request(
                DISCORD_WEBHOOK,
                data=json.dumps({'content': '\n'.join(msg)[:2000]}).encode(),
                headers={'Content-Type': 'application/json'},
                method='POST',
            )
            urllib.request.urlopen(req, timeout=15)
        except Exception as e:
            print(f"discord err: {e}")

    return len(suggestions)


if __name__ == '__main__':
    sys.exit(0 if main() == 0 else 0)
