#!/usr/bin/env python3
"""X会話型が型A(感想→起で止め、結はリプ)になっているかを実ログで測る。

owner指定(2026-08-20)の型Aを導入したあと、実際に出た投稿が型Aを満たして
いるか、そのときエンゲージ率がどうかを並べて追うためのツール。

  型A: 本文=感想(1文)→起(+承転)、結は書かない / リプ=結+URL

Usage:
  python3 tools/x_type_a_report.py                # 直近30本
  python3 tools/x_type_a_report.py --limit 60
  python3 tools/x_type_a_report.py --since 2026-08-20   # 型A導入日以降
  python3 tools/x_type_a_report.py --json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from lib.x_traffic_picker import check_hook_structure_type_a  # noqa: E402
from lib.x_engagement import engagement_rate, summarize_engagement  # noqa: E402

POSTS_LOG = BASE / "logs" / "x_posts.jsonl"


def load_posts(limit: int, since: str = "") -> list[dict]:
    """会話型の本文投稿だけを新しい順に返す(URLリプ等は除く)。"""
    if not POSTS_LOG.exists():
        return []
    out = []
    for line in reversed(POSTS_LOG.read_text(encoding="utf-8").splitlines()):
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        if d.get("mode") == "url_reply":
            continue
        text = (d.get("text") or "").strip()
        if not text:
            continue
        ts = str(d.get("ts") or "")
        if since and ts[:10] < since:
            continue
        out.append(d)
        if limit and len(out) >= limit:
            break
    return out


def _body_only(text: str) -> str:
    """ハッシュタグ行/URLを落として本文だけにする。"""
    t = re.sub(r"https?://\S+", "", text)
    t = re.sub(r"\n+#.*$", "", t)
    return re.sub(r"#\S+", "", t).strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--since", default="")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-metrics", action="store_true",
                    help="X API を叩かず構成判定だけ行う")
    a = ap.parse_args()

    posts = load_posts(a.limit, a.since)
    if not posts:
        print("対象の投稿が無い")
        return 0

    # メトリクスは任意(API が使えない環境でも構成判定はできるようにする)
    metrics: dict = {}
    if not a.no_metrics:
        ids = [str(p.get("tweet_id")) for p in posts if p.get("tweet_id")]
        if ids:
            try:
                from google_metrics.post_to_x import get_public_metrics
                for i in range(0, len(ids), 100):
                    metrics.update(get_public_metrics(ids[i:i + 100]) or {})
            except Exception as e:
                print(f"[warn] メトリクス取得に失敗: {e}", file=sys.stderr)

    rows = []
    for p in posts:
        body = _body_only(p.get("text") or "")
        chk = check_hook_structure_type_a(body)
        tid = str(p.get("tweet_id") or "")
        m = metrics.get(tid, {})
        rows.append({
            "ts": str(p.get("ts") or "")[:16],
            "tweet_id": tid,
            "type_a": bool(chk["ok"]),
            "issue": chk["issue"],
            "engagement_rate": engagement_rate(m),
            "impression": int(m.get("impression_count", 0) or 0) if m else None,
            "text": body[:70],
        })

    ok = [r for r in rows if r["type_a"]]
    ng = [r for r in rows if not r["type_a"]]
    ok_m = {r["tweet_id"]: metrics.get(r["tweet_id"], {}) for r in ok}
    ng_m = {r["tweet_id"]: metrics.get(r["tweet_id"], {}) for r in ng}

    summary = {
        "n": len(rows),
        "type_a_count": len(ok),
        "type_a_rate": round(len(ok) / len(rows) * 100, 1) if rows else 0.0,
        "type_a_engagement": summarize_engagement(ok_m),
        "non_type_a_engagement": summarize_engagement(ng_m),
    }

    if a.json:
        print(json.dumps({"summary": summary, "posts": rows}, ensure_ascii=False))
        return 0

    print(f"対象 {summary['n']}本 / 型A適合 {summary['type_a_count']}本 "
          f"({summary['type_a_rate']}%)")
    ta, na = summary["type_a_engagement"], summary["non_type_a_engagement"]
    print(f"  型A     : n={ta['n']} 平均エンゲージ率 {ta['avg_engagement_rate']}%")
    print(f"  型A以外 : n={na['n']} 平均エンゲージ率 {na['avg_engagement_rate']}%")
    print()
    for r in rows[:25]:
        mark = "○" if r["type_a"] else "×"
        er = f"{r['engagement_rate']}%" if r["engagement_rate"] is not None else "-"
        print(f" {mark} {r['ts']} ER{er:>7} {r['text']}")
        if not r["type_a"]:
            print(f"     └ {r['issue']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
