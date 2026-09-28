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

3-5 の候補には2つのガードを掛ける(2026-09-28、同じ誤読を2度踏んだため):
  - 単日スパイク除外: 窓内の最大単日imp / 合計imp > SPIKE_SHARE は本表から外し
    「除外(単日スパイク)」に回す。/artists/cortis/ imp1409 の 918 が 09-07 の単日だった
    ([[gsc-7d-window-and-fragment-artifacts]])。
  - 対策済みの印: AIOSEO title 設定済 / 本文の FAQPage・TVSeries を DB から引いて表示。
    推奨前に「もう打った手か」を見るため(kpop-wp-ro の SELECT のみ。失敗時は印なしで続行)。

使い方:
  venv_kpi/bin/python3 tools/seo/gsc_snapshot.py            # 人間向けテキスト
  venv_kpi/bin/python3 tools/seo/gsc_snapshot.py --json     # 機械可読(他ツール連携用)
  venv_kpi/bin/python3 tools/seo/gsc_snapshot.py --days 14  # 窓を変更(既定28)

GSC APIはservice_account読み取り専用。書き込み・課金は一切なし。
"""
import argparse
import datetime
import json
import re
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent
SA = BASE / "google_metrics" / "service_account.json"
SITE = "https://www.kpopjournal.tokyo/"
GSC_LAG_DAYS = 3  # GSCデータは通常2-3日遅延
SPIKE_SHARE = 0.5  # 最大単日imp/合計imp がこれを超えたらスパイク扱い
RO = "/usr/local/sbin/kpop/kpop-wp-ro"
_SLUG_RE = re.compile(r"^[a-z0-9%_-]+$")


def spike_share(daily) -> float:
    total = sum(daily)
    return max(daily) / total if total else 0


def split_spikes(items, key, daily_map):
    """items を (定常, スパイク) に分ける。日次が取れない候補は定常側に残す。"""
    kept, spikes = [], []
    for r in items:
        daily = daily_map.get(r[key])
        share = spike_share(daily) if daily else 0
        if share > SPIKE_SHARE:
            spikes.append({**r, "spike_share": round(share, 2)})
        else:
            kept.append(r)
    return kept, spikes


def slug_from_page(page: str):
    path = page.replace(SITE, "/").split("#")[0].strip("/")
    slug = path.rsplit("/", 1)[-1] if path else ""
    return slug if _SLUG_RE.match(slug) else None


def parse_treatment(out: str) -> dict:
    res = {}
    for line in out.splitlines()[1:]:
        f = line.split("\t")
        if len(f) < 6:
            continue
        name, title_set, updated, faq, tv = f[0], f[1], f[2], f[3], f[4]
        res[name] = {
            "title_set": title_set == "1",
            "updated": None if updated in ("NULL", "") else updated[:10],
            "schema": [n for n, v in (("FAQPage", faq), ("TVSeries", tv)) if v not in ("0", "NULL")],
        }
    return res


def treatment_label(t) -> str:
    if not t or not (t["title_set"] or t["schema"]):
        return ""
    parts = (["title"] if t["title_set"] else []) + t["schema"]
    date = f" {t['updated'][5:]}" if t["updated"] else ""
    return f"[対策済 {'+'.join(parts)}{date}]"


def _treatments(slugs) -> dict:
    slugs = sorted({s for s in slugs if s})
    if not slugs:
        return {}
    in_list = ",".join(f"'{s}'" for s in slugs)
    sql = ("SELECT p.post_name, MAX(a.title IS NOT NULL AND a.title<>'') title_set, MAX(a.updated) updated, "
           "LOCATE('FAQPage',p.post_content) faq, LOCATE('TVSeries',p.post_content) tvseries, "
           "LOCATE('ld+json',p.post_content) ldjson FROM wp_posts p "
           "LEFT JOIN wp_aioseo_posts a ON a.post_id=p.ID "
           f"WHERE p.post_status='publish' AND p.post_name IN ({in_list}) GROUP BY p.ID")
    try:
        r = subprocess.run(["sudo", "-n", RO, "db", "query", sql],
                           capture_output=True, text=True, timeout=60)
    except Exception:
        return {}
    return parse_treatment(r.stdout) if r.returncode == 0 else {}


def _daily(svc, dim, value, days):
    """候補1件の窓内日次imp と、query の場合は最多impページを返す。"""
    s, e = _range(days)
    dims = ["date", "page"] if dim == "query" else ["date"]
    body = {"startDate": s, "endDate": e, "dimensions": dims, "rowLimit": 5000,
            "dimensionFilterGroups": [{"filters": [
                {"dimension": dim, "operator": "equals",
                 "expression": value if dim == "query" else SITE + value.lstrip("/")}]}]}
    rows = svc.searchanalytics().query(siteUrl=SITE, body=body).execute().get("rows", [])
    by_date, by_page = {}, {}
    for r in rows:
        by_date[r["keys"][0]] = by_date.get(r["keys"][0], 0) + r["impressions"]
        if dim == "query":
            pg = r["keys"][1].replace(SITE, "/").split("#")[0]
            by_page[pg] = by_page.get(pg, 0) + r["impressions"]
    top = max(by_page, key=by_page.get) if by_page else None
    return list(by_date.values()), top


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

    # ガード: 単日スパイク除外 + 対策済みの印
    out["spikes"] = []
    slugs = []
    for sec, key, win in (("ctr_opportunities", "query", days),
                          ("page2_candidates", "page", days),
                          ("rising_queries", "query", 7)):
        daily_map = {}
        for r in out[sec]:
            daily, top = _daily(svc, key, r[key], win)
            daily_map[r[key]] = daily
            r["page_for_query"] = top if key == "query" else r["page"]
            slugs.append(slug_from_page(r["page_for_query"] or ""))
        out[sec], spk = split_spikes(out[sec], key, daily_map)
        out["spikes"] += [{**x, "section": sec} for x in spk]
    tr = _treatments(slugs)
    for sec in ("ctr_opportunities", "page2_candidates", "rising_queries", "spikes"):
        for r in out[sec]:
            r["treatment"] = tr.get(slug_from_page(r.get("page_for_query") or ""))
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
        L.append(f"  imp{r['imp']:5.0f} ctr{r['ctr']:4.1f}% pos{r['pos']:4.1f}  {r['query']} "
                 f"{treatment_label(r.get('treatment'))}".rstrip())
    if not o["ctr_opportunities"]:
        L.append("  (該当なし)")
    L.append("\n─── 1ページ目押し上げ候補 (pos11-20 × imp≥300) ───")
    for r in o["page2_candidates"] or []:
        L.append(f"  imp{r['imp']:5.0f} clk{r['clicks']:3.0f} pos{r['pos']:4.1f}  {r['page'][:55]} "
                 f"{treatment_label(r.get('treatment'))}".rstrip())
    if not o["page2_candidates"]:
        L.append("  (該当なし)")
    L.append("\n─── 急上昇クエリ (7d imp≥100, 前週比1.5倍+) ───")
    for r in o["rising_queries"] or []:
        L.append(f"  imp{r['imp']:5.0f}(+{r['delta']:.0f}) clk{r['clicks']:3.0f} pos{r['pos']:4.1f}  {r['query']} "
                 f"{treatment_label(r.get('treatment'))}".rstrip())
    if not o["rising_queries"]:
        L.append("  (該当なし)")
    if o.get("spikes"):
        L.append(f"\n─── 除外(単日スパイク: 最大単日imp/合計 > {SPIKE_SHARE:.0%}) — 追う価値なし ───")
        for r in o["spikes"]:
            L.append(f"  imp{r['imp']:5.0f} 単日{r['spike_share']:.0%}  {r.get('query') or r.get('page')}")
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
