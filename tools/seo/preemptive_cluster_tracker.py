#!/usr/bin/env python3
"""先回りクラスタ記事の効果測定を自動化する (2026-08-12 新設)。

背景: 先回り記事は「公開/配信の当日に検索需要がゼロから立ち上がる」ことを
第1弾『恋は飴模様』で実証した(前日11→当日108セッション、初日で5-6位)。
この再現性を人手で追っていると判定日を逃すため、週次で自動集計する。

各記事の GSC 実績(clicks/impressions/position)を対象日の前後で比較し、
- 対象日を過ぎた記事: 立ち上がったか(before→after)
- 対象日が近い記事 : 事前にインデックスされているか(imp>0)
を判定して JSON + 標準出力に落とす。閾値割れは Discord 通知。

対象記事は config/preemptive_clusters.json で管理する(slug と対象日)。
"""
import json
import subprocess
import sys
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

BASE = Path("/home/aiuser/kpop-ai-system")
sys.path.insert(0, str(BASE))
CONFIG = BASE / "config" / "preemptive_clusters.json"
OUT = BASE / "logs" / "preemptive_cluster_report.jsonl"
SITE = "https://www.kpopjournal.tokyo/"
SA = BASE / "google_metrics" / "service_account.json"

# 「立ち上がった」と見なす最低クリック数(28日)。第1弾は初週で100超だった。
SUCCESS_CLICKS = 20
# 対象日前に「インデックスが温まっている」と見なす最低表示回数
WARM_IMPRESSIONS = 10


def _svc():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    creds = service_account.Credentials.from_service_account_file(
        str(SA), scopes=["https://www.googleapis.com/auth/webmasters.readonly"])
    return build("searchconsole", "v1", credentials=creds, cache_discovery=False)


def _query(svc, slug, start, end):
    """slug のページ実績を返す。アンカー行(#kpop-h-N)は計測アーティファクトなので除外。"""
    r = svc.searchanalytics().query(siteUrl=SITE, body={
        "startDate": start, "endDate": end, "dimensions": ["page"],
        "dimensionFilterGroups": [{"filters": [
            {"dimension": "page", "operator": "contains", "expression": slug}]}],
        "rowLimit": 20,
    }).execute()
    clicks = imp = 0
    pos = []
    for row in r.get("rows", []):
        if "#" in row["keys"][0]:
            continue
        clicks += row["clicks"]
        imp += row["impressions"]
        pos.append(row["position"])
    return {"clicks": clicks, "impressions": imp,
            "position": round(min(pos), 1) if pos else None}


def _notify(msg):
    try:
        from lib.resolve_discord_webhook import resolve
        url = resolve("alert_summary")
        if not url:
            return
        req = urllib.request.Request(
            url, data=json.dumps({"content": msg[:1900]}).encode(),
            headers={"Content-Type": "application/json",
                     "User-Agent": "KpopJournal-Bot/2.0 (preemptive-tracker)"})
        urllib.request.urlopen(req, timeout=15)
    except Exception as e:
        print(f"discord notify failed: {e}", file=sys.stderr)


def main():
    if not CONFIG.exists():
        print(f"config なし: {CONFIG}")
        return 1
    items = json.loads(CONFIG.read_text(encoding="utf-8")).get("clusters", [])
    if not items:
        print("追跡対象なし")
        return 0

    svc = _svc()
    today = date.today()
    # GSC は約3日遅延するため、確定している範囲だけ見る
    end = today - timedelta(days=3)
    report, alerts = [], []

    for it in items:
        slug, target = it["slug"], date.fromisoformat(it["target_date"])
        rec = {"slug": slug, "target_date": it["target_date"],
               "title": it.get("title", slug)}
        if target <= end:
            # 対象日以降28日 vs 対象日前28日
            after = _query(svc, slug, target.isoformat(),
                           min(end, target + timedelta(days=28)).isoformat())
            before = _query(svc, slug, (target - timedelta(days=28)).isoformat(),
                            (target - timedelta(days=1)).isoformat())
            rec.update({"phase": "after", "before": before, "after": after,
                        "success": after["clicks"] >= SUCCESS_CLICKS})
            if not rec["success"]:
                alerts.append(
                    f"⚠️ {rec['title']}: 対象日({it['target_date']})後の clicks "
                    f"{after['clicks']} が閾値{SUCCESS_CLICKS}未満。型の再現性を要検証")
        else:
            # 対象日前: インデックスが温まっているか
            warm = _query(svc, slug, (end - timedelta(days=28)).isoformat(),
                          end.isoformat())
            rec.update({"phase": "before", "warm": warm,
                        "days_left": (target - today).days,
                        "indexed": warm["impressions"] >= WARM_IMPRESSIONS})
            if rec["days_left"] <= 7 and not rec["indexed"]:
                alerts.append(
                    f"⚠️ {rec['title']}: 対象日まで{rec['days_left']}日だが imp "
                    f"{warm['impressions']}。インデックス未達の可能性")
        report.append(rec)

    stamp = datetime.now().isoformat()
    with OUT.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": stamp, "report": report}, ensure_ascii=False) + "\n")

    print(f"=== 先回りクラスタ効果測定 {stamp[:16]} ===")
    for r in report:
        if r["phase"] == "after":
            b, a = r["before"], r["after"]
            mark = "✅" if r["success"] else "❌"
            print(f"{mark} {r['title'][:34]:36} 前{b['clicks']:>4}clk → 後{a['clicks']:>4}clk "
                  f"(imp {b['impressions']}→{a['impressions']}, pos {a['position']})")
        else:
            mark = "🌱" if r["indexed"] else "⏳"
            w = r["warm"]
            print(f"{mark} {r['title'][:34]:36} 対象日まで{r['days_left']:>3}日 "
                  f"imp{w['impressions']:>5} pos{w['position']}")

    if alerts:
        _notify("📊 **先回りクラスタ 週次レポート**\n" + "\n".join(alerts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
