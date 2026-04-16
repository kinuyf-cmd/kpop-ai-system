#!/usr/bin/env python3
"""recovery_snapshot.py — 現在状態のスナップショットを logs/recovery_snapshot_YYYYMMDD.json に保存

含める情報:
  - システム: git HEAD、ブランチ、running processes
  - コンテンツ: 公開記事数、draft数、カテゴリ/タグ数
  - パイプライン: 直近 N 件のpipeline run、成功/失敗件数
  - X/GSC 状況
  - 設定の要約 (cron / 主要設定ファイルのハッシュ)
  - 直近エラー

使い方:
  python3 lib/recovery_snapshot.py
"""
from __future__ import annotations
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"
JST = timezone(timedelta(hours=9))
WP = "https://www.kpopjournal.tokyo"
WP_AUTH = str(Path.home() / ".wp_auth")


def run(cmd: list[str]) -> str:
    try:
        return subprocess.check_output(cmd, timeout=30, stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        return ""


def curl_get(path: str):
    try:
        return json.loads(subprocess.check_output(
            ["curl", "-s", f"{WP}{path}", "-K", WP_AUTH], timeout=30).decode())
    except Exception:
        return None


def file_hash(p: Path) -> str:
    if not p.exists():
        return ""
    h = hashlib.sha256()
    with p.open("rb") as fp:
        for chunk in iter(lambda: fp.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def count_jsonl(p: Path) -> int:
    if not p.exists():
        return 0
    return sum(1 for line in p.read_text(errors="replace").splitlines() if line.strip())


def count_publish_and_draft() -> dict:
    # 件数をヘッダから取得
    result = {"publish": 0, "draft": 0}
    for status in ("publish", "draft"):
        try:
            out = subprocess.check_output(
                ["curl", "-sI", f"{WP}/wp-json/wp/v2/posts?per_page=1&status={status}",
                 "-K", WP_AUTH], timeout=20).decode()
            m = re.search(r"X-WP-Total:\s*(\d+)", out, re.I)
            if m:
                result[status] = int(m.group(1))
        except Exception:
            pass
    return result


def main():
    now = datetime.now(tz=JST)
    date_str = now.strftime("%Y%m%d")
    out_file = LOGS / f"recovery_snapshot_{date_str}.json"

    # git
    git_head = run(["git", "-C", str(BASE), "rev-parse", "HEAD"])
    git_branch = run(["git", "-C", str(BASE), "rev-parse", "--abbrev-ref", "HEAD"])
    git_dirty = run(["git", "-C", str(BASE), "status", "--porcelain"])
    last_commits = run(["git", "-C", str(BASE), "log", "--oneline", "-10"])

    # WP content
    post_counts = count_publish_and_draft()
    cats = curl_get("/wp-json/wp/v2/categories?per_page=1&_fields=id") or []
    tags = curl_get("/wp-json/wp/v2/tags?per_page=1&_fields=id") or []

    # Pipeline stats (last 7 days)
    pjsonl = LOGS / "pipeline.jsonl"
    recent_runs = {"total": 0, "by_step": {}, "by_status": {}, "errors": []}
    if pjsonl.exists():
        cutoff = now - timedelta(days=7)
        for line in pjsonl.read_text(errors="replace").splitlines():
            try:
                r = json.loads(line)
                ts = r.get("timestamp", "")
                if not ts:
                    continue
                t = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(JST)
                if t < cutoff:
                    continue
                recent_runs["total"] += 1
                recent_runs["by_step"][r.get("step", "?")] = recent_runs["by_step"].get(r.get("step", "?"), 0) + 1
                recent_runs["by_status"][r.get("status", "?")] = recent_runs["by_status"].get(r.get("status", "?"), 0) + 1
                if r.get("status") == "error":
                    recent_runs["errors"].append({
                        "ts": ts, "step": r.get("step", ""), "message": r.get("message", "")[:120]
                    })
            except Exception:
                continue
        recent_runs["errors"] = recent_runs["errors"][-10:]

    # Config hashes
    config_files = {}
    for f in ["kpop_pipeline.sh", "kpop_strategy_pipeline.sh", "kpop_chart_pipeline.sh",
              "post_audit.sh", "run_backup.sh", "google_metrics/post_to_x.sh"]:
        fp = BASE / f
        if fp.exists():
            config_files[f] = {
                "sha256_16": file_hash(fp),
                "bytes": fp.stat().st_size,
                "mtime": datetime.fromtimestamp(fp.stat().st_mtime, tz=JST).isoformat(),
            }

    # Cron summary
    cron = run(["crontab", "-l"])
    cron_entries = [l for l in cron.splitlines() if l and not l.startswith("#") and l.strip()]

    # X posting / GSC
    x_post_log = LOGS / "x_post.log"
    gsc_resubmit_log = LOGS / "gsc_resubmit_log.jsonl"

    snapshot = {
        "generated_at": now.isoformat(),
        "date": date_str,
        "git": {
            "head": git_head[:12],
            "branch": git_branch,
            "dirty_count": len(git_dirty.splitlines()) if git_dirty else 0,
            "last_commits": last_commits.splitlines(),
        },
        "wordpress": {
            "posts_publish": post_counts.get("publish", 0),
            "posts_draft": post_counts.get("draft", 0),
            "categories_sample": len(cats) if isinstance(cats, list) else 0,
            "tags_sample": len(tags) if isinstance(tags, list) else 0,
        },
        "pipeline_last_7d": recent_runs,
        "x_post_log_lines": count_jsonl(x_post_log) if x_post_log.exists() else 0,
        "gsc_resubmits": count_jsonl(gsc_resubmit_log),
        "cron_entries": len(cron_entries),
        "critical_files": config_files,
        "notes": [
            "2026-04-16: flock排他＋品質ゲート緩和＋サムネalt3層修正を実施",
            "復旧後の再投稿・内部リンク・CTA注入を一括実行",
        ],
    }

    out_file.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2))
    print(f"[recovery_snapshot] 保存: {out_file}")
    print(f"  posts={snapshot['wordpress']['posts_publish']} "
          f"drafts={snapshot['wordpress']['posts_draft']} "
          f"pipeline_events_7d={recent_runs['total']}")


if __name__ == "__main__":
    main()
