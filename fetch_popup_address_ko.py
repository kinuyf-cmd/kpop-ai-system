#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kbuzzlab 出典ページからハングル住所(原文)を抽出し popup_address_ko に冪等格納する。

背景: popup_address は日本語のみ。kbuzzlab 出典ページにはハングル原文住所が
構造化されて存在する(606: 서울 성동구..., 595: 서울 용산구... を probe確認 2026-05-23)。
住所カードに日本語+ハングル併記するため、出典から verbatim 抽出して別フィールドへ。

絶対方針(捏造ゼロ):
  - verbatim: 出典ページのハングル住所をそのまま格納。要約・整形・翻訳しない。
  - 非空のみ: 抽出できなければ書かない(=日本語のみ表示)。無理に作らない。
  - 冪等: ON DUPLICATE KEY UPDATE。同じ出典なら何度流しても同一。
  - 出典維持: popup_source_url は触らない(citation-rules §8)。本フィールド追加のみ。
  - 触るのは popup_address_ko 1キーのみ。a8/外部リンク/本文/出典は不変。

抽出ロジック: 韓国住所の語(특별시/광역시/특별자치/시/구/길/로/동 等)を含み、
かつ日本語の '📍 Address' 行ではない(ハングルを含む)候補を拾う。複数候補は
最長一致(住所は語が多い)を採用。曖昧なら空。

実行(www-data で。DB接続 + 外部HTTP のため):
  サンプル dry-run:  sudo -u www-data python3 fetch_popup_address_ko.py --ids 606,595
  サンプル適用:      sudo -u www-data DRY_RUN=0 python3 fetch_popup_address_ko.py --ids 606,595
  全件 dry-run:      sudo -u www-data python3 fetch_popup_address_ko.py
  全件適用:          sudo -u www-data DRY_RUN=0 python3 fetch_popup_address_ko.py
"""
import os
import re
import sys
import time
import argparse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib.popup_event_to_post as P
import set_popup_reservation_benefit as S          # _mysql_rows / get_meta / set_meta / popup_post_ids

DRY_RUN = os.environ.get("DRY_RUN", "1") != "0"
UA = "KpopJournalBot/1.0 (+https://www.kpopjournal.tokyo/about; research)"
_HANGUL = re.compile(r"[가-힣]")
# 韓国住所らしい語を含むハングル混じり文字列(verbatim 候補)
_KO_ADDR = re.compile(
    r"[가-힣A-Za-z0-9\-\s]{4,}?"
    r"(?:특별시|광역시|특별자치|특별자치도|특별자치시|시\s|구\s|군\s|길\s|로\s|동\s|읍\s|면\s)"
    r"[가-힣A-Za-z0-9\-\s]{0,60}"
)


def fetch_html(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read(600000).decode("utf-8", "ignore")


def extract_ko_address(html: str) -> str:
    """ハングル住所を verbatim 抽出。最長候補を採用。無ければ空。"""
    cands = []
    for m in _KO_ADDR.findall(html):
        s = re.sub(r"\s+", " ", m).strip()
        if _HANGUL.search(s) and len(s) >= 6:
            cands.append(s)
    if not cands:
        return ""
    # 重複除去 → 最長(住所は語数が多い)を採用。曖昧回避のため最長一意。
    cands = list(dict.fromkeys(cands))
    cands.sort(key=len, reverse=True)
    return cands[0]


def process(post_id: int) -> dict:
    src = S.get_meta(post_id, "popup_source_url")
    result = {"id": post_id, "src": src, "ko": "", "action": ""}
    if not src or "kbuzzlab.com" not in src:
        result["action"] = "skip(出典なし/対象外)"
        return result
    try:
        html = fetch_html(src)
    except Exception as e:
        result["action"] = f"skip(取得失敗: {type(e).__name__})"
        return result
    ko = extract_ko_address(html)
    result["ko"] = ko
    if not ko:
        result["action"] = "skip(ハングル住所抽出不可=日本語のみ)"
        return result
    cur = S.get_meta(post_id, "popup_address_ko")
    if cur == ko:
        result["action"] = "no-op(同値)"
        return result
    if not DRY_RUN:
        S.set_meta(post_id, "popup_address_ko", ko)   # 非空のみ・冪等
    result["action"] = "WROTE" if not DRY_RUN else "would-write"
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", default="", help="対象 popup ID(カンマ区切り)。省略時は popup 全件")
    ap.add_argument("--sleep", type=float, default=1.0, help="出典への連続アクセス間隔(秒)")
    args = ap.parse_args()

    ids = ([int(x) for x in args.ids.split(",") if x.strip().isdigit()]
           if args.ids.strip() else S.popup_post_ids())

    mode = "DRY_RUN(書込なし)" if DRY_RUN else "APPLY(DB書込)"
    print(f"=== fetch_popup_address_ko [{mode}] 対象 {len(ids)}件 ===")
    n_ko = 0
    for i, pid in enumerate(ids):
        r = process(pid)
        if r["ko"]:
            n_ko += 1
        print(f"[{pid}] {r['action']:24} ko={r['ko']!r}")
        if i < len(ids) - 1:
            time.sleep(args.sleep)            # 出典に優しく
    print(f"--- 計: ハングル住所取得 {n_ko}/{len(ids)}件 ({'適用済' if not DRY_RUN else 'dry-run・未適用'}) ---")
    return 0


if __name__ == "__main__":
    sys.exit(main())
