#!/usr/bin/env python3
"""
x_daily_link_check.py — 過去7日間のX投稿リンクを毎日チェック

cron: 30 3 * * * python3 /home/aiuser/kpop-ai-system/lib/x_daily_link_check.py

404/soft-404が見つかった場合:
  1. logs/x_link_errors.jsonl にログ
  2. Discord urgent_errors に通知
"""

import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "lib"))

from x_post_url_validator import validate_url

JST = timezone(timedelta(hours=9))
POSTED_URLS = BASE / "logs" / "x_posted_urls.txt"
LINK_ERRORS_LOG = BASE / "logs" / "x_link_errors.jsonl"
DISCORD_CFG = BASE / "config" / "discord_webhooks.json"


def load_recent_urls(days=7):
    """直近N日間の投稿URLを読み込む"""
    if not POSTED_URLS.exists():
        return []

    cutoff = int((datetime.now(JST) - timedelta(days=days)).timestamp())
    urls = []
    for line in POSTED_URLS.read_text().strip().split("\n"):
        if not line.strip():
            continue
        parts = line.strip().split("|", 1)
        if len(parts) == 2:
            ts, url = int(parts[0]), parts[1]
            if ts >= cutoff:
                urls.append({"ts": ts, "url": url})
    return urls


def check_urls(urls):
    """全URLを検証し、NG結果を返す"""
    errors = []
    for entry in urls:
        result = validate_url(entry["url"])
        if not result["ok"]:
            errors.append({
                "url": entry["url"],
                "ts": entry["ts"],
                "checked_at": datetime.now(JST).isoformat(),
                **result,
            })
        time.sleep(0.5)
    return errors


def notify_discord(errors):
    """Discord urgent_errorsに通知"""
    if not DISCORD_CFG.exists():
        return
    try:
        cfg = json.loads(DISCORD_CFG.read_text())
        webhook = cfg.get("urgent_errors", "")
        if not webhook:
            return

        import urllib.request
        msg = f"🔴 **X投稿リンクチェック: {len(errors)}件のエラー検出**\n"
        for e in errors[:5]:
            msg += f"  • {e['reason']}: {e['url'][:60]}\n"
        if len(errors) > 5:
            msg += f"  ...他{len(errors) - 5}件\n"
        msg += "→ `logs/x_link_errors.jsonl` を確認してください"

        payload = json.dumps({"content": msg[:1800]}).encode()
        req = urllib.request.Request(
            webhook, data=payload,
            headers={"Content-Type": "application/json"}, method="POST"
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"Discord通知失敗: {e}", file=sys.stderr)


def main():
    urls = load_recent_urls(days=7)
    print(f"チェック対象: {len(urls)}件")

    if not urls:
        print("直近7日のX投稿URLなし")
        return

    errors = check_urls(urls)

    if errors:
        print(f"\n⚠️ エラー検出: {len(errors)}件")
        for e in errors:
            print(f"  {e['reason']}: {e['url'][:70]}")

        # ログ記録
        with open(LINK_ERRORS_LOG, "a") as f:
            for e in errors:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")

        # Discord通知
        notify_discord(errors)
    else:
        print(f"✅ 全{len(urls)}件 正常")


if __name__ == "__main__":
    main()
