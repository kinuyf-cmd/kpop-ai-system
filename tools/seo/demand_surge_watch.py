#!/usr/bin/env python3
"""demand_surge_watch.py — 需要が「今」立ち上がったクエリを検知する(2026-09-10)

seo_opportunity_scanner.py(90日窓・週次)との役割分担:
  scanner        = 蓄積した imp の中から「取りこぼし」を探す。既に需要がある前提。
  demand_surge   = 7日窓で「前週ほぼゼロ → 今週急増」を捉える。需要の立ち上がり検知。

なぜ必要か(2026-09-10 実測):
  CORTIS は 9/7 に `cortis メンバー` の imp が 53→795 と15倍に急増したが、
  90日窓では埋もれて scanner に出ず、手動で GSC を叩いて3日遅れで気づいた。
  新人グループは競合が弱く、立ち上がりに先回りできれば1ページ目を取れる。
  実際 /artists/cortis/ は pos11.1 まで来ており、有名グループ(newjeans pos68 /
  aespa pos52)とは対照的([[idol-wiki-wins-only-for-rookies]])。

判定:
  imp >= MIN_IMP かつ 前週比 >= SURGE_RATIO 倍(前週0でも可) かつ
  意図不一致でない(= 上位なのにクリックが出ない幻を除外)
  → 「今すぐ着手すべき需要」として Discord 通知 + JSON 出力

使い方:
  venv_kpi/bin/python3 tools/seo/demand_surge_watch.py            # 検知して通知
  venv_kpi/bin/python3 tools/seo/demand_surge_watch.py --dry-run  # 通知せず表示のみ
"""
import argparse
import json
import os
import subprocess
import sys
import urllib.request
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from google.oauth2 import service_account
from googleapiclient.discovery import build

from lib.seo_opportunity_scanner import is_excluded, is_intent_mismatch

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SA_FILE = os.path.join(BASE, "google_metrics", "service_account.json")
SITE = os.environ.get("GSC_SITE_URL", "https://www.kpopjournal.tokyo/")
OUT_FILE = os.path.join(BASE, "data", "demand_surge.json")
STATE_FILE = os.path.join(BASE, "data", "demand_surge_seen.json")

# --- 判定パラメータ ---
MIN_IMP = 80          # 今週これ未満は様子見(CORTIS 検知時は 864)
SURGE_RATIO = 3.0     # 前週比の倍率。前週0なら MIN_IMP 超えで即該当
NOTIFY_TOP = 10       # 通知に載せる最大件数
SEEN_KEEP_DAYS = 21   # 一度通知したクエリを再通知しない期間

# 本ツール固有の追加除外。scanner の辞書(BRAND/GOSSIP/BREAKING)を汚さず、
# 「立ち上がりを追う」文脈でだけ不要なものをここで弾く。
#  - 相関図: SERP画像パックで用が済むゼロクリック検索。順位を取っても
#    クリックにならない([[correlation-chart-queries-are-zero-click]])。
#    実測で `恋 は 飴 も よう 相関 図` が pos1.5/CTR1.2% で intent_mismatch を
#    すり抜けたため、語そのもので除外する。
#  - 身体部位: 整形疑惑など GOSSIP_TERMS が拾いきれない外見詮索クエリ
#    (実測: `ジヒョ 鼻` が通過していた)。
EXTRA_EXCLUDE = ["相関図", "相関 図"]
BODY_PART_TERMS = ["鼻", "目 整形", "顔 変わ", "太った", "痩せた", "脚", "腹筋"]


def _extra_excluded(q):
    if any(t in q for t in EXTRA_EXCLUDE):
        return True
    return any(t in q for t in BODY_PART_TERMS)


# GSC は確定に2-3日かかる([[ga4-must-wait-for-data-finalization]] と同様の遅延)。
# 未確定日を掴むと「急増」を取り逃すため 3日前を終端にする。
LAG_DAYS = 3


def _svc():
    creds = service_account.Credentials.from_service_account_file(
        SA_FILE, scopes=["https://www.googleapis.com/auth/webmasters.readonly"])
    return build("searchconsole", "v1", credentials=creds, cache_discovery=False)


def _window(days, back=0):
    end = date.today() - timedelta(days=LAG_DAYS + back)
    start = end - timedelta(days=days - 1)
    return start.isoformat(), end.isoformat()


def _query(svc, days, back):
    s, e = _window(days, back)
    body = {"startDate": s, "endDate": e, "dimensions": ["query"],
            "type": "web", "rowLimit": 5000}
    rows = svc.searchanalytics().query(siteUrl=SITE, body=body).execute().get("rows", [])
    return {r["keys"][0]: r for r in rows}


