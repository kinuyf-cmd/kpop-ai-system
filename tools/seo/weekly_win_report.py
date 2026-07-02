#!/usr/bin/env python3
"""weekly_win_report.py — 週次「勝ち記事」レポート + Lane C候補キュー(2026-07-02)

毎週月曜、GSC実測から以下を自動生成して owner の施策判断を「選ぶだけ」にする:
  1. 勝ち記事    — 7d clicksが前週比+50%以上 or 新規に5clk以上獲得したページ
                   → 成功パターンの横展開判断の材料
  2. Lane C候補  — pos 6-14 × imp>=150 のクエリ×ページ(1ページ目上位への押し上げ候補)
                   → data/lane_c_candidates.json にキュー化(imp降順)
  3. 負け検知    — 7d clicksが前週比-50%以上のページ(順位減衰の早期発見
                   [[seo-golden-cluster-rank-decay]]同型の初動を早める)

出力: Discord weekly_board_report へ要約 + data/weekly_win_report.json に全量。
gsc_snapshot.py と同じ read-only GSC API。課金なし。

使い方:
  venv_kpi/bin/python3 tools/seo/weekly_win_report.py            # 実行+Discord送信
  venv_kpi/bin/python3 tools/seo/weekly_win_report.py --dry-run  # 送信せず表示のみ
"""
import argparse
import datetime
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE / "tools" / "seo"))
from gsc_snapshot import _svc, _query  # 部品を再利用

SITE = "https://www.kpopjournal.tokyo/"
OUT_JSON = BASE / "data" / "weekly_win_report.json"
LANE_C_QUEUE = BASE / "data" / "lane_c_candidates.json"


def build():
    svc = _svc()
    cur = {r["keys"][0]: r for r in _query(svc, ["page"], 7, 0, 500)}
    prev = {r["keys"][0]: r for r in _query(svc, ["page"], 7, 7, 500)}

    wins, losses = [], []
    for page, r in cur.items():
        c, p = r["clicks"], prev.get(page, {}).get("clicks", 0)
        if c >= 5 and (p == 0 or c >= p * 1.5):
            wins.append({"page": page.replace(SITE, "/"), "clicks_7d": c, "clicks_prev": p,
                         "imp": r["impressions"], "pos": round(r["position"], 1)})
    for page, r in prev.items():
        c, p = cur.get(page, {}).get("clicks", 0), r["clicks"]
        if p >= 5 and c <= p * 0.5:
            losses.append({"page": page.replace(SITE, "/"), "clicks_7d": c, "clicks_prev": p})
    wins.sort(key=lambda x: -(x["clicks_7d"] - x["clicks_prev"]))
    losses.sort(key=lambda x: -(x["clicks_prev"] - x["clicks_7d"]))

    # Lane C候補: 28d窓 query×page で pos6-14 × imp>=150
    qp = _query(svc, ["query", "page"], 28, 0, 1000)
    lane_c = sorted([
        {"query": r["keys"][0], "page": r["keys"][1].replace(SITE, "/"),
         "imp": r["impressions"], "clicks": r["clicks"],
         "ctr": round(r["ctr"] * 100, 1), "pos": round(r["position"], 1)}
        for r in qp if 6 <= r["position"] <= 14 and r["impressions"] >= 150
    ], key=lambda x: -x["imp"])[:20]

    return {"generated_at": datetime.datetime.now().isoformat(),
            "wins": wins[:10], "losses": losses[:10], "lane_c_candidates": lane_c}


def notify(report):
    lines = [f"📈 **週次SEO勝ち記事レポート** {datetime.date.today().isoformat()}"]
    if report["wins"]:
        lines.append("\n**🏆 勝ち記事(7d clicks 前週比+50%↑)**")
        for w in report["wins"][:5]:
            lines.append(f"  +{w['clicks_7d']-w['clicks_prev']}clk ({w['clicks_prev']}→{w['clicks_7d']}) pos{w['pos']} {w['page'][:50]}")
    if report["losses"]:
        lines.append("\n**📉 急落(順位減衰の早期シグナル)**")
        for l in report["losses"][:3]:
            lines.append(f"  {l['clicks_prev']}→{l['clicks_7d']}clk {l['page'][:50]}")
    if report["lane_c_candidates"]:
        lines.append(f"\n**🎯 Lane C候補 {len(report['lane_c_candidates'])}件(押し上げ余地・imp順)**")
        for c in report["lane_c_candidates"][:5]:
            lines.append(f"  imp{c['imp']} pos{c['pos']} [{c['query'][:24]}] {c['page'][:40]}")
        lines.append(f"  → 全量: data/lane_c_candidates.json")
    text = "\n".join(lines)[:1900]
    try:
        url = subprocess.run(
            [sys.executable, str(BASE / "lib/resolve_discord_webhook.py"), "weekly_board_report"],
            capture_output=True, text=True, timeout=15).stdout.strip()
        if not url.startswith("https://discord.com/api/webhooks/"):
            print("WARN: webhook解決失敗", file=sys.stderr)
            return
        req = urllib.request.Request(url, data=json.dumps({"content": text}).encode(),
                                     headers={"Content-Type": "application/json",
                                              "User-Agent": "kpop-weekly-win/1.0"})
        urllib.request.urlopen(req, timeout=15)
        print("→ Discord送信OK")
    except Exception as e:
        print(f"WARN: Discord送信失敗: {e}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    report = build()
    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    LANE_C_QUEUE.write_text(json.dumps(
        {"generated_at": report["generated_at"], "candidates": report["lane_c_candidates"]},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"勝ち{len(report['wins'])} / 負け{len(report['losses'])} / LaneC候補{len(report['lane_c_candidates'])}")
    for w in report["wins"][:5]:
        print(f"  🏆 +{w['clicks_7d']-w['clicks_prev']}clk {w['page'][:55]}")
    for c in report["lane_c_candidates"][:5]:
        print(f"  🎯 imp{c['imp']} pos{c['pos']} [{c['query'][:26]}] {c['page'][:38]}")
    if not args.dry_run:
        notify(report)


if __name__ == "__main__":
    main()
