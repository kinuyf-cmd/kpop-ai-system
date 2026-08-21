#!/usr/bin/env python3
"""x_concrete_effect.py — 具体ゲート導入の効果を実測する

背景 (2026-08-21):
  Phase1以降のトップレベル投稿を自動/手動で分けると、自動 平均imp 109.5 に対し
  手動は 991.2 で 9倍差があった。伸びた手動投稿はいずれも日時/会場/条件を
  含み、自動投稿は感想だけで情報量がゼロだった。
  そこで has_concrete_info() の具体ゲートを新設した(commit aa044ac)。

  このツールは「具体を含む投稿は本当に伸びるのか」を継続的に検証する。
  導入前後の比較ではなく、投稿1本ごとに具体の有無で分けて imp を比べる。
  imp は分母なので、平均ではなく imp加重 と 中央値 の両方を出す
  (算術平均だとバン期の imp=2〜5 の投稿が ER を跳ね上げて誤読を招く)。

使い方:
    python3 tools/x_concrete_effect.py                # Phase1以降を集計
    python3 tools/x_concrete_effect.py --since 2026-08-21   # ゲート導入後だけ
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "google_metrics"))

from lib.x_traffic_picker import has_concrete_info  # noqa: E402

POSTS_LOG = BASE / "logs" / "x_posts.jsonl"
PHASE1_START = "2026-08-12"
AGE_H = 24  # imp が固まるまで待つ


def _posts(since: str) -> list[dict]:
    """自動投稿のトップレベルのみ。手動投稿は logs に無いので自然に除かれる。"""
    if not POSTS_LOG.exists():
        return []
    hi = datetime.now() - timedelta(hours=AGE_H)
    out = []
    for line in POSTS_LOG.read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        if d.get("status") != "ok" or not d.get("tweet_id"):
            continue
        if d.get("reply_to") or d.get("mode") == "url_reply":
            continue
        ts = str(d.get("ts") or "")
        if ts[:10] < since:
            continue
        try:
            if datetime.fromisoformat(ts) > hi:
                continue
        except ValueError:
            continue
        out.append(d)
    return out


def _metrics(ids: list[str]) -> dict:
    from post_to_x import get_public_metrics
    m = {}
    for i in range(0, len(ids), 100):
        m.update(get_public_metrics(ids[i:i + 100]) or {})
    return m


def _summarize(rows: list[tuple[int, int]]) -> dict:
    if not rows:
        return {}
    imps = [r[0] for r in rows]
    ti = sum(imps)
    te = sum(r[1] for r in rows)
    return {
        "n": len(rows),
        "imp_total": ti,
        "imp_mean": round(ti / len(rows), 1),
        "imp_median": statistics.median(imps),
        "eng_total": te,
        # imp加重ER。算術平均のERは低imp投稿に引きずられて誤読になる
        "er_weighted": round(te / ti * 100, 2) if ti else 0.0,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=PHASE1_START)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    posts = _posts(a.since)
    if not posts:
        print(f"対象の投稿が無い (since={a.since}, {AGE_H}h以上経過が条件)")
        return 1
    met = _metrics([str(p["tweet_id"]) for p in posts])

    groups: dict[bool, list] = {True: [], False: []}
    for p in posts:
        d = met.get(str(p["tweet_id"]))
        if not d:
            continue
        imp = int(d.get("impression_count", 0) or 0)
        eng = sum(int(d.get(k, 0) or 0) for k in
                  ("like_count", "reply_count", "retweet_count",
                   "quote_count", "bookmark_count"))
        groups[has_concrete_info(p.get("text", ""))["ok"]].append((imp, eng))

    res = {"since": a.since,
           "concrete": _summarize(groups[True]),
           "vague": _summarize(groups[False])}
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0

    print(f"=== 具体ゲートの効果 (since={a.since}, {AGE_H}h以上経過) ===")
    for label, key in (("具体あり", "concrete"), ("具体なし", "vague")):
        s = res[key]
        if not s:
            print(f"  [{label}] 該当なし")
            continue
        print(f"  [{label}] n={s['n']}  imp合計={s['imp_total']}  "
              f"平均={s['imp_mean']}  中央={s['imp_median']}  "
              f"加重ER={s['er_weighted']}%")
    c, v = res["concrete"], res["vague"]
    if c and v and v["imp_median"]:
        print(f"\n  中央値比 (具体あり/なし) = {c['imp_median'] / v['imp_median']:.2f}倍")
    if not c:
        print("\n  ※ 具体ありがまだ0件。ゲート導入直後はここが埋まるまで判定できない。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
