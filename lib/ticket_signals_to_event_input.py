#!/usr/bin/env python3
"""ticket_signals_to_event_input.py — ticket_collector の signal を
popup_event_to_post.py が食える event 入力JSONに変換するアダプタ(2026-05-25)

ticket_collector(pia/tickebo/eplus/ltike)は trend_signals.jsonl に
source=ticket_guide の signal を吐く。一方 popup_event_to_post.py は
{"signals":[{type,artist_keyword,title,source_url,source_media,start_date}]}
形式を期待する(kbuzzlab/PRTIMES 由来)。両者のキー構造が違うため、
ここで変換する。投稿ロジック(DB INSERT + TEC テーブル更新)は
popup_event_to_post.py をそのまま再利用する(車輪の再発明・DB破壊回避)。

変換ルール:
  ticket_guide signal → {type:"event"} に。
  - artist_keyword ← keyword(無ければ title 先頭語)
  - title         ← title(原文ママ。citation)
  - source_url    ← url
  - source_media  ← source_id を表示名へ(pia→ぴあ, eplus→イープラス, tickebo→チケットボード)
  - start_date    ← raw_data.performances[0].date

フィルタ:
  - source==ticket_guide のみ
  - source_url 必須(HARD_FAIL)
  - 未来公演のみ(start_date >= today)。過去公演はカレンダー価値が低く除外。
  - (title, start_date) で重複除去

使い方:
  venv_kpi/bin/python3 lib/ticket_signals_to_event_input.py            # 既定出力
  venv_kpi/bin/python3 lib/ticket_signals_to_event_input.py --out /path.json
出力後の投稿(既存ロジック):
  DRY_RUN=1 venv_kpi/bin/python3 lib/popup_event_to_post.py <出力JSON>  # SQL確認
  venv_kpi/bin/python3 lib/popup_event_to_post.py <出力JSON>            # 本投稿
"""
import argparse
import json
import os
from datetime import date

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIGNALS = os.path.join(BASE, "data", "trend_signals.jsonl")
DEFAULT_OUT = os.path.join(BASE, "data", "event_input_from_tickets.json")

MEDIA_NAME = {"pia": "ぴあ", "eplus": "イープラス", "tickebo": "チケットボード",
              "ltike": "ローソンチケット"}

# ソース信頼度: pia(K-POPタグ tagCd=0000078 由来)/tickebo(K-POP判定通過済)は
# K-POP確定として信頼。eplus は keyword=K-POP 検索だが非K-POP(梶浦由記/音楽祭等)が
# 混入するため、明確なK-POPアーティスト名を含むものだけ採用する。
TRUSTED_SOURCES = {"pia", "tickebo"}

# eplus 採用用: 主要K-POPアーティスト/グループのホワイトリスト(タイトル部分一致)。
# 確実にK-POPと言えるものに限定(誤って非K-POPを通さない安全側)。
KPOP_ARTISTS = [
    "BTS", "BLACKPINK", "TWICE", "SEVENTEEN", "Stray Kids", "ENHYPEN", "TXT",
    "TOMORROW X TOGETHER", "ITZY", "aespa", "NewJeans", "IVE", "LE SSERAFIM",
    "NMIXX", "NCT", "EXO", "Red Velvet", "SHINee", "SUPER JUNIOR", "&TEAM",
    "RIIZE", "ZEROBASEONE", "ZB1", "BABYMONSTER", "ILLIT", "KISS OF LIFE",
    "(G)I-DLE", "G-IDLE", "MAMAMOO", "ATEEZ", "THE BOYZ", "TREASURE", "P1Harmony",
    "MONSTA X", "GOT7", "DAY6", "fromis", "Kep1er", "STAYC", "NEXZ", "&AUDITION",
    "MEOVV", "Hearts2Hearts", "ALLDAY PROJECT", "YENA", "LEE YOUNGJI", "MYNAME",
    "Kwon Jin Ah", "KANG JI YOUNG", "LEE MINHYUK", "HAN SEUNG WOO", "LEE JI HOON",
    "JANG HANEUM", "SMTR", "WI HA JUN", "BOYNEXTDOOR", "xikers", "TWS", "CORTIS",
]


