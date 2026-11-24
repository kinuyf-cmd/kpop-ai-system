#!/usr/bin/env python3
"""AI検索(ChatGPT/Gemini/Copilot/Perplexity/Claude)からの流入レポート(AEO計測)。

背景 (2026-11-08):
  AEO対策の効果を測る手段が無かった。GA4 実測(28d)では全体16,308セッションのうち
  AI由来は約516(3.2%)で、内訳は openai 345 / chatgpt.com 161 / gemini 6 / copilot 4。
  つまり実質 ChatGPT 一極。平均滞在は110〜130秒で、X流入(約13秒)より質が高い。

  GA4 の sessionSource は 'openai' と 'chatgpt.com' に分かれる(同じChatGPT)。
  両方を合算して見ること。

注意:
  - GA4 は確定に24〜48h かかるため LAG_DAYS(=3)前までを対象にする(x_traffic_report と共通)。
  - 移動合計は日次の山で動く。週次は7日窓×4本の並びで見て、1本だけの増減を語らない。
  - 着地記事ごとに FAQPage JSON-LD の有無を本番HTMLで確認する(--check-faq)。
    JSON-LD は `"@type": "FAQPage"` のように空白が入る書式があるため、
    grep は '"@type"' ではなく 'FAQPage' の語で数えること(2026-11-08 に誤判定した実例)。

usage:
  venv_kpi/bin/python3 tools/ai_traffic_report.py                # 直近28日(7日窓×4)
  venv_kpi/bin/python3 tools/ai_traffic_report.py --check-faq    # 着地上位のFAQ有無も確認
  venv_kpi/bin/python3 tools/ai_traffic_report.py --save         # data/ai_traffic_history.jsonl に追記
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import x_traffic_report as t  # noqa: E402  (GA4 クライアントと LAG_DAYS を共用)

AI_SOURCE = re.compile(
    r"chatgpt|openai|perplexity|copilot|claude|gemini|bard|you\.com|phind|kagi", re.I)
HISTORY = ROOT / "data" / "ai_traffic_history.jsonl"
SITE = "https://www.kpopjournal.tokyo"


def _family(src: str) -> str:
    s = src.lower()
    if "chatgpt" in s or "openai" in s:
        return "ChatGPT"
    if "gemini" in s or "bard" in s:
        return "Gemini"
    if "copilot" in s:
        return "Copilot"
    if "perplexity" in s:
        return "Perplexity"
    if "claude" in s:
        return "Claude"
    return src


def collect(days: int) -> dict:
    daily = t._run(["date", "sessionSource"], ["sessions"], days)
    total_rows = t._run(["date"], ["sessions"], days)
    end = date.today() - timedelta(days=t.LAG_DAYS)
    start = end - timedelta(days=days - 1)

    def window(d: str) -> int:
        dt = datetime.strptime(d, "%Y%m%d").date()
        return (dt - start).days // 7

    n_win = (days + 6) // 7
    ai_by_win = [0] * n_win
    tot_by_win = [0] * n_win
    fam = {}
    for r in daily:
        if AI_SOURCE.search(r["sessionSource"]):
            ai_by_win[window(r["date"])] += r["sessions"]
            f = _family(r["sessionSource"])
            fam[f] = fam.get(f, 0) + r["sessions"]
    for r in total_rows:
        tot_by_win[window(r["date"])] += r["sessions"]

    lp = t._run(["sessionSource", "landingPage"], ["sessions"], days)
    pages = {}
    for r in lp:
        if AI_SOURCE.search(r["sessionSource"]):
            pages[r["landingPage"]] = pages.get(r["landingPage"], 0) + r["sessions"]
    top = sorted(pages.items(), key=lambda kv: -kv[1])[:15]
    return {
        "period": f"{start}..{end}",
        "windows_ai": ai_by_win,
        "windows_total": tot_by_win,
        "by_family": dict(sorted(fam.items(), key=lambda kv: -kv[1])),
        "top_landing": top,
    }


def has_faq(path: str) -> bool | None:
    if not path.startswith("/") or path in ("/", "(not set)"):
        return None
    try:
        req = urllib.request.Request(
            SITE + path, headers={"User-Agent": "Mozilla/5.0 (ai_traffic_report)"})
        with urllib.request.urlopen(req, timeout=25) as resp:
            return "FAQPage" in resp.read().decode("utf-8", "replace")
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=28)
    ap.add_argument("--check-faq", action="store_true")
    ap.add_argument("--save", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    res = collect(a.days)
    if a.check_faq:
        res["top_landing"] = [(p, n, has_faq(p)) for p, n in res["top_landing"]]

    if a.save:
        HISTORY.parent.mkdir(exist_ok=True)
        with HISTORY.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"saved": date.today().isoformat(), **res},
                               ensure_ascii=False) + "\n")
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0

    print(f"AI流入レポート {res['period']}(GA4確定分)")
    print("7日窓 古→新  AI:", res["windows_ai"], " 全体:", res["windows_total"])
    for i, (x, y) in enumerate(zip(res["windows_ai"], res["windows_total"])):
        print(f"  窓{i + 1}: AI {x:>4} / 全体 {y:>5} = {x / y * 100:.1f}%" if y else f"  窓{i + 1}: -")
    print("流入元(ChatGPT は openai+chatgpt.com 合算):")
    for k, v in res["by_family"].items():
        print(f"  {k:<11}{v:>5}")
    print("AI流入の着地記事 上位:")
    for row in res["top_landing"]:
        mark = ""
        if len(row) == 3:
            mark = {True: "FAQ有", False: "FAQ無", None: "-"}[row[2]]
        print(f"  {row[1]:>4}  {row[0]}  {mark}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
