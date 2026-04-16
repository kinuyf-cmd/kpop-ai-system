#!/usr/bin/env python3
"""ctr_recovery_runner.py — CTR回復ランナー

対象判定:
  - GSC データ (metrics_yesterday.json / gsc_* logs) から CTR<2% AND impressions>100 の記事を抽出
  - スラッグは絶対変更禁止
  - 1記事あたり最大2回まで (logs/ctr_recovery_history.jsonl で管理)

アクション:
  - タイトル再生成 (スラッグ維持)
  - サムネ再生成
  - X フック再生成 (次回再投稿キューに追加)

実装方針: 既存ツールへ委譲
  - google_metrics/update_low_ctr_titles.sh
  - google_metrics/rewrite_low_ctr_articles.sh (HTML本文リライト)

使い方:
  python3 lib/ctr_recovery_runner.py [--dry-run] [--max 5]
"""
from __future__ import annotations
import argparse
import json
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"
METRICS_YESTERDAY = BASE / "google_metrics" / "metrics_yesterday.json"
HISTORY = LOGS / "ctr_recovery_history.jsonl"
UPDATE_TITLES_SH = BASE / "google_metrics" / "update_low_ctr_titles.sh"
REWRITE_SH = BASE / "google_metrics" / "rewrite_low_ctr_articles.sh"
JST = timezone(timedelta(hours=9))


def load_candidates() -> list[dict]:
    if not METRICS_YESTERDAY.exists():
        return []
    try:
        data = json.loads(METRICS_YESTERDAY.read_text())
    except Exception:
        return []
    rows = data.get("rows", data) if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return []
    candidates = []
    for r in rows:
        ctr = r.get("ctr") or r.get("CTR") or 0
        impr = r.get("impressions") or r.get("Impressions") or 0
        try:
            ctr = float(ctr); impr = int(impr)
        except Exception:
            continue
        # CTR は小数 (0.02=2%) か百分率 (2.0) のどちらかありうる
        if ctr > 1: ctr /= 100
        if ctr < 0.02 and impr > 100:
            url = r.get("url") or r.get("page") or r.get("URL")
            if url:
                candidates.append({"url": url, "ctr": ctr, "impressions": impr})
    return candidates


def count_retries(url: str) -> int:
    if not HISTORY.exists():
        return 0
    n = 0
    for line in HISTORY.read_text(errors="replace").splitlines():
        try:
            d = json.loads(line)
            if d.get("url") == url:
                n += 1
        except Exception:
            continue
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max", type=int, default=5)
    args = ap.parse_args()

    cand = load_candidates()
    print(f"[ctr_recovery] GSCデータから候補 {len(cand)}件")
    ts = datetime.now(tz=JST).isoformat()
    processed = 0
    skipped_retry = 0
    run_results = []

    for c in cand:
        if processed >= args.max:
            break
        if count_retries(c["url"]) >= 2:
            skipped_retry += 1
            continue
        processed += 1
        if args.dry_run:
            print(f"  [dry] {c['url']} ctr={c['ctr']*100:.2f}% impr={c['impressions']}")
            continue
        # 既存リライターに委譲
        title_ok = False
        if UPDATE_TITLES_SH.exists():
            try:
                r = subprocess.run(["bash", str(UPDATE_TITLES_SH), c["url"]],
                                   timeout=120, capture_output=True, text=True)
                title_ok = r.returncode == 0
            except Exception as e:
                print(f"  [title-sh error] {e}")
        rewrite_ok = False
        if REWRITE_SH.exists():
            try:
                r = subprocess.run(["bash", str(REWRITE_SH), c["url"]],
                                   timeout=300, capture_output=True, text=True)
                rewrite_ok = r.returncode == 0
            except Exception as e:
                print(f"  [rewrite-sh error] {e}")
        rec = {
            "ts": ts, "url": c["url"], "ctr_pct": round(c["ctr"] * 100, 2),
            "impressions": c["impressions"],
            "title_rewritten": title_ok, "body_rewritten": rewrite_ok,
        }
        run_results.append(rec)
        with HISTORY.open("a") as fp:
            fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
        mark = "✅" if (title_ok or rewrite_ok) else "⚠️"
        print(f"  {mark} {c['url']} title={title_ok} body={rewrite_ok}")

    print()
    print(f"[ctr_recovery] processed={processed} skipped_retry_limit={skipped_retry} "
          f"候補全体={len(cand)}")
    print(f"  履歴: {HISTORY}")


if __name__ == "__main__":
    main()
