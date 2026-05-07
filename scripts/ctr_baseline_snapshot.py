#!/usr/bin/env python3
"""
ctr_baseline_snapshot.py — CTR改善効果の測定用ベースライン保存 & 2週間後比較

Usage:
  python3 scripts/ctr_baseline_snapshot.py --save       # ベースライン保存 (今日実行)
  python3 scripts/ctr_baseline_snapshot.py --compare    # 2週間後に比較実行

保存先: data/ctr_baseline_20260501.json
比較結果: logs/ctr_comparison_report.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"
LOGS = BASE / "logs"
GSC_LATEST = LOGS / "gsc_metrics_latest.json"
CTR_TARGETS = DATA / "low_ctr_targets.json"
JST = timezone(timedelta(hours=9))


def load_gsc_data() -> dict:
    if not GSC_LATEST.exists():
        print(f"[ERROR] GSCデータが見つかりません: {GSC_LATEST}", file=sys.stderr)
        sys.exit(1)
    return json.loads(GSC_LATEST.read_text())


def load_targets() -> list[str]:
    if not CTR_TARGETS.exists():
        return []
    targets = json.loads(CTR_TARGETS.read_text())
    return [t.get("slug", "") for t in targets if t.get("slug")]


def save_baseline():
    """現在のGSCデータからベースラインを保存"""
    gsc = load_gsc_data()
    target_slugs = load_targets()

    pages = gsc.get("pages", gsc.get("rows", []))
    baseline = {
        "snapshot_date": datetime.now(JST).strftime("%Y-%m-%d"),
        "gsc_date_range": gsc.get("date_range", {}),
        "total_pages": len(pages),
        "target_slugs": target_slugs,
        "site_avg": {
            "impressions": sum(p.get("impressions", 0) for p in pages),
            "clicks": sum(p.get("clicks", 0) for p in pages),
            "ctr": 0.0,
        },
        "target_pages": [],
        "all_pages": [],
    }

    total_imp = baseline["site_avg"]["impressions"]
    total_clk = baseline["site_avg"]["clicks"]
    baseline["site_avg"]["ctr"] = round(total_clk / total_imp * 100, 2) if total_imp else 0

    for p in pages:
        url = p.get("url", "")
        slug = url.rstrip("/").split("/")[-1] if url else ""
        entry = {
            "url": url,
            "slug": slug,
            "impressions": p.get("impressions", 0),
            "clicks": p.get("clicks", 0),
            "ctr": round(p.get("ctr", 0) * 100 if p.get("ctr", 0) < 1 else p.get("ctr", 0), 2),
            "position": round(p.get("position", 0), 1),
        }
        baseline["all_pages"].append(entry)
        if slug in target_slugs:
            baseline["target_pages"].append(entry)

    out = DATA / f"ctr_baseline_{baseline['snapshot_date'].replace('-', '')}.json"
    with open(out, "w") as f:
        json.dump(baseline, f, ensure_ascii=False, indent=2)

    print(f"Baseline saved: {out}")
    print(f"  Total pages: {baseline['total_pages']}")
    print(f"  Site avg CTR: {baseline['site_avg']['ctr']}%")
    print(f"  Target pages matched: {len(baseline['target_pages'])}")
    return out


def compare(baseline_path: str | None = None):
    """ベースラインと現在のGSCデータを比較"""
    # ベースラインファイルを探す
    if baseline_path:
        bp = Path(baseline_path)
    else:
        candidates = sorted(DATA.glob("ctr_baseline_*.json"))
        if not candidates:
            print("[ERROR] ベースラインが見つかりません。先に --save を実行してください", file=sys.stderr)
            sys.exit(1)
        bp = candidates[-1]

    baseline = json.loads(bp.read_text())
    current_gsc = load_gsc_data()

    current_pages = current_gsc.get("pages", current_gsc.get("rows", []))

    # URL→データのマップ
    current_map = {}
    for p in current_pages:
        url = p.get("url", "")
        current_map[url] = p

    # サイト全体
    cur_imp = sum(p.get("impressions", 0) for p in current_pages)
    cur_clk = sum(p.get("clicks", 0) for p in current_pages)
    cur_ctr = round(cur_clk / cur_imp * 100, 2) if cur_imp else 0

    report = {
        "comparison_date": datetime.now(JST).strftime("%Y-%m-%d"),
        "baseline_date": baseline.get("snapshot_date"),
        "baseline_gsc_range": baseline.get("gsc_date_range"),
        "current_gsc_range": current_gsc.get("date_range"),
        "site_overall": {
            "before": baseline["site_avg"],
            "after": {"impressions": cur_imp, "clicks": cur_clk, "ctr": cur_ctr},
            "ctr_change": round(cur_ctr - baseline["site_avg"]["ctr"], 2),
            "ctr_change_pct": round(
                (cur_ctr - baseline["site_avg"]["ctr"]) / baseline["site_avg"]["ctr"] * 100, 1
            ) if baseline["site_avg"]["ctr"] else 0,
        },
        "target_pages_comparison": [],
        "improved": 0,
        "degraded": 0,
        "unchanged": 0,
    }

    for bp_page in baseline.get("target_pages", []):
        url = bp_page["url"]
        cur = current_map.get(url)
        if not cur:
            continue
        cur_ctr_val = round(cur.get("ctr", 0) * 100 if cur.get("ctr", 0) < 1 else cur.get("ctr", 0), 2)
        delta = round(cur_ctr_val - bp_page["ctr"], 2)
        entry = {
            "url": url,
            "before_ctr": bp_page["ctr"],
            "after_ctr": cur_ctr_val,
            "delta": delta,
            "before_position": bp_page["position"],
            "after_position": round(cur.get("position", 0), 1),
        }
        report["target_pages_comparison"].append(entry)
        if delta > 0.5:
            report["improved"] += 1
        elif delta < -0.5:
            report["degraded"] += 1
        else:
            report["unchanged"] += 1

    out = LOGS / "ctr_comparison_report.json"
    with open(out, "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\n=== CTR Comparison Report ===")
    print(f"Baseline: {report['baseline_date']} → Current: {report['comparison_date']}")
    print(f"Site CTR: {report['site_overall']['before']['ctr']}% → {report['site_overall']['after']['ctr']}% ({report['site_overall']['ctr_change']:+.2f}pp)")
    print(f"Target pages: {len(report['target_pages_comparison'])} compared")
    print(f"  Improved: {report['improved']}")
    print(f"  Degraded: {report['degraded']}")
    print(f"  Unchanged: {report['unchanged']}")
    print(f"\nFull report: {out}")

    # Discord通知
    try:
        import os, urllib.request
        webhook = os.getenv("DISCORD_WEBHOOK_URL", "")
        if webhook:
            msg = (
                f"📊 CTR改善効果レポート\n"
                f"期間: {report['baseline_date']} → {report['comparison_date']}\n"
                f"サイトCTR: {report['site_overall']['before']['ctr']}% → {report['site_overall']['after']['ctr']}% ({report['site_overall']['ctr_change']:+.2f}pp)\n"
                f"改善: {report['improved']}件 / 悪化: {report['degraded']}件 / 維持: {report['unchanged']}件"
            )
            data = json.dumps({"content": msg}).encode()
            req = urllib.request.Request(webhook, data=data, headers={"Content-Type": "application/json"}, method="POST")
            urllib.request.urlopen(req, timeout=10)
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(description="CTR baseline & comparison")
    parser.add_argument("--save", action="store_true", help="Save baseline snapshot")
    parser.add_argument("--compare", action="store_true", help="Compare with baseline")
    parser.add_argument("--baseline", type=str, help="Baseline file path for comparison")
    args = parser.parse_args()

    if args.save:
        save_baseline()
    elif args.compare:
        compare(args.baseline)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
