#!/usr/bin/env python3
"""
alert_queue.py — 通知失敗時のローカルキュー管理
CEO: ミュウツー / オーナー: 人間（閲覧専用）

【役割】
  discord_notifier.py が送信失敗した通知を logs/alert_queue.jsonl へ保存。
  run_alert_retry.sh が定期的にこのキューを読み再送する。

【ステータス遷移】
  pending → sent          : 再送成功
  pending → pending       : 再送失敗（retry_count +1）
  pending → permanent_failed : retry_count が MAX_RETRY を超過
  CRITICAL は permanent_failed になっても記録を保持し続ける

【transport 設計】
  send_via_transport() が実際の送信経路を抽象化。
  現在は Discord のみ。将来 Slack / Gmail を足す場合はここに追加する。
"""

import json
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).parent.parent
QUEUE_PATH   = BASE / "logs" / "alert_queue.jsonl"
RETRY_HISTORY_PATH = BASE / "logs" / "alert_retry_history.jsonl"
CONFIG_PATH  = BASE / "config" / "discord_webhooks.json"

JST = timezone(timedelta(hours=9))

MAX_RETRY_WARNING  = 5    # WARNING: 5回失敗で permanent_failed
MAX_RETRY_CRITICAL = 10   # CRITICAL: 10回失敗（permanent_failedにしても記録保持）

# Discord Cloudflare Bot対策: User-Agentを明示する
DISCORD_USER_AGENT = "DiscordBot (kpop-ai-monitor, 2.0)"


# ─────────────────────────────────────────────────────────────
# transport 層（送信経路の抽象化）
# ─────────────────────────────────────────────────────────────

def _get_webhook(channel: str) -> str:
    if not CONFIG_PATH.exists():
        return ""
    try:
        d = json.loads(CONFIG_PATH.read_text())
        return d.get(channel, "") or ""
    except Exception:
        return ""


def send_via_transport(channel: str, title: str, body: str,
                       color: int, event_key: str) -> tuple[str, str]:
    """
    通知を送信する transport 関数。
    現在は Discord Webhook のみ実装。
    将来 Slack / Gmail / 別Webhook を追加する場合はここに分岐を追加する。

    Returns:
        (result, detail)
        result: "sent" | "webhook_not_set" | "http_403" | "http_404" | "http_other" | "network_error"
        detail: エラー詳細文字列（sent なら空）
    """
    return _send_discord(channel, title, body, color, event_key)


def _send_discord(channel: str, title: str, body: str,
                  color: int, event_key: str) -> tuple[str, str]:
    """Discord Webhook 送信（User-Agent 明示で Cloudflare 対策済み）"""
    url = _get_webhook(channel)
    if not url:
        return "webhook_not_set", f"channel={channel}"

    now_jst = datetime.now(JST).strftime("%Y-%m-%d %H:%M JST")
    # body を2000字以内に収める
    import re
    body = re.sub(r'\n{3,}', '\n\n', body.strip())
    if len(body) > 1900:
        body = body[:1900] + "\n…（省略）"

    payload = {
        "username": "K-POP AI 監視システム",
        "embeds": [{
            "title": title,
            "description": body,
            "color": color,
            "footer": {
                "text": (
                    f"AI会社 監視システム v2.0 | CEO: ミュウツー | {now_jst}"
                    f" | key: {event_key}"
                )
            },
        }]
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", DISCORD_USER_AGENT)   # ← Cloudflare 1010 対策

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status in (200, 204):
                return "sent", ""
            return "http_other", f"HTTP {resp.status}"
    except urllib.error.HTTPError as e:
        snippet = ""
        try:
            snippet = e.read().decode("utf-8", errors="replace")[:120]
        except Exception:
            pass
        if e.code == 403:
            return "http_403", f"403 Forbidden — {snippet}"
        if e.code == 404:
            return "http_404", f"404 Not Found（Webhook削除済みの可能性）— {snippet}"
        return "http_other", f"HTTP {e.code} — {snippet}"
    except Exception as e:
        return "network_error", str(e)[:120]


# ─────────────────────────────────────────────────────────────
# キュー書き込み
# ─────────────────────────────────────────────────────────────

def enqueue(
    severity: str, channel: str, title: str, body: str,
    color: int, event_key: str, rule: str, last_error: str,
) -> None:
    """
    送信失敗した通知をキューへ保存する。
    dry-run 時は呼ばない（呼び出し元が制御）。
    """
    QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "queued_at":   datetime.now(timezone.utc).isoformat(),
        "severity":    severity,
        "channel":     channel,
        "title":       title,
        "body":        body,
        "color":       color,
        "event_key":   event_key,
        "rule":        rule,
        "retry_count": 0,
        "last_error":  last_error,
        "status":      "pending",
    }
    with QUEUE_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(
        f"  [queue] 保存: {event_key} severity={severity} last_error={last_error[:60]}",
        file=sys.stderr,
    )