def _load_seen():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}
    cutoff = (date.today() - timedelta(days=SEEN_KEEP_DAYS)).isoformat()
    return {q: d for q, d in data.items() if d >= cutoff}


def _save_seen(seen):
    # 台帳の書き込みは原子的に([[adsense-token-zero-byte-nonatomic-write]])。
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, STATE_FILE)


def detect():
    svc = _svc()
    cur = _query(svc, 7, 0)
    prev = _query(svc, 7, 7)
    out = []
    for q, r in cur.items():
        imp = r["impressions"]
        if imp < MIN_IMP or is_excluded(q) or _extra_excluded(q):
            continue
        if is_intent_mismatch(r["position"], r["ctr"], imp):
            continue  # 上位なのにクリックが出ない幻は追わない
        pi = prev[q]["impressions"] if q in prev else 0
        if pi > 0 and imp < pi * SURGE_RATIO:
            continue
        out.append({
            "query": q, "imp": imp, "prev_imp": pi, "delta": imp - pi,
            "clicks": r["clicks"], "ctr_pct": round(r["ctr"] * 100, 2),
            "position": round(r["position"], 1),
            "ratio": (round(imp / pi, 1) if pi else None),
        })
    out.sort(key=lambda x: -x["delta"])
    return out


def notify_discord(text):
    """alert_summary チャネルへ送信([[discord-notify-global-repair-20260602]] 準拠)。"""
    try:
        url = subprocess.run(
            [sys.executable, os.path.join(BASE, "lib/resolve_discord_webhook.py"), "alert_summary"],
            capture_output=True, text=True, timeout=15).stdout.strip()
        if not url.startswith("https://discord.com/api/webhooks/"):
            print("WARN: webhook解決失敗、通知スキップ", file=sys.stderr)
            return False
        body = json.dumps({"content": text[:1900]}).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers={
            "Content-Type": "application/json",
            "User-Agent": "kpop-demand-surge/1.0 (github.com/kpop-ai-system)"})
        urllib.request.urlopen(req, timeout=15)
        return True
    except Exception as e:
        print(f"WARN: Discord通知失敗: {e}", file=sys.stderr)
        return False


def main():
    ap = argparse.ArgumentParser(description="需要立ち上がり検知")
    ap.add_argument("--dry-run", action="store_true", help="通知せず表示のみ")
    ap.add_argument("--all", action="store_true", help="通知済みも再表示する")
    args = ap.parse_args()

    s, e = _window(7)
    rows = detect()
    print(f"═══ 需要立ち上がり検知 {s}..{e} (前週比{SURGE_RATIO}倍以上 / imp>={MIN_IMP}) ═══")

    seen = _load_seen()
    fresh = [r for r in rows if args.all or r["query"] not in seen]

    if not rows:
        print("  該当なし")
    for r in rows:
        mark = " " if r["query"] in seen else "★"
        ratio = f"{r['ratio']}倍" if r["ratio"] else "新規"
        print(f" {mark} imp{r['imp']:5.0f}(前週{r['prev_imp']:4.0f} {ratio:>6s}) "
              f"clk{r['clicks']:3.0f} ctr{r['ctr_pct']:5.2f}% pos{r['position']:5.1f}  {r['query']}")

    payload = {"window": [s, e], "generated_at": date.today().isoformat(), "rows": rows}
    tmp = OUT_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, OUT_FILE)

    if fresh and not args.dry_run:
        lines = ["**📈 需要が立ち上がっています(先回りの好機)**",
                 f"窓: {s}..{e} / 前週比{SURGE_RATIO}倍以上"]
        for r in fresh[:NOTIFY_TOP]:
            ratio = f"{r['ratio']}倍" if r["ratio"] else "新規"
            lines.append(f"・`{r['query']}` imp{r['imp']:.0f} (前週{r['prev_imp']:.0f} → {ratio}) "
                         f"pos{r['position']} ctr{r['ctr_pct']}%")
        lines.append("→ 競合が弱いうちに記事化/強化すると1ページ目を取りやすい")
        if notify_discord("\n".join(lines)):
            print(f"→ Discord通知送信 ({len(fresh)}件の新規検知)")
        today = date.today().isoformat()
        for r in fresh:
            seen[r["query"]] = today
        _save_seen(seen)
    elif fresh:
        print(f"(dry-run: {len(fresh)}件が新規検知。通知はしていません)")
    else:
        print("(新規の立ち上がりなし = 通知不要)")


if __name__ == "__main__":
    main()
