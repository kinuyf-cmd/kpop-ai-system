#!/usr/bin/env python3
"""kpi_recovery_builder.py — ダッシュボード用 KPI 復旧指標 JSON を生成

出力: dashboard_kpi_recovery.json （generate_dashboard.py が読み込む）

含まれるKPI:
  - インデックス数 (gsc_resubmit_log から24h以内の成功件数)
  - CTR (metrics_yesterday.json から平均CTR、あれば)
  - 流入 (metrics_yesterday.json から総impression/clicks)
  - CTA率 (cta_updates.jsonl から直近1週間の設置率)
  - 記事数 (WP API publish件数)
"""
from __future__ import annotations
import json
import re
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"
OUT = BASE / "dashboard_kpi_recovery.json"
WP = "https://www.kpopjournal.tokyo"
WP_AUTH = str(Path.home() / ".wp_auth")
JST = timezone(timedelta(hours=9))


def count_jsonl_recent(p: Path, hours: int) -> int:
    if not p.exists():
        return 0
    cutoff = datetime.now(tz=JST) - timedelta(hours=hours)
    n = 0
    for line in p.read_text(errors="replace").splitlines():
        try:
            r = json.loads(line)
            ts = r.get("ts") or r.get("timestamp")
            if not ts:
                continue
            t = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(JST)
            if t >= cutoff:
                n += 1
        except Exception:
            continue
    return n


def wp_post_count() -> int:
    try:
        out = subprocess.check_output(
            ["curl", "-sI", f"{WP}/wp-json/wp/v2/posts?per_page=1&status=publish",
             "-K", WP_AUTH], timeout=20).decode()
        m = re.search(r"X-WP-Total:\s*(\d+)", out, re.I)
        return int(m.group(1)) if m else 0
    except Exception:
        return 0


def main():
    now = datetime.now(tz=JST)
    # 1. GSC インデックス件数 (24h)
    gsc_24h = count_jsonl_recent(LOGS / "gsc_resubmit_log.jsonl", 24)
    gsc_total = 0
    if (LOGS / "gsc_resubmit_log.jsonl").exists():
        gsc_total = sum(1 for l in (LOGS / "gsc_resubmit_log.jsonl").read_text(errors="replace").splitlines() if l.strip())

    # 2. CTR / 流入 — gsc_metrics_latest.json (直近28日) を優先
    ctr_avg = None; total_imp = 0; total_click = 0
    gsc_latest = LOGS / "gsc_metrics_latest.json"
    if gsc_latest.exists():
        try:
            d = json.loads(gsc_latest.read_text())
            pages = d.get("pages", [])
            if pages:
                clicks = sum(int(p.get("clicks") or 0) for p in pages)
                impr = sum(int(p.get("impressions") or 0) for p in pages)
                total_click, total_imp = clicks, impr
                if impr > 0:
                    ctr_avg = round(clicks / impr * 100, 2)
        except Exception:
            pass
    # Fallback to metrics_yesterday.json (gsc.top_pages or rows)
    if total_imp == 0:
        my = BASE / "google_metrics" / "metrics_yesterday.json"
        if my.exists():
            try:
                d = json.loads(my.read_text())
                rows = d.get("gsc", {}).get("top_pages") if isinstance(d, dict) else None
                if not rows:
                    rows = d.get("rows", d) if isinstance(d, dict) else d
                if isinstance(rows, list) and rows:
                    clicks = sum(int(r.get("clicks") or 0) for r in rows if isinstance(r, dict))
                    impr = sum(int(r.get("impressions") or 0) for r in rows if isinstance(r, dict))
                    total_click, total_imp = clicks, impr
                    if impr > 0:
                        ctr_avg = round(clicks / impr * 100, 2)
            except Exception:
                pass

    # 3. CTA設置率 (直近7日に更新された記事のうち data-cta=top/mid/bottom すべてある率)
    cta_log = LOGS / "cta_updates.jsonl"
    cta_updated_7d = count_jsonl_recent(cta_log, 24 * 7)

    # 4. 記事数
    posts_publish = wp_post_count()

    # 4.5 GSC インデックス率 (gsc_index_summary.json)
    idx_rate = None; idx_counts = {}
    isum = LOGS / "gsc_index_summary.json"
    if isum.exists():
        try:
            s = json.loads(isum.read_text())
            idx_rate = s.get("indexed_rate_pct")
            idx_counts = s.get("counts", {})
        except Exception:
            pass

    # 5. 直近 X 投稿件数 (24h)
    x_log = LOGS / "x_post.log"
    x_24h = 0
    if x_log.exists():
        cutoff = now - timedelta(hours=24)
        for line in x_log.read_text(errors="replace").splitlines():
            m = re.search(r'"timestamp"\s*:\s*"([^"]+)"', line)
            if m:
                try:
                    t = datetime.fromisoformat(m.group(1).replace("Z", "+00:00")).astimezone(JST)
                    if t >= cutoff:
                        x_24h += 1
                except Exception:
                    pass

    # 6. 内部リンク追加件数 (7d)
    il_7d = count_jsonl_recent(LOGS / "internal_link_updates.jsonl", 24 * 7)

    kpi = {
        "generated_at": now.isoformat(),
        "kpis": {
            "gsc_indexed_24h":   gsc_24h,
            "gsc_indexed_total": gsc_total,
            "ctr_avg_pct":       ctr_avg,
            "impressions_total": total_imp,
            "clicks_total":      total_click,
            "cta_updated_7d":    cta_updated_7d,
            "posts_publish":     posts_publish,
            "x_posts_24h":       x_24h,
            "internal_links_added_7d": il_7d,
            "gsc_index_rate_pct": idx_rate,
            "gsc_index_counts":   idx_counts,
        },
        "recovery_phase": {
            "phase1_seo_recovery": {
                "gsc_resubmit": gsc_total >= 30,
                "internal_links_fixed": il_7d >= 50,
                "x_revival_queue_built": (LOGS / "x_revival_queue.jsonl").exists(),
            },
            "phase3_monetization": {
                "cta_injected_50posts": cta_updated_7d >= 50,
                "cv_articles_drafted": (LOGS / "cv_article_queue.jsonl").exists(),
            },
            "phase4_disaster_prevention": {
                "backup_script_installed": (BASE / "run_backup.sh").exists(),
                "recovery_snapshot_today": (LOGS / f"recovery_snapshot_{now.strftime('%Y%m%d')}.json").exists(),
            },
        },
    }

    OUT.write_text(json.dumps(kpi, ensure_ascii=False, indent=2))
    print(f"[kpi_recovery_builder] 保存: {OUT}")
    for k, v in kpi["kpis"].items():
        print(f"  {k:30s} = {v}")


if __name__ == "__main__":
    main()
