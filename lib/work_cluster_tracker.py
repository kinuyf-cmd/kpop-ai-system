#!/usr/bin/env python3
"""work_cluster_tracker.py — 作品クラスタの成否を配信日基準で追跡する

背景 (2026-08-23 実測):
  作品クラスタ(ガイド/相関図/声優の3本セット)は速報の91倍のimp・62倍のclickを
  生む。ただし47本中15本はクリック0で、当たり外れが極端。

  分析でわかったこと:
    1. 記事公開タイミング(配信前/後)は成否を分けない
       恋は飴模様(-18日) も 鉄槌教師(+17日) も当たっている
    2. 分けるのは作品自体の検索需要。imp>=1000 は平均clk307、
       1000未満は平均clk6 で47倍差
    3. 需要は配信後にしか測れない。しかも記事公開直後は配信前なので
       imp が小さく、そこで判断すると誤る
       (恋は飴模様: 7〜13日目 imp69 → 14〜20日目 imp3,417 に急増)

  よって「事前に当たりを予測する」のではなく、
  「配信から十分な日数が経ってから正しく評価し、当たった作品に追加投資する」。

Usage:
  python3 lib/work_cluster_tracker.py --list          # 追跡中の作品
  python3 lib/work_cluster_tracker.py --add "作品名" --release 2026-09-01
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

STATE = BASE / "data" / "work_clusters.json"

# 配信からこの日数が経つまでは判定しない(配信前の imp で誤判定しないため)
MIN_DAYS_AFTER_RELEASE = 14
# 「当たり」とみなす検索需要(90日 imp)。実測で1000前後が分かれ目
HIT_IMP_THRESHOLD = 1000

VERDICT_TOO_EARLY = "too_early"


def evaluate_work(name: str, imp: int, days_since_release) -> dict:
    """作品クラスタの成否を判定する。

    days_since_release が None または MIN_DAYS_AFTER_RELEASE 未満なら
    判定を保留する(早すぎる判定は「当たる作品」を捨ててしまう)。
    """
    if days_since_release is None or days_since_release < MIN_DAYS_AFTER_RELEASE:
        d = "不明" if days_since_release is None else f"{days_since_release}日"
        return {"name": name, "verdict": VERDICT_TOO_EARLY, "imp": imp,
                "message": f"{name}: 配信からの経過が{d}のため判定保留"
                           f"(配信後{MIN_DAYS_AFTER_RELEASE}日以降に評価)"}
    if imp >= HIT_IMP_THRESHOLD:
        return {"name": name, "verdict": "hit", "imp": imp,
                "message": f"{name}: 需要imp {imp:,} → 当たり。関連記事の追加が有効"}
    return {"name": name, "verdict": "miss", "imp": imp,
            "message": f"{name}: 需要imp {imp:,} → 伸びず。追加投資はしない"}


def _load() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"works": []}


def _save(d: dict) -> None:
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def _demand(keyword: str, days: int = 90) -> int:
    """GSC でその作品名を含むクエリの imp 合計を取る。"""
    try:
        from lib.seo_opportunity_scanner import fetch_queries
        k = keyword.lower().replace("・", "")
        return sum(r["impressions"] for r in fetch_queries(days)
                   if k in r["keys"][0].lower().replace("・", ""))
    except Exception:
        return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--add", help="追跡する作品名")
    ap.add_argument("--release", help="配信開始日 YYYY-MM-DD")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()

    st = _load()
    if a.add:
        st["works"] = [w for w in st["works"] if w["name"] != a.add]
        st["works"].append({"name": a.add, "release": a.release or ""})
        _save(st)
        print(f"追加: {a.add} (配信 {a.release or '未定'})")
        return 0

    if not st["works"]:
        print("追跡中の作品なし。--add で登録してください。")
        return 0

    print("=== 作品クラスタの評価(配信日基準) ===")
    for w in st["works"]:
        rel = w.get("release") or ""
        days = None
        if rel:
            try:
                days = (date.today() - date.fromisoformat(rel)).days
            except ValueError:
                days = None
        imp = _demand(w["name"])
        r = evaluate_work(w["name"], imp, days)
        mark = {"hit": "◎", "miss": "×", VERDICT_TOO_EARLY: "…"}[r["verdict"]]
        print(f"  {mark} {r['message']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