# ─────────────────────────────────────────────────────────────
# キュー読み書き
# ─────────────────────────────────────────────────────────────

def load_queue() -> list[dict]:
    """全キューレコードを読み込む（全ステータス）"""
    if not QUEUE_PATH.exists():
        return []
    records = []
    with QUEUE_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def save_queue(records: list[dict]) -> None:
    """キュー全体を上書き保存する"""
    QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with QUEUE_PATH.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def append_retry_history(record: dict, result: str, detail: str) -> None:
    """再送結果を logs/alert_retry_history.jsonl へ追記"""
    RETRY_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "retried_at":  datetime.now(timezone.utc).isoformat(),
        "event_key":   record.get("event_key", ""),
        "severity":    record.get("severity", ""),
        "channel":     record.get("channel", ""),
        "retry_count": record.get("retry_count", 0),
        "result":      result,
        "detail":      detail,
    }
    with RETRY_HISTORY_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ─────────────────────────────────────────────────────────────
# 再送処理
# ─────────────────────────────────────────────────────────────

def retry_pending() -> dict:
    """
    pending 状態のキューを再送する。
    戻り値: {"sent": int, "failed": int, "pending": int, "permanent_failed": int}
    """
    records = load_queue()
    stats = {"sent": 0, "failed": 0, "pending": 0, "permanent_failed": 0}

    for rec in records:
        if rec.get("status") != "pending":
            # 既に完了・永続失敗のものはカウントだけ
            if rec.get("status") == "permanent_failed":
                stats["permanent_failed"] += 1
            continue

        severity    = rec.get("severity", "WARNING")
        event_key   = rec.get("event_key", "")
        channel     = rec.get("channel", "")
        title       = rec.get("title", "")
        body        = rec.get("body", "")
        color       = rec.get("color", 0xF39C12)
        retry_count = rec.get("retry_count", 0)
        max_retry   = MAX_RETRY_CRITICAL if severity == "CRITICAL" else MAX_RETRY_WARNING

        result, detail = send_via_transport(channel, title, body, color, event_key)

        if result == "sent":
            rec["status"]      = "sent"
            rec["last_error"]  = ""
            rec["retry_count"] = retry_count + 1
            stats["sent"] += 1
            print(f"  [retry] ✅ 送信成功: {event_key}", file=sys.stderr)
        else:
            rec["retry_count"] = retry_count + 1
            rec["last_error"]  = f"{result}: {detail}"

            if rec["retry_count"] >= max_retry:
                rec["status"] = "permanent_failed"
                stats["permanent_failed"] += 1
                level = "⚠️ " if severity == "CRITICAL" else "🔴"
                print(
                    f"  [retry] {level} permanent_failed({severity}): {event_key} "
                    f"(試行{rec['retry_count']}回)",
                    file=sys.stderr,
                )
            else:
                rec["status"] = "pending"
                stats["failed"] += 1
                print(
                    f"  [retry] ❌ 失敗({result}) retry={rec['retry_count']}/{max_retry}: {event_key}",
                    file=sys.stderr,
                )

        append_retry_history(rec, result, detail)

    # pending 残数カウント（再送後も pending のもの）
    stats["pending"] = sum(1 for r in records if r.get("status") == "pending")

    save_queue(records)
    return stats


# ─────────────────────────────────────────────────────────────
# キュー状態確認
# ─────────────────────────────────────────────────────────────

def queue_status() -> dict:
    """キューの現在の状態サマリーを返す"""
    from collections import Counter
    records = load_queue()
    counts = Counter(r.get("status", "unknown") for r in records)
    return {
        "total":            len(records),
        "pending":          counts.get("pending", 0),
        "sent":             counts.get("sent", 0),
        "permanent_failed": counts.get("permanent_failed", 0),
        "critical_pending": sum(
            1 for r in records
            if r.get("status") == "pending" and r.get("severity") == "CRITICAL"
        ),
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="アラートキュー管理")
    parser.add_argument("--retry",  action="store_true", help="pending を再送")
    parser.add_argument("--status", action="store_true", help="キュー状態を表示")
    args = parser.parse_args()

    if args.status:
        s = queue_status()
        print(f"キュー状態: total={s['total']} pending={s['pending']} "
              f"sent={s['sent']} permanent_failed={s['permanent_failed']} "
              f"CRITICAL_pending={s['critical_pending']}")

    if args.retry:
        print("[alert_queue] 再送開始...", file=sys.stderr)
        stats = retry_pending()
        print(f"  送信成功: {stats['sent']}件", file=sys.stderr)
        print(f"  失敗:     {stats['failed']}件", file=sys.stderr)
        print(f"  pending残: {stats['pending']}件", file=sys.stderr)
        print(f"  永続失敗: {stats['permanent_failed']}件", file=sys.stderr)
        print(json.dumps({"queue_retry": stats}, ensure_ascii=False))
