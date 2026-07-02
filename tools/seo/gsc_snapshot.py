#!/usr/bin/env python3
"""gsc_snapshot.py — SEO状況を1コマンドで実測レポート(2026-07-02)

「SEOの状況確認して」の定型調査を恒久コマンド化したもの。
480日累積の幻を避け、常に直近28d/7dの実測で判断する
([[seo-opportunity-480d-vs-28d-mirage]] 準拠)。

出力セクション:
  1. トレンド(28d vs 前28d、7d vs 前7d)
  2. 上位クエリ/上位ページ(28d clicks順)
  3. CTR機会(pos<=10 × imp>=200 × ctr<3%)
  4. 1ページ目押し上げ候補(pos11-20 × imp>=300)
  5. 急上昇クエリ(7d imp>=100 で前7d比1.5倍+)

使い方:
  venv_kpi/bin/python3 tools/seo/gsc_snapshot.py            # 人間向けテキスト
  venv_kpi/bin/python3 tools/seo/gsc_snapshot.py --json     # 機械可読(他ツール連携用)
  venv_kpi/bin/python3 tools/seo/gsc_snapshot.py --days 14  # 窓を変更(既定28)

GSC APIはservice_account読み取り専用。書き込み・課金は一切なし。
"""
import argparse
import datetime
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent
SA = BASE / "google_metrics" / "service_account.json"
SITE = "https://www.kpopjournal.tokyo/"
GSC_LAG_DAYS = 3  # GSCデータは通常2-3日遅延


def _svc():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    creds = service_account.Credentials.from_service_account_file(
        str(SA), scopes=["https://www.googleapis.com/auth/webmasters.readonly"])
    return build("searchconsole", "v1", credentials=creds, cache_discovery=False)


def _range(days: int, back: int = 0):
    end = datetime.date.today() - datetime.timedelta(days=GSC_LAG_DAYS + back)
    start = end - datetime.timedelta(days=days - 1)
    return start.isoformat(), end.isoformat()


def _query(svc, dims, days, back=0, limit=250):
    s, e = _range(days, back)
    body = {"startDate": s, "endDate": e, "dimensions": dims, "rowLimit": limit}
    return svc.searchanalytics().query(siteUrl=SITE, body=body).execute().get("rows", [])


def snapshot(days: int = 28) -> dict:
    svc = _svc()
    out = {"generated_at": datetime.datetime.now().isoformat(), "window_days": days}

    # 1. トレンド
    def totals(d, back):
        r = _query(svc, [], d, back, 1)
        row = r[0] if r else {}
        return {"clicks": row.get("clicks", 0), "impressions": row.get("impressions", 0),
                "ctr": row.get("ctr", 0), "position": row.get("position", 0)}
    out["trend"] = {
        "cur": totals(days, 0), "prev": totals(days, days),
        "cur7": totals(7, 0), "prev7": totals(7, 7),
    }
    s, e = _range(days)
    out["trend"]["period"] = f"{s}..{e}"

    # 2. 上位クエリ/ページ
    out["top_queries"] = [
        {"query": r["keys"][0], "clicks": r["clicks"], "imp": r["impressions"],
         "ctr": round(r["ctr"] * 100, 1), "pos": round(r["position"], 1)}
        for r in sorted(_query(svc, ["query"], days), key=lambda x: -x["clicks"])[:15]]
    out["top_pages"] = [
        {"page": r["keys"][0].replace(SITE, "/"), "clicks": r["clicks"],
         "imp": r["impressions"], "ctr": round(r["ctr"] * 100, 1), "pos": round(r["position"], 1)}
        for r in sorted(_query(svc, ["page"], days), key=lambda x: -x["clicks"])[:12]]

    # 3. CTR機会
    qs = _query(svc, ["query"], days)
    out["ctr_opportunities"] = sorted([
        {"query": r["keys"][0], "imp": r["impressions"], "ctr": round(r["ctr"] * 100, 1),
         "pos": round(r["position"], 1)}
        for r in qs if r["position"] <= 10 and r["impressions"] >= 200 and r["ctr"] < 0.03
    ], key=lambda x: -x["imp"])[:12]

    # 4. 1ページ目押し上げ候補
    ps = _query(svc, ["page"], days, limit=300)
    out["page2_candidates"] = sorted([
        {"page": r["keys"][0].replace(SITE, "/"), "imp": r["impressions"],
         "clicks": r["clicks"], "pos": round(r["position"], 1)}
        for r in ps if 11 <= r["position"] <= 20 and r["impressions"] >= 300
    ], key=lambda x: -x["imp"])[:12]

    # 5. 急上昇クエリ(7d)
    cur7 = {r["keys"][0]: r for r in _query(svc, ["query"], 7, 0)}
    prev7 = {r["keys"][0]: r for r in _query(svc, ["query"], 7, 7)}
    rising = []
    for k, r in cur7.items():
        if r["impressions"] < 100:
            continue
        p = prev7.get(k, {}).get("impressions", 0)
        if p == 0 or r["impressions"] > p * 1.5:
            rising.append({"query": k, "imp": r["impressions"], "delta": r["impressions"] - p,
                           "clicks": r["clicks"], "pos": round(r["position"], 1)})
    out["rising_queries"] = sorted(rising, key=lambda x: -x["delta"])[:12]
    return out


