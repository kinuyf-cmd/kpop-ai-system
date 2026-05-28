#!/usr/bin/env python3
"""x_ab_summary.py — M10 ABテストの集計。

logs/x_ab_log.jsonl の各tweet_idについて X /2/tweets で public_metrics を取得し、
variant別 (A=ペルソナ / B=Pop Crave) に imp/like/rt/reply/bookmark を集計。

Usage:
  venv_kpi/bin/python tools/x_ab_summary.py                  # 全期間
  venv_kpi/bin/python tools/x_ab_summary.py --since 24h      # 直近24時間
  venv_kpi/bin/python tools/x_ab_summary.py --since 72h --json
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

AB_LOG = os.path.join(BASE_DIR, "logs", "x_ab_log.jsonl")


def _parse_since(s: str) -> timedelta | None:
    if not s:
        return None
    if s.endswith("h"):
        return timedelta(hours=int(s[:-1]))
    if s.endswith("d"):
        return timedelta(days=int(s[:-1]))
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="", help="集計対象期間。例 24h / 72h / 7d")
    ap.add_argument("--json", action="store_true", help="JSONで出力")
    args = ap.parse_args()

    if not os.path.exists(AB_LOG):
        print(f"AB log not found: {AB_LOG}", file=sys.stderr)
        return 1

    since = _parse_since(args.since)
    cutoff = datetime.now() - since if since else None

    entries = []
    for line in open(AB_LOG, encoding="utf-8"):
        try:
            r = json.loads(line)
        except Exception:
            continue
        if cutoff:
            try:
                if datetime.fromisoformat(r["ts"]).replace(tzinfo=None) < cutoff:
                    continue
            except Exception:
                pass
        if r.get("tweet_id"):
            entries.append(r)

    if not entries:
        print("AB log: 集計対象なし")
        return 0

    # public_metrics をまとめ取得 (100件/req まで)
    from google_metrics.post_to_x import get_public_metrics, validate_credentials
    creds, errs = validate_credentials()
    if not creds:
        print(f"認証NG: {errs}", file=sys.stderr)
        return 1

    ids = [e["tweet_id"] for e in entries]
    metrics = get_public_metrics(ids, creds=creds)

    # variant別集計
    agg = defaultdict(lambda: {"n": 0, "imp": 0, "like": 0, "rt": 0,
                                "reply": 0, "bookmark": 0, "quote": 0})
    samples = defaultdict(list)
    for e in entries:
        v = e.get("variant") or "?"
        m = metrics.get(e["tweet_id"], {})
        a = agg[v]
        a["n"] += 1
        a["imp"] += int(m.get("impression_count", 0))
        a["like"] += int(m.get("like_count", 0))
        a["rt"] += int(m.get("retweet_count", 0))
        a["reply"] += int(m.get("reply_count", 0))
        a["bookmark"] += int(m.get("bookmark_count", 0))
        a["quote"] += int(m.get("quote_count", 0))
        if len(samples[v]) < 3:
            samples[v].append({
                "tweet_id": e["tweet_id"], "title": e.get("title", "")[:60],
                "imp": int(m.get("impression_count", 0)),
                "like": int(m.get("like_count", 0)),
            })

    result = {
        "since": args.since or "全期間",
        "entries": len(entries),
        "by_variant": {},
        "samples": dict(samples),
    }
    for v, a in agg.items():
        n = max(a["n"], 1)
        result["by_variant"][v] = {
            **a,
            "imp_avg": round(a["imp"] / n, 2),
            "like_avg": round(a["like"] / n, 2),
            "eng_rate_pct": round(
                (a["like"] + a["rt"] + a["reply"] + a["bookmark"]) / max(a["imp"], 1) * 100, 2
            ),
        }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print(f"=== M10 AB 集計 ({result['since']}, n={result['entries']}) ===")
    for v in sorted(result["by_variant"]):
        a = result["by_variant"][v]
        print(f"\n[variant {v}] n={a['n']}")
        print(f"  imp合計={a['imp']}  平均={a['imp_avg']}")
        print(f"  like={a['like']} (avg {a['like_avg']}) / rt={a['rt']} / reply={a['reply']} / bookmark={a['bookmark']}")
        print(f"  エンゲージ率={a['eng_rate_pct']}%")
        for s in samples[v]:
            print(f"    {s['tweet_id']} imp={s['imp']} like={s['like']} {s['title']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
