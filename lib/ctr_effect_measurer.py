#!/usr/bin/env python3
"""ctr_effect_measurer.py — CTRリライト前後の効果測定

使い方:
  # baseline作成（CTR更新直後、Google再計算前に実行）
  python3 lib/ctr_effect_measurer.py --snapshot baseline

  # 24-72h後に after スナップショットを作成し比較
  python3 lib/ctr_effect_measurer.py --snapshot after
  python3 lib/ctr_effect_measurer.py --compare

  # cron日次実行（scheduler経由）でbefore/afterを自動収集
  python3 lib/ctr_effect_measurer.py --auto

出力:
  logs/ctr_snapshots/baseline_YYYYMMDD.json
  logs/ctr_snapshots/after_YYYYMMDD.json
  logs/ctr_effect_report.json
"""
from __future__ import annotations
import argparse
import json
import subprocess
import sys
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"
SNAP_DIR = LOGS / "ctr_snapshots"
SNAP_DIR.mkdir(exist_ok=True)
GSC_LATEST = LOGS / "gsc_metrics_latest.json"
REWRITE_HISTORY = LOGS / "ctr_title_rewrite.jsonl"
REPORT = LOGS / "ctr_effect_report.json"
JST = timezone(timedelta(hours=9))


def ensure_fresh_gsc():
    """gsc_metrics_fetcher.py を実行してデータを更新"""
    print("[ctr_effect] GSC最新データ取得中...")
    r = subprocess.run(["python3", str(BASE / "lib" / "gsc_metrics_fetcher.py"),
                        "--days", "28"], capture_output=True, text=True, timeout=180)
    print(r.stdout[-200:] if r.stdout else r.stderr[-200:])


def load_gsc() -> dict[str, dict]:
    if not GSC_LATEST.exists():
        return {}
    d = json.loads(GSC_LATEST.read_text())
    return {p["url"]: p for p in d.get("pages", [])}


def load_rewrite_targets() -> list[dict]:
    """CTRリライトで更新されたURLのリスト"""
    if not REWRITE_HISTORY.exists():
        return []
    targets = []
    seen = set()
    for line in REWRITE_HISTORY.read_text(errors="replace").splitlines():
        try:
            d = json.loads(line)
            if d.get("updated") is True and d.get("url"):
                u = d["url"]
                if u in seen:
                    continue
                seen.add(u)
                targets.append(d)
        except Exception:
            continue
    return targets


def save_snapshot(kind: str) -> Path:
    today = date.today().strftime("%Y%m%d")
    ensure_fresh_gsc()
    gsc = load_gsc()
    targets = load_rewrite_targets()
    snap = {
        "kind": kind,
        "snapshot_at": datetime.now(tz=JST).isoformat(),
        "target_urls": [t["url"] for t in targets],
        "metrics": {t["url"]: gsc.get(t["url"], {}) for t in targets},
        "targets_count": len(targets),
        "metrics_count_found": sum(1 for t in targets if gsc.get(t["url"])),
    }
    path = SNAP_DIR / f"{kind}_{today}.json"
    path.write_text(json.dumps(snap, ensure_ascii=False, indent=2))
    print(f"[ctr_effect] {kind} スナップショット保存: {path}")
    print(f"  対象URL: {snap['targets_count']}件 / GSCで見つかった: {snap['metrics_count_found']}件")
    return path


