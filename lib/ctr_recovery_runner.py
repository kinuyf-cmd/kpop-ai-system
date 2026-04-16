#!/usr/bin/env python3
"""ctr_recovery_runner.py — CTR回復ランナー (v2)

新ソース: logs/gsc_metrics_latest.json (gsc_metrics_fetcher.py 出力)

対象判定:
  - impressions > 50
  - ctr < 3% (0.03)
  - スラッグは絶対変更禁止
  - 1記事最大2回まで (logs/ctr_recovery_history.jsonl で管理)

アクション:
  1. rewrite_candidates.jsonl 書き出し
  2. 既存 google_metrics/update_low_ctr_titles.sh / rewrite_low_ctr_articles.sh へ委譲

使い方:
  python3 lib/ctr_recovery_runner.py                    # 候補出力 + 実行
  python3 lib/ctr_recovery_runner.py --dry-run
  python3 lib/ctr_recovery_runner.py --max 5
  python3 lib/ctr_recovery_runner.py --candidates-only  # 候補JSONL出力のみ
"""
from __future__ import annotations
import argparse
import json
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"
METRICS = LOGS / "gsc_metrics_latest.json"
HISTORY = LOGS / "ctr_recovery_history.jsonl"
CANDIDATES = LOGS / "rewrite_candidates.jsonl"
UPDATE_TITLES_SH = BASE / "google_metrics" / "update_low_ctr_titles.sh"
REWRITE_SH = BASE / "google_metrics" / "rewrite_low_ctr_articles.sh"
JST = timezone(timedelta(hours=9))

IMPR_THRESHOLD = 50
CTR_THRESHOLD = 0.03  # 3%
MAX_RETRIES_PER_URL = 2


def load_candidates() -> list[dict]:
    if not METRICS.exists():
        return []
    try:
        d = json.loads(METRICS.read_text())
    except Exception:
        return []
    pages = d.get("pages", [])
    out = []
    for p in pages:
        impr = p.get("impressions", 0)
        ctr = p.get("ctr", 0.0)
        if impr > IMPR_THRESHOLD and ctr < CTR_THRESHOLD:
            out.append(p)
    return out


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


def write_candidates(cand: list[dict]) -> None:
    ts = datetime.now(tz=JST).isoformat()
    with CANDIDATES.open("w") as fp:
        for c in cand:
            retries = count_retries(c["url"])
            fp.write(json.dumps({
                "ts": ts,
                "url": c["url"],
                "impressions": c["impressions"],
                "clicks": c["clicks"],
                "ctr_pct": round(c["ctr"] * 100, 2),
                "position": round(c.get("position", 0), 1),
                "prior_retries": retries,
                "eligible": retries < MAX_RETRIES_PER_URL,
            }, ensure_ascii=False) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max", type=int, default=5)
    ap.add_argument("--candidates-only", action="store_true")
    args = ap.parse_args()

    cand = load_candidates()
    print(f"[ctr_recovery] GSC条件(impr>{IMPR_THRESHOLD} & ctr<{CTR_THRESHOLD*100}%) 候補={len(cand)}件")

    # Always write the candidates file (為 他システムが参照可能)
    write_candidates(cand)
    print(f"  候補ファイル: {CANDIDATES}")

    if args.candidates_only:
        return

    ts = datetime.now(tz=JST).isoformat()
    processed = 0
    skipped_retry = 0

    for c in cand:
        if processed >= args.max:
            break
        if count_retries(c["url"]) >= MAX_RETRIES_PER_URL:
            skipped_retry += 1
            continue
        processed += 1
        url = c["url"]
        ctr_pct = c["ctr"] * 100
        if args.dry_run:
            print(f"  [dry] {url} impr={c['impressions']} ctr={ctr_pct:.2f}% pos={c.get('position',0):.1f}")
            continue

        # Rewrite via existing scripts
        title_ok = body_ok = False
        try:
            if UPDATE_TITLES_SH.exists():
                r = subprocess.run(["bash", str(UPDATE_TITLES_SH), url],
                                   timeout=180, capture_output=True, text=True)
                title_ok = r.returncode == 0
        except Exception as e:
            print(f"  [title-sh error] {url}: {e}")
        try:
            if REWRITE_SH.exists():
                r = subprocess.run(["bash", str(REWRITE_SH), url],
                                   timeout=360, capture_output=True, text=True)
                body_ok = r.returncode == 0
        except Exception as e:
            print(f"  [rewrite-sh error] {url}: {e}")

        rec = {
            "ts": ts, "url": url,
            "impressions": c["impressions"], "clicks": c["clicks"],
            "ctr_pct": round(ctr_pct, 2),
            "position": round(c.get("position", 0), 1),
            "title_rewritten": title_ok, "body_rewritten": body_ok,
        }
        with HISTORY.open("a") as fp:
            fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
        mark = "✅" if (title_ok or body_ok) else "⚠️"
        print(f"  {mark} {url} title={title_ok} body={body_ok}")

    print()
    print(f"[ctr_recovery] 実行={processed} 既上限={skipped_retry} 候補全体={len(cand)} max={args.max}")
    print(f"  履歴: {HISTORY}")


if __name__ == "__main__":
    main()
