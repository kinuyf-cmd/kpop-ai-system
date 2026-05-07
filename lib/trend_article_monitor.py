#!/usr/bin/env python3
"""
trend_article_monitor.py — トレンド記事自動生成の監視
feature_article_generator の実行結果をチェックし、異常時にDiscord通知。

cron: 8:30, 20:30 (生成の30分後)
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"
LOG_FILE = LOGS / "feature_article_generator.log"
MONITOR_LOG = LOGS / "trend_article_monitor.log"

JST = timezone(timedelta(hours=9))

try:
    from dotenv import load_dotenv
    load_dotenv(BASE / ".env")
except ImportError:
    pass


def log(msg: str):
    ts = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(MONITOR_LOG, "a") as f:
        f.write(line + "\n")


def notify_discord(message: str):
    webhook = os.getenv("DISCORD_WEBHOOK_URL", "")
    if not webhook:
        return
    import urllib.request
    data = json.dumps({"content": message}).encode()
    req = urllib.request.Request(
        webhook, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        log(f"Discord通知失敗: {e}")


def check_latest_run() -> dict:
    """直近の feature_article_generator 実行結果を解析"""
    if not LOG_FILE.exists():
        return {"status": "error", "detail": "ログファイルが存在しません"}

    text = LOG_FILE.read_text(errors="replace")
    lines = text.strip().split("\n")

    # 今日の日付
    today = datetime.now(JST).strftime("%Y-%m-%d")

    # 直近の実行ブロックを探す
    run_start = None
    for i, line in enumerate(lines):
        if "feature_article_generator" in line and today in line:
            run_start = i
            break

    if run_start is None:
        return {"status": "warn", "detail": f"今日({today})の実行ログが見つかりません"}

    run_lines = lines[run_start:]
    run_text = "\n".join(run_lines)

    # 公開件数を抽出
    published = re.findall(r"post_id=(\d+)\s+公開", run_text)
    errors = re.findall(r"(❌|ERROR|失敗|Exception)", run_text)
    x_errors = re.findall(r"X投稿失敗", run_text)

    # 件数サマリ行を探す
    summary_match = re.search(r"(\d+)/(\d+)件\s+特集記事公開", run_text)
    success_count = int(summary_match.group(1)) if summary_match else len(published)
    total_count = int(summary_match.group(2)) if summary_match else 0

    result = {
        "status": "ok",
        "date": today,
        "published": success_count,
        "total": total_count,
        "post_ids": published,
        "x_errors": len(x_errors),
        "other_errors": len(errors) - len(x_errors),
    }

    if success_count == 0:
        result["status"] = "critical"
        result["detail"] = "記事が1件も公開されていません"
    elif total_count > 0 and success_count < total_count * 0.5:
        result["status"] = "warn"
        result["detail"] = f"公開率が低い: {success_count}/{total_count}"

    # X投稿が全滅の場合も警告（記事公開自体は成功していても）
    if result.get("x_errors", 0) > 0 and success_count > 0:
        x_detail = f"X投稿 {result['x_errors']}件失敗"
        if result["status"] == "ok":
            result["status"] = "warn"
            result["detail"] = x_detail
        else:
            result["detail"] = f"{result.get('detail', '')} / {x_detail}"

    return result


def main():
    log("=== Trend Article Monitor START ===")
    result = check_latest_run()

    log(f"Status: {result['status']}")
    if result.get("published") is not None:
        log(f"公開: {result['published']}/{result.get('total', '?')}件, X error: {result.get('x_errors', 0)}")
    if result.get("detail"):
        log(f"Detail: {result['detail']}")

    # 異常時はDiscord通知
    if result["status"] in ("critical", "error"):
        notify_discord(
            f"🚨 トレンド記事自動生成 異常\n"
            f"Status: {result['status']}\n"
            f"{result.get('detail', '')}\n"
            f"公開: {result.get('published', 0)}件"
        )
    elif result["status"] == "warn":
        notify_discord(
            f"⚠️ トレンド記事自動生成 警告\n"
            f"{result.get('detail', '')}\n"
            f"公開: {result.get('published', 0)}/{result.get('total', '?')}件"
        )

    # 監視結果をJSONで保存
    out_path = LOGS / "trend_article_monitor_latest.json"
    with open(out_path, "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    log("=== Trend Article Monitor END ===")
    return 0 if result["status"] in ("ok", "warn") else 1


if __name__ == "__main__":
    sys.exit(main())
