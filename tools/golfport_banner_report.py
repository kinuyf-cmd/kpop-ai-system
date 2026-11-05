#!/usr/bin/env python3
"""GOLF PORT 自社バナー(3枠)の効果測定レポート。

データ源ごとに「何が取れて何が取れないか」を分けて出す(混ぜない):
  [A] K-POP JOURNAL の GA4        … バナー表示/クリック(house_banner_view/click)。pagePath で設置場所を判定。
  [B] GA4 の広告プロキシ          … ad_impression / ad_click。AdSense の収益ではない。
  [C] A8                          … API なし。収益・クリックは A8 管理画面のみ(未計測)。affiliate_click はサイト全体の参考値。
  [D] AdSense 収益                … トークンが生きているときだけ(0バイトなら未計測)。
  [E] GOLF PORT の DB dump        … 登録時の流入記録(AttributionSnapshot)+初回記録。訪問数は取れない。

使い方:
  venv_kpi/bin/python tools/golfport_banner_report.py --start 2026-11-06 --end 2026-11-12 [--baseline-days 7] [--out FILE]

読み取り専用。本番・GOLF PORT・GA4 設定は一切変更しない。GOLF PORT の個人情報(メール等)は読まず、集計値だけ出す。
GA4 は確定に24〜48h かかる(直近2日は途中値)。GOLF PORT dump は毎日03:00 JST の保存で最大約24h遅れる。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

PUBLISH_DATE = date(2026, 11, 5)  # 3枠とも2026-11-05(18:11〜18:23 JST)に公開
RO = ["sudo", "-n", "/usr/local/sbin/kpop/kpop-wp-ro"]
DUMP_DIR = Path("/home/aiuser/golfport-backups")
PLACEMENTS = ("top_sidebar", "article_footer", "event_page")


# ───────────── 共通 ─────────────
def wp(*args: str) -> str:
    r = subprocess.run(RO + list(args), capture_output=True, text=True, timeout=60)
    return r.stdout.strip()


def pct(n: float, d: float) -> str:
    return f"{n / d * 100:.2f}%" if d else "n/a"


def banner_option() -> dict:
    try:
        return json.loads(wp("option", "get", "kpop_golfport_banner", "--format=json"))
    except Exception:
        return {}


def placement_paths(opt: dict) -> dict[str, str]:
    """pagePath → 設置場所。トップ='/'、イベント=許可リストIDの slug、kdrama=カテゴリ内の slug。"""
    m: dict[str, str] = {"/": "top_sidebar"}
    for pid in opt.get("event_page_ids", []):
        slug = wp("post", "get", str(pid), "--field=post_name")
        if slug:
            m[f"/{slug}/"] = "event_page"
    for cat in opt.get("categories", []):
        out = wp("post", "list", "--post_type=post", "--post_status=publish", f"--category_name={cat}",
                 "--field=post_name", "--posts_per_page=500")
        for slug in out.splitlines():
            if slug.strip():
                m.setdefault(f"/{slug.strip()}/", "article_footer")  # イベントが優先(setdefault)
    return m


# ───────────── [A][B][C] GA4 ─────────────
def ga4(dims, metrics, start, end, event_filter=None):
    from google.analytics.data_v1beta import BetaAnalyticsDataClient
    from google.analytics.data_v1beta.types import (DateRange, Dimension, Filter, FilterExpression,
                                                    FilterExpressionList, Metric, RunReportRequest)
    from google.oauth2 import service_account
    from lib.data_collector import GA4_PROPERTY_ID, SERVICE_ACCOUNT_FILE
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=["https://www.googleapis.com/auth/analytics.readonly"])
    client = BetaAnalyticsDataClient(credentials=creds)
    flt = None
    if event_filter:
        flt = FilterExpression(or_group=FilterExpressionList(expressions=[
            FilterExpression(filter=Filter(field_name="eventName",
                                           string_filter=Filter.StringFilter(value=e)))
            for e in event_filter]))
    req = RunReportRequest(
        property=f"properties/{GA4_PROPERTY_ID}",
        date_ranges=[DateRange(start_date=start.isoformat(), end_date=end.isoformat())],
        dimensions=[Dimension(name=d) for d in dims], metrics=[Metric(name=m) for m in metrics],
        dimension_filter=flt, limit=100000)
    out = []
    for row in client.run_report(req).rows:
        d = {dims[i]: row.dimension_values[i].value for i in range(len(dims))}
        for i, m in enumerate(metrics):
            d[m] = int(float(row.metric_values[i].value))
        out.append(d)
    return out


def section_banner_events(pmap, start, end):
    rows = ga4(["pagePath", "deviceCategory", "eventName"], ["eventCount"], start, end,
               ["house_banner_view", "house_banner_click"])
    agg = defaultdict(lambda: Counter())
    dev = defaultdict(lambda: Counter())
    unknown = Counter()
    for r in rows:
        pl = pmap.get(r["pagePath"])
        if not pl:
            unknown[r["pagePath"]] += r["eventCount"]
            continue
        agg[pl][r["eventName"]] += r["eventCount"]
        dev[(pl, r["deviceCategory"])][r["eventName"]] += r["eventCount"]
    lines = ["### [A] バナー表示・クリック(GA4 / K-POP JOURNAL)",
             "| 設置場所 | 表示(view) | クリック | CTR |", "|---|---:|---:|---:|"]
    tv = tc = 0
    for pl in PLACEMENTS:
        v, c = agg[pl]["house_banner_view"], agg[pl]["house_banner_click"]
        tv, tc = tv + v, tc + c
        lines.append(f"| {pl} | {v} | {c} | {pct(c, v)} |")
    lines.append(f"| **合計** | {tv} | {tc} | {pct(tc, tv)} |")
    lines += ["", "デバイス別:", "| 設置場所 | デバイス | view | click | CTR |", "|---|---|---:|---:|---:|"]
    for (pl, dv), c in sorted(dev.items()):
        lines.append(f"| {pl} | {dv} | {c['house_banner_view']} | {c['house_banner_click']} | "
                     f"{pct(c['house_banner_click'], c['house_banner_view'])} |")
    if unknown:
        lines.append(f"\n※ 設置場所を判定できなかったpagePath(許可リスト外/URL変更の可能性): {dict(unknown.most_common(5))}")
    lines.append("\n※ view=バナーが50%見えた回数(1ページ1回)。ページPVとは別物。placement は pagePath から判定"
                 "(banner_content はGA4カスタムディメンション未登録のため直接は集計できない)。")
    return lines, {pl: (agg[pl]["house_banner_view"], agg[pl]["house_banner_click"]) for pl in PLACEMENTS}


def section_pv_and_ads(pmap, w_before, w_after):
    """設置対象ページ群のPV・広告イベントを 掲載前/後 で比較(日平均)。"""
    def collect(win):
        s, e = win
        pv = ga4(["pagePath"], ["screenPageViews"], s, e)
        ev = ga4(["pagePath", "eventName"], ["eventCount"], s, e, ["ad_impression", "ad_click"])
        g = defaultdict(Counter)
        for r in pv:
            if r["pagePath"] in pmap:
                g[pmap[r["pagePath"]]]["pv"] += r["screenPageViews"]
        for r in ev:
            if r["pagePath"] in pmap:
                g[pmap[r["pagePath"]]][r["eventName"]] += r["eventCount"]
        return g, (e - s).days + 1
    (gb, nb), (ga, na) = collect(w_before), collect(w_after)
    lines = ["### [B] 対象ページのPVと広告イベント(GA4のプロキシ。**AdSense収益ではない**)",
             f"掲載前 {w_before[0]}〜{w_before[1]}({nb}日) → 掲載後 {w_after[0]}〜{w_after[1]}({na}日)。日平均で比較。",
             "| 設置場所 | PV/日(前→後) | ad_impression/PV(前→後) | ad_click/日(前→後) |", "|---|---|---|---|"]
    for pl in PLACEMENTS:
        b, a = gb[pl], ga[pl]
        lines.append(
            f"| {pl} | {b['pv']/nb:.1f} → {a['pv']/na:.1f} | "
            f"{(b['ad_impression']/b['pv'] if b['pv'] else 0):.2f} → {(a['ad_impression']/a['pv'] if a['pv'] else 0):.2f} | "
            f"{b['ad_click']/nb:.2f} → {a['ad_click']/na:.2f} |")
    lines.append("\n※ 対象ページ数が少なく日次変動が大きい。前後差は因果の証明にならない(曜日・ニュース・季節要因)。")
    return lines


def section_a8_adsense(w_before, w_after):
    lines = ["### [C] A8 / [D] AdSense 収益"]
    tok = BASE / "google_metrics" / "adsense_token.json"
    size = tok.stat().st_size if tok.exists() else None
    if not size:
        lines.append(f"- **AdSense収益: 未計測**。google_metrics/adsense_token.json が{'存在しない' if size is None else '0バイト'}"
                     "(再認証はownerのOAuth操作が必要)。上の[B]の広告イベントはGA4由来のプロキシ。")
    else:
        lines.append("- AdSenseトークンは存在するが、このレポートでは収益APIを呼んでいない(未実装)。収益は未計測として扱う。")
    try:
        aff = {}
        for tag, (s, e) in (("前", w_before), ("後", w_after)):
            rows = ga4(["eventName"], ["eventCount"], s, e, ["affiliate_click"])
            n = (e - s).days + 1
            aff[tag] = (sum(r["eventCount"] for r in rows), n)
        lines.append(f"- **A8収益/クリック(PORT含む): 未計測**。A8管理画面でのみ確認可。参考: サイト全体のGA4 affiliate_click "
                     f"前 {aff['前'][0]}件/{aff['前'][1]}日 → 後 {aff['後'][0]}件/{aff['後'][1]}日"
                     "(A8以外のASPも含み、link_urlがカスタムディメンション未登録のためPORT単体は分離不可)。")
    except Exception as ex:  # noqa: BLE001
        lines.append(f"- A8: 未計測(affiliate_click取得失敗: {type(ex).__name__})")
    return lines


# ───────────── [E] GOLF PORT dump ─────────────
def _unescape(v: str):
    if v == r"\N":
        return None
    return (v.replace(r"\t", "\t").replace(r"\n", "\n").replace(r"\r", "\r").replace("\\\\", "\\"))


def read_table(dump: Path, table: str) -> list[dict]:
    p = subprocess.run(["pg_restore", "-a", "-t", table, "-f", "-", str(dump)],
                       capture_output=True, text=True, timeout=300)
    cols, rows, inside = [], [], False
    for ln in p.stdout.splitlines():
        if ln.startswith("COPY "):
            head = ln[ln.index("(") + 1: ln.rindex(")")]
            cols = [c.strip().strip('"') for c in head.split(",")]
            inside = True
            continue
        if inside:
            if ln == r"\.":
                break
            parts = ln.split("\t")
            rows.append({cols[i]: _unescape(parts[i]) for i in range(min(len(cols), len(parts)))})
    return rows


def parse_ts(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.split("+")[0].strip())
    except ValueError:
        return None


def section_golfport(start, end):
    dumps = sorted(DUMP_DIR.glob("golfport-*.dump"))
    lines = ["### [E] GOLF PORT 側(DB dump。**訪問数・セッションは取れない**)"]
    if not dumps:
        return lines + ["- dumpが見つからない → 未計測"]
    dump = dumps[-1]
    lines.append(f"- 使用dump: {dump.name}(毎日03:00 JST保存。それ以降の登録は含まない)")
    att = read_table(dump, "AttributionSnapshot")
    users = {u["id"]: u for u in read_table(dump, "User")}
    s_dt, e_dt = datetime.combine(start, datetime.min.time()), datetime.combine(end + timedelta(days=1), datetime.min.time())

    def in_win(r):
        t = parse_ts(r.get("capturedAt"))
        return t is not None and s_dt <= t < e_dt

    win = [r for r in att if in_win(r)]
    signups = [r for r in win if r["kind"] == "SIGNUP"]
    consent_yes = sum(1 for r in signups if r["analyticsConsent"] == "t")
    kp = [r for r in win if "kpopjournal" in ((r.get("firstUtmSource") or ""), (r.get("lastUtmSource") or ""))]
    lines += [f"- 期間内の登録(SIGNUP)記録: {len(signups)}件。うち解析Cookie許可: {consent_yes}件({pct(consent_yes, len(signups))})。"
              "**不許可の登録はUTMが記録されないため、バナー経由の登録は実際より少なく出る。**",
              f"- kpopjournal経由の記録(first/lastのどちらか): {len(kp)}件"]
    byk = Counter((r["kind"], (r.get("firstUtmContent") or r.get("lastUtmContent") or "-")) for r in kp)
    if byk:
        lines += ["", "| 種別 | utm_content | 件数 |", "|---|---|---:|"]
        lines += [f"| {k} | {c} | {n} |" for (k, c), n in sorted(byk.items())]
    # 初回記録(登録ユーザーが登録後に記録したか)
    kp_users = {r["refId"] for r in kp if r["kind"] == "SIGNUP"}
    rec = {"ラウンド記録": ("RoundLog", "studentId", "createdAt"),
           "練習記録": ("PracticeLog", "studentId", "createdAt"),
           "思い出(単体)": ("StandaloneMemory", "studentId", "createdAt")}
    lines += ["", f"- kpopjournal経由の新規登録ユーザー: {len(kp_users)}人 → 登録後の初回記録(人数・集計のみ):"]
    for label, (tbl, ucol, tcol) in rec.items():
        owners = set()
        for r in read_table(dump, tbl):
            u = users.get(r.get(ucol) or "")
            if r.get(ucol) in kp_users and u:
                tc, tu = parse_ts(r.get(tcol)), parse_ts(u.get("createdAt"))
                if tc and tu and tc >= tu:
                    owners.add(r[ucol])
        lines.append(f"  - {label}: {len(owners)}人")
    lines.append("\n※ 記録の種別は一部(ラウンド/練習/単体メモリー)。ラウンド/練習に紐づく写真メモリー等は含まない。"
                 "GOLF PORTのGA4(訪問・セッション・参照元/メディア)は別プロパティで、このサーバーからは未接続 → GOLF PORT側から提供が必要。")
    return lines


# ───────────── main ─────────────
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", required=True, help="YYYY-MM-DD(掲載後の開始。公開は2026-11-05 18時台なので通常11-06)")
    ap.add_argument("--end", default=date.today().isoformat())
    ap.add_argument("--baseline-days", type=int, default=7)
    ap.add_argument("--out")
    a = ap.parse_args()
    start, end = date.fromisoformat(a.start), date.fromisoformat(a.end)
    w_after = (start, end)
    w_before = (PUBLISH_DATE - timedelta(days=a.baseline_days), PUBLISH_DATE - timedelta(days=1))

    opt = banner_option()
    pmap = placement_paths(opt)
    out = [f"# GOLF PORT バナー 計測レポート {start}〜{end}",
           f"生成: {datetime.now():%F %T}  /  現在のoption: `{json.dumps(opt, ensure_ascii=False)}`",
           f"対象ページ数: " + ", ".join(f"{pl}={sum(1 for v in pmap.values() if v == pl)}" for pl in PLACEMENTS),
           "", "> **最重要**: 表示数・CTRではなく、GOLF PORTでの実利用(登録→初回記録)につながったかで評価する。"
           "GA4/A8/AdSense/GOLF PORTは計測条件が異なり、数値は一致しない。", ""]
    for fn in (lambda: section_banner_events(pmap, start, end)[0],
               lambda: section_pv_and_ads(pmap, w_before, w_after),
               lambda: section_a8_adsense(w_before, w_after),
               lambda: section_golfport(start, end)):
        try:
            out += fn() + [""]
        except Exception as ex:  # noqa: BLE001 — 1セクションの失敗で全体を止めない
            out += [f"(セクション失敗: {type(ex).__name__}: {str(ex)[:200]} → 該当データは未計測)", ""]
    text = "\n".join(out)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
