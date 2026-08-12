#!/usr/bin/env python3
"""X自動投稿の可視性ガード(シャドウバン再発の自動検知→自動再停止)。

2026-08-12 Phase 1再開の安全網として新設。日次で直近7日の実投稿impを
get_public_metrics で実測し、平均が閾値を割ったら X系cronを
"# [X-PAUSE auto YYYY-MM-DD] " マーカーでコメントアウトして Discord に通知する。
マーカー形式は tools/x_pause_resume.sh と互換(同スクリプトで再開可)。

判定基準(env で上書き可):
  X_REPAUSE_THRESHOLD  平均imp閾値 (default 5.0)  # バン時崩壊水準2.67-6の中間
  X_REPAUSE_MIN_N      判定に必要な投稿数 (default 8)
  X_REPAUSE_WINDOW_D   観測窓・日 (default 7)
  X_REPAUSE_AGE_H      imp集計に含める最低経過時間 (default 24)

冪等: アクティブなX系cronが無ければ何もしない。判定結果は毎回
logs/x_repause_guard.jsonl に記録(可観測化)。
"""
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

BASE = Path("/home/aiuser/kpop-ai-system")
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "google_metrics"))

POSTS_LOG = BASE / "logs" / "x_posts.jsonl"
GUARD_LOG = BASE / "logs" / "x_repause_guard.jsonl"
REPAUSE_LOG = Path.home() / ".kpop_recovery" / "x_auto_repause.log"
CRON_BACKUP_DIR = Path.home() / ".kpop_recovery" / "cron_backups"

THRESHOLD = float(os.environ.get("X_REPAUSE_THRESHOLD", "5.0"))
MIN_N = int(os.environ.get("X_REPAUSE_MIN_N", "8"))
WINDOW_D = int(os.environ.get("X_REPAUSE_WINDOW_D", "7"))
AGE_H = int(os.environ.get("X_REPAUSE_AGE_H", "24"))

# 停止対象のX系cron(実行行のみ。既にコメントの行は対象外)
X_CRON_RE = re.compile(
    r"^(?!#).*(pipeline\.x_scheduled_poster|x_conversation_starter\.py|x_engagement_responder\.py)"
)


def _recent_post_ids() -> list[str]:
    """直近WINDOW_D日・24h以上経過・status ok のトップレベル投稿 tweet_id を返す。"""
    if not POSTS_LOG.exists():
        return []
    now = datetime.now()
    lo = now - timedelta(days=WINDOW_D)
    hi = now - timedelta(hours=AGE_H)
    ids = []
    for line in POSTS_LOG.read_text().splitlines():
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        if d.get("status") != "ok" or not d.get("tweet_id"):
            continue
        if d.get("reply_to"):  # URLリプライ等は親のimpに含まれるため除外
            continue
        try:
            ts = datetime.fromisoformat(d["ts"])
        except (KeyError, ValueError):
            continue
        if lo <= ts <= hi:
            ids.append(str(d["tweet_id"]))
    return ids


def _avg_impression(ids: list[str]) -> tuple[float, int]:
    from post_to_x import get_public_metrics

    imps = []
    for i in range(0, len(ids), 100):
        # get_public_metrics は {tweet_id: {impression_count, ...}} を返す
        data = get_public_metrics(ids[i : i + 100]) or {}
        for m in data.values():
            imps.append(int(m.get("impression_count", 0)))
    if not imps:
        return 0.0, 0
    return sum(imps) / len(imps), len(imps)


def _active_x_cron_lines(cron_text: str) -> list[str]:
    return [l for l in cron_text.splitlines() if X_CRON_RE.match(l)]


def _pause_crons(dry_run: bool) -> int:
    cron_text = subprocess.run(
        ["crontab", "-l"], capture_output=True, text=True
    ).stdout
    today = datetime.now().strftime("%Y-%m-%d")
    marker = f"# [X-PAUSE auto {today}] "
    out, paused = [], 0
    for line in cron_text.splitlines():
        if X_CRON_RE.match(line):
            out.append(marker + line)
            paused += 1
        else:
            out.append(line)
    if paused and not dry_run:
        CRON_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        backup = CRON_BACKUP_DIR / f"crontab_auto_repause_{today}.bak"
        backup.write_text(cron_text)
        # crontab更新はstdin経由必須(長パスarg失敗の既知問題)
        subprocess.run(
            ["crontab", "-"], input="\n".join(out) + "\n", text=True, check=True
        )
    return paused


def _notify_discord(msg: str) -> None:
    try:
        from lib.resolve_discord_webhook import resolve

        url = resolve("urgent_errors")
        if not url:
            return
        req = urllib.request.Request(
            url,
            data=json.dumps({"content": msg}).encode(),
            headers={
                "Content-Type": "application/json",
                "User-Agent": "KpopJournal-Bot/2.0 (x-auto-repause-guard)",
            },
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:  # 通知失敗で停止処理は止めない
        print(f"discord notify failed: {e}", file=sys.stderr)


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    record = {"ts": datetime.now().isoformat(), "threshold": THRESHOLD}

    cron_text = subprocess.run(
        ["crontab", "-l"], capture_output=True, text=True
    ).stdout
    active = _active_x_cron_lines(cron_text)
    if not active:
        record["result"] = "noop_no_active_cron"
        _log(record)
        print("no active X posting cron; nothing to guard")
        return 0

    ids = _recent_post_ids()
    if len(ids) < MIN_N:
        record.update({"result": "noop_insufficient_data", "n": len(ids)})
        _log(record)
        print(f"insufficient data: {len(ids)} posts < MIN_N={MIN_N}")
        return 0

    avg, n = _avg_impression(ids)
    record.update({"avg_impression": round(avg, 2), "n": n})
    if avg >= THRESHOLD:
        record["result"] = "healthy"
        _log(record)
        print(f"healthy: avg imp {avg:.2f} >= {THRESHOLD} (n={n})")
        return 0

    paused = _pause_crons(dry_run)
    record.update({"result": "repaused" if not dry_run else "would_repause",
                   "paused_lines": paused})
    _log(record)
    msg = (
        f"🚨 [X自動再停止] 直近{WINDOW_D}日の平均imp {avg:.2f} が閾値 {THRESHOLD} を"
        f"割りました(n={n})。シャドウバン再発の疑いでX投稿cron {paused}本を自動停止しました。"
        f"再開は tools/x_pause_resume.sh。診断は x-shadowban メモリの3点セットで。"
    )
    if not dry_run:
        _notify_discord(msg)
        with REPAUSE_LOG.open("a") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n")
    print(msg)
    return 0


def _log(record: dict) -> None:
    with GUARD_LOG.open("a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    sys.exit(main())