def render(o: dict) -> str:
    L = []
    t = o["trend"]

    def pct(c, p):
        return f"{(c - p) / p * 100:+.1f}%" if p else "n/a"
    L.append(f"═══ SEOスナップショット ({o['trend']['period']}, {o['window_days']}d窓) ═══")
    c, p = t["cur"], t["prev"]
    L.append(f"[トレンド] clicks {c['clicks']:.0f} ({pct(c['clicks'], p['clicks'])})  "
             f"imp {c['impressions']:.0f} ({pct(c['impressions'], p['impressions'])})  "
             f"CTR {c['ctr']*100:.2f}%  pos {c['position']:.1f}")
    c7, p7 = t["cur7"], t["prev7"]
    L.append(f"[直近7d ] clicks {c7['clicks']:.0f} ({pct(c7['clicks'], p7['clicks'])})  "
             f"imp {c7['impressions']:.0f}  pos {c7['position']:.1f}")
    L.append("\n─── 上位クエリ ───")
    for r in o["top_queries"][:10]:
        L.append(f"  {r['clicks']:4.0f}clk imp{r['imp']:5.0f} ctr{r['ctr']:4.1f}% pos{r['pos']:4.1f}  {r['query']}")
    L.append("\n─── 上位ページ ───")
    for r in o["top_pages"][:10]:
        L.append(f"  {r['clicks']:4.0f}clk imp{r['imp']:5.0f} pos{r['pos']:4.1f}  {r['page'][:58]}")
    L.append("\n─── CTR機会 (pos≤10 × imp≥200 × ctr<3%) ───")
    for r in o["ctr_opportunities"] or []:
        L.append(f"  imp{r['imp']:5.0f} ctr{r['ctr']:4.1f}% pos{r['pos']:4.1f}  {r['query']}")
    if not o["ctr_opportunities"]:
        L.append("  (該当なし)")
    L.append("\n─── 1ページ目押し上げ候補 (pos11-20 × imp≥300) ───")
    for r in o["page2_candidates"] or []:
        L.append(f"  imp{r['imp']:5.0f} clk{r['clicks']:3.0f} pos{r['pos']:4.1f}  {r['page'][:55]}")
    if not o["page2_candidates"]:
        L.append("  (該当なし)")
    L.append("\n─── 急上昇クエリ (7d imp≥100, 前週比1.5倍+) ───")
    for r in o["rising_queries"] or []:
        L.append(f"  imp{r['imp']:5.0f}(+{r['delta']:.0f}) clk{r['clicks']:3.0f} pos{r['pos']:4.1f}  {r['query']}")
    if not o["rising_queries"]:
        L.append("  (該当なし)")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description="GSC実測スナップショット")
    ap.add_argument("--json", action="store_true", help="JSON出力(機械可読)")
    ap.add_argument("--days", type=int, default=28, help="集計窓(既定28)")
    args = ap.parse_args()
    if not SA.exists():
        print(f"ERR: service_account が見つからない: {SA}", file=sys.stderr)
        sys.exit(2)
    o = snapshot(args.days)
    if args.json:
        print(json.dumps(o, ensure_ascii=False, indent=2))
    else:
        print(render(o))


if __name__ == "__main__":
    main()