def compare() -> dict:
    """最新の baseline_* と after_* を比較"""
    baselines = sorted(SNAP_DIR.glob("baseline_*.json"))
    afters = sorted(SNAP_DIR.glob("after_*.json"))
    if not baselines:
        return {"error": "baseline snapshot がありません"}
    if not afters:
        return {"error": "after snapshot がありません（24-72h後に取得）"}
    before = json.loads(baselines[-1].read_text())
    after = json.loads(afters[-1].read_text())

    rows = []
    for url in before["target_urls"]:
        b = before["metrics"].get(url, {})
        a = after["metrics"].get(url, {})
        b_ctr = b.get("ctr", 0) * 100
        a_ctr = a.get("ctr", 0) * 100
        b_imp = b.get("impressions", 0)
        a_imp = a.get("impressions", 0)
        b_clk = b.get("clicks", 0)
        a_clk = a.get("clicks", 0)
        improvement_pct = ((a_ctr - b_ctr) / b_ctr * 100) if b_ctr else 0
        rows.append({
            "url": url,
            "before": {"ctr_pct": round(b_ctr, 3), "impressions": b_imp, "clicks": b_clk},
            "after":  {"ctr_pct": round(a_ctr, 3), "impressions": a_imp, "clicks": a_clk},
            "delta":  {
                "ctr_pct":     round(a_ctr - b_ctr, 3),
                "impressions": a_imp - b_imp,
                "clicks":      a_clk - b_clk,
                "ctr_improvement_pct": round(improvement_pct, 2),
            },
        })

    valid_rows = [r for r in rows if r["before"]["impressions"] > 0 or r["after"]["impressions"] > 0]
    improved = [r for r in valid_rows if r["delta"]["ctr_pct"] > 0]
    worsened = [r for r in valid_rows if r["delta"]["ctr_pct"] < 0]
    unchanged = [r for r in valid_rows if r["delta"]["ctr_pct"] == 0]

    avg_before_ctr = (sum(r["before"]["ctr_pct"] for r in valid_rows) / len(valid_rows)) if valid_rows else 0
    avg_after_ctr = (sum(r["after"]["ctr_pct"] for r in valid_rows) / len(valid_rows)) if valid_rows else 0
    total_imp_before = sum(r["before"]["impressions"] for r in valid_rows)
    total_imp_after = sum(r["after"]["impressions"] for r in valid_rows)
    total_clk_before = sum(r["before"]["clicks"] for r in valid_rows)
    total_clk_after = sum(r["after"]["clicks"] for r in valid_rows)

    report = {
        "compared_at": datetime.now(tz=JST).isoformat(),
        "before_snapshot": baselines[-1].name,
        "after_snapshot":  afters[-1].name,
        "summary": {
            "urls_analyzed":  len(valid_rows),
            "improved":       len(improved),
            "worsened":       len(worsened),
            "unchanged":      len(unchanged),
            "avg_ctr_before_pct": round(avg_before_ctr, 3),
            "avg_ctr_after_pct":  round(avg_after_ctr, 3),
            "avg_ctr_improvement_pct": round(
                ((avg_after_ctr - avg_before_ctr) / avg_before_ctr * 100) if avg_before_ctr else 0, 2
            ),
            "total_impressions_before": total_imp_before,
            "total_impressions_after":  total_imp_after,
            "total_clicks_before":      total_clk_before,
            "total_clicks_after":       total_clk_after,
            "traffic_increase_pct":     round(
                ((total_clk_after - total_clk_before) / total_clk_before * 100) if total_clk_before else 0, 2
            ),
        },
        "top_improved": sorted(improved, key=lambda x: -x["delta"]["ctr_pct"])[:10],
        "top_worsened": sorted(worsened, key=lambda x: x["delta"]["ctr_pct"])[:5],
        "all_rows": rows,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", choices=["baseline", "after"])
    ap.add_argument("--compare", action="store_true")
    ap.add_argument("--auto", action="store_true",
                    help="baseline がなければ作成。あり かつ 24h経過なら after を作成し比較")
    args = ap.parse_args()

    if args.snapshot:
        save_snapshot(args.snapshot)
        return
    if args.compare:
        r = compare()
        if "error" in r:
            print(r["error"])
            return
        s = r["summary"]
        print(f"\n[ctr_effect] 効果測定レポート: {REPORT}")
        print(f"  比較対象: {s['urls_analyzed']}件 (改善={s['improved']} / 悪化={s['worsened']} / 変化なし={s['unchanged']})")
        print(f"  CTR平均: {s['avg_ctr_before_pct']}% → {s['avg_ctr_after_pct']}% ({s['avg_ctr_improvement_pct']}% 改善)")
        print(f"  表示: {s['total_impressions_before']} → {s['total_impressions_after']}")
        print(f"  クリック: {s['total_clicks_before']} → {s['total_clicks_after']} ({s['traffic_increase_pct']}% 増)")
        return
    if args.auto:
        today = date.today().strftime("%Y%m%d")
        has_baseline = any(SNAP_DIR.glob("baseline_*.json"))
        if not has_baseline:
            save_snapshot("baseline")
            return
        # Check if baseline is older than 24h
        baselines = sorted(SNAP_DIR.glob("baseline_*.json"))
        latest_bl_date = baselines[-1].stem.split("_", 1)[1]
        if (datetime.now() - datetime.strptime(latest_bl_date, "%Y%m%d")).days >= 1:
            # Enough time passed → after snapshot + compare
            save_snapshot("after")
            compare()
        else:
            print(f"[ctr_effect] baseline は {latest_bl_date} 作成、24h未満のため測定待機中")
        return

    ap.print_help()


if __name__ == "__main__":
    main()