def _is_kpop_eplus(title):
    """eplus signal が確実にK-POPか。
    eplus_enricher._is_kpop の堅牢判定(単語境界+曖昧名の文脈語ガード)に統一。
    旧実装は単純部分一致で 'The Hidden Treasure' を TREASURE と誤判定していた。"""
    try:
        from lib.eplus_enricher import _is_kpop as _robust_is_kpop
        return _robust_is_kpop(title)
    except Exception:
        # フォールバック(import 失敗時のみ): 単語境界一致 + 曖昧名は文脈語必須
        import re as _re
        if not title:
            return False
        tl = title.lower()
        _ambig = {'treasure', 'ive', 'ace'}
        _ctx = ['k-pop', 'kpop', '韓国', 'korea', 'ソウル', 'アイドル',
                'ファンミ', 'ワールドツアー', '트레저', '아이브']
        has_ctx = any(c in tl for c in _ctx)
        for a in KPOP_ARTISTS:
            al = a.lower()
            if a.isascii() and a.replace(' ', '').replace('-', '').isalnum():
                if _re.search(r'(?<![a-z0-9])' + _re.escape(al) + r'(?![a-z0-9])', tl):
                    if al in _ambig and not has_ctx:
                        continue
                    return True
            elif al in tl:
                return True
        return False


def load_ticket_signals(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if d.get("source") == "ticket_guide":
                rows.append(d)
    return rows


def _extract_artist(title, keyword):
    """タイトルから K-POP アーティスト名を推定。
    ホワイトリスト一致を最優先(「2026 Kwon Jin Ah ...」等の前置き数字対策)。"""
    tl = title.lower()
    for a in KPOP_ARTISTS:
        if a.lower() in tl:
            return a
    # keyword が 'K-POP'/数字/空 のときは title 先頭の意味のある語を使う
    kw = (keyword or "").strip()
    if kw and kw.upper() != "K-POP" and not kw.isdigit():
        return kw[:30]
    # title 先頭から英字/カナの語を拾う(年号 2026 等はスキップ)
    for tok in title.split():
        if tok.isdigit():
            continue
        return tok[:30]
    return title[:30] or "K-POP"


def to_event(sig):
    """ticket_guide signal → popup_event_to_post の event 形式。不適格は None。"""
    url = sig.get("url", "")
    if not url:
        return None  # source_url 必須(HARD_FAIL)
    title = (sig.get("title") or "").strip()
    if not title:
        return None
    source_id = sig.get("source_id", "")
    # ソース信頼度フィルタ: eplus は K-POP アーティスト名を含むものだけ採用
    # (非K-POPの音楽祭・舞台・作曲家公演の混入を防ぐ)。pia/tickebo は信頼。
    if source_id not in TRUSTED_SOURCES and not _is_kpop_eplus(title):
        return None
    perfs = sig.get("raw_data", {}).get("performances", [])
    start_date = perfs[0].get("date", "") if perfs else ""
    venue = perfs[0].get("venue", "") if perfs else ""
    artist = _extract_artist(title, sig.get("keyword", ""))
    media = MEDIA_NAME.get(source_id, source_id or "チケット")
    return {
        "type": "event",
        "artist_keyword": artist,
        "title": title,
        "source_url": url,
        "source_media": media,
        "start_date": start_date,
        "venue": venue,
        "_source_id": source_id,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--signals", default=SIGNALS)
    ap.add_argument("--include-past", action="store_true",
                    help="過去公演も含める(既定は未来のみ)")
    args = ap.parse_args()

    raw = load_ticket_signals(args.signals)
    today = date.today().isoformat()
    events, seen = [], set()
    skipped = {"no_url_or_title": 0, "no_date": 0, "past": 0, "dup": 0}

    for sig in raw:
        ev = to_event(sig)
        if ev is None:
            skipped["no_url_or_title"] += 1
            continue
        # start_date 必須: 日付の無いイベントは The Events Calendar の
        # 日付メタ(wp_tec_events/occurrences)が設定できず single ページが404になる
        # (TEC 6.x 仕様。tickebo は日付未取得が多い)。カレンダー価値も無いので除外。
        if not ev["start_date"]:
            skipped["no_date"] += 1
            continue
        if not args.include_past and ev["start_date"] < today:
            skipped["past"] += 1
            continue
        key = (ev["title"][:50], ev["start_date"])
        if key in seen:
            skipped["dup"] += 1
            continue
        seen.add(key)
        events.append(ev)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"signals": events}, f, ensure_ascii=False, indent=1)

    by_media = {}
    for e in events:
        by_media[e["source_media"]] = by_media.get(e["source_media"], 0) + 1
    print(f"ticket_guide signals読込: {len(raw)}")
    print(f"event出力: {len(events)} 件 / media別: {by_media}")
    print(f"除外: {skipped}")
    print(f"出力: {args.out}")


if __name__ == "__main__":
    main()
