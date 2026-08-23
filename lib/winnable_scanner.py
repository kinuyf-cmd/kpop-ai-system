#!/usr/bin/env python3
"""winnable_scanner.py — 「3位以内を取れる」候補だけを抽出する

背景 (2026-08-23 実測):
  page_one_tracker は5週連続で pos<3 進入がゼロだった。既存の SEO パイプラインは
  動いていたが、1ページ目(pos4-10)止まりで、そこは CTR 2% 前後しかない。
  一方 pos1-3 は CTR 6.96%。**3位以内に入らないと回収できない**構造。

  そこで「上げれば3位以内に届きそうな場所」だけに絞る。実測した勝ち筋:
    - 複合語(2語以上) CTR 21.4% > 単独名詞 CTR 14.2%
    - ブランド名(kジャーナル等)は既に上位だが意図不一致で回収不能

Usage:
  python3 lib/winnable_scanner.py              # 候補を表示
  python3 lib/winnable_scanner.py --json
  python3 lib/winnable_scanner.py --days 28
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

# ブランド名(サイト名)クエリ。既に上位で、かつ意図不一致で回収できない
BRAND_RE = re.compile(r"(ジャーナル|journal|じゃーなる|kpopj|ｋジャーナル)", re.I)

# 狙う順位帯: 3位以内に届く現実味がある範囲
POS_MIN, POS_MAX = 3.5, 12.0
# これ未満の imp は上げても回収できない(90日換算)
MIN_IMP = 50

OUT = BASE / "data" / "winnable_queue.json"


def _query(row) -> str:
    return (row.get("keys") or [""])[0]


def is_winnable(row) -> bool:
    """3位以内を狙う価値がある候補か。"""
    q = _query(row)
    if not q or BRAND_RE.search(q):
        return False
    if row.get("impressions", 0) < MIN_IMP:
        return False
    p = row.get("position", 999)
    return POS_MIN <= p <= POS_MAX


def score_candidate(row) -> float:
    """優先度スコア。imp が大きく・順位が近く・複合語ほど高い。"""
    imp = float(row.get("impressions", 0))
    pos = float(row.get("position", 99))
    q = _query(row)
    # 順位が3位に近いほど倍率が高い(4位=1.0 → 12位=0.3)
    prox = max(0.3, 1.0 - (pos - POS_MIN) * 0.08)
    # 複合語ボーナス(実測 CTR 21.4% vs 14.2%)
    words = len([w for w in re.split(r"[\s　]+", q) if w])
    multi = 1.5 if (words >= 2 or len(q) >= 10) else 1.0
    return imp * prox * multi


def leading_term_missing(query: str, title: str) -> bool:
    """検索語の主要部分がタイトルの先頭側に無いかを判定する。

    2026-08-23 実測: 「恋は雨模様 相関図」(imp6,379) は CTR0.74% なのに、
    「恋は飴模様」は CTR2.52% と3.4倍差。記事タイトルが
    『恋は飴模様』(恋は雨模様)… の順で、最多検索語がタイトル先頭に無かった。
    タイトル前半(表示で切られない範囲)に主要語が入っているかを見る。
    """
    qs = str(query or "").strip()
    t = str(title or "")
    if not qs or not t:
        return False
    # 検索語の主要部 = 最初の語(スペース区切り)。無ければ全体。
    head = re.split(r"[\s　]+", qs)[0].lower()
    if not head:
        return False
    # 括弧内(補足表記)は「タイトル先頭」とみなさない。実測で
    # 『恋は飴模様』(恋は雨模様)… は「雨模様」検索で CTR0.74% しか出なかった。
    t_main = re.sub(r"[(（\[][^)）\]]*[)）\]]", "", t)
    # 中黒・読点も落とす(「ユジン怪我」×「アン・ユジン、負傷で…」は成功例で、
    # 表記差で誤検出してはいけない)
    _strip = lambda x: re.sub(r"[『』「」()（）\[\]|｜\-–—\s　・、,，]", "", x).lower()
    tc = _strip(t_main)
    h = _strip(head)
    idx = tc.find(h)
    if idx < 0 and len(h) >= 4:
        # 「ユジン怪我」のように語がつながっている場合、前半だけで再照合する
        idx = tc.find(h[:max(3, len(h) // 2)])
    if idx < 0:
        return True          # そもそも入っていない
    # 入っていても後ろすぎるとタイトル先頭に見えない(実測でCTR3.4倍差)
    return idx > 6


def collect(days: int = 90) -> list[dict]:
    from lib.seo_opportunity_scanner import fetch_queries
    rows = fetch_queries(days)
    out = []
    for r in rows:
        if not is_winnable(r):
            continue
        out.append({
            "query": _query(r),
            "impressions": r.get("impressions", 0),
            "clicks": r.get("clicks", 0),
            "position": round(float(r.get("position", 0)), 1),
            "score": round(score_candidate(r), 1),
            # 3位以内(CTR6.96%)まで上げた時の増分クリック見込み
            "potential_clicks": round(r.get("impressions", 0) * 0.0696
                                      - r.get("clicks", 0), 1),
        })
    out.sort(key=lambda x: -x["score"])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--limit", type=int, default=25)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    cands = collect(a.days)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({"days": a.days, "count": len(cands),
                               "items": cands}, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    if a.json:
        print(json.dumps(cands[:a.limit], ensure_ascii=False, indent=1))
        return 0
    print(f"=== 3位以内を狙える候補 {len(cands)}件 (直近{a.days}日) ===")
    print(f"  条件: pos{POS_MIN}〜{POS_MAX} / imp{MIN_IMP}以上 / ブランド名除外\n")
    print(f"  {'score':>7}{'imp':>7}{'clk':>5}{'pos':>6}{'+見込':>7}  query")
    for c in cands[:a.limit]:
        print(f"  {c['score']:>7.0f}{c['impressions']:>7,}{c['clicks']:>5}"
              f"{c['position']:>6.1f}{c['potential_clicks']:>7.1f}  {c['query']}")
    tot = sum(c["potential_clicks"] for c in cands)
    print(f"\n  全候補を3位以内に上げた場合の増分: +{tot:,.0f} clicks/{a.days}日")
    print(f"  → 保存: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
