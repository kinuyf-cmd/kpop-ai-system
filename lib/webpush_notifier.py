#!/usr/bin/env python3
"""
Webプッシュ通知 v1.0
- VAPID認証によるWeb Push API対応
- 速報記事の即時ブラウザ通知
- 購読者管理（JSONファイルベース → 将来的にWP REST API連携）
- 静粛時間帯・レートリミット・TTL対応

Usage:
  python3 lib/webpush_notifier.py --title "タイトル" --url "記事URL" --category breaking
  python3 lib/webpush_notifier.py --title "..." --url "..." --image "サムネURL"
  python3 lib/webpush_notifier.py --validate
  python3 lib/webpush_notifier.py --dry-run --title "..." --url "..."
  python3 lib/webpush_notifier.py --stats   # 購読者統計

前提:
  pip install pywebpush

  ~/.webpush_vapid に以下のJSON:
  {
    "private_key": "VAPID秘密鍵（Base64 URL-safe）",
    "public_key": "VAPID公開鍵（Base64 URL-safe）",
    "claims_email": "mailto:kinu.yf@gmail.com"
  }

  VAPID鍵ペア生成:
    python3 -c "from pywebpush import webpush; from py_vapid import Vapid; v=Vapid(); v.generate_keys(); print(v.private_pem()); print(v.public_key)"
    または: npx web-push generate-vapid-keys

  購読者データ:
    logs/webpush_subscriptions.jsonl — 各行がsubscription object
    WordPressプラグインまたはカスタムREST APIで購読登録を受け付ける

Service Worker設定（WordPress側に設置）:
  wp-content/themes/your-theme/sw.js
"""
import json
import sys
import os
import time
import argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
LOGS_DIR = BASE_DIR / "logs"
CONFIG_PATH = BASE_DIR / "config" / "sns_config.json"
CREDS_FILE = Path(os.path.expanduser("~/.webpush_vapid"))
SUBSCRIPTIONS_FILE = LOGS_DIR / "webpush_subscriptions.jsonl"
HISTORY_LOG = LOGS_DIR / "webpush_history.jsonl"

JST = timezone(timedelta(hours=9))

MAX_RETRIES = 2
BATCH_SIZE = 50  # 同時送信数


# ── 設定・認証 ──

def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text()).get("webpush", {})
    except Exception:
        return {}


def load_credentials() -> tuple[dict | None, list[str]]:
    errors = []
    if not CREDS_FILE.exists():
        errors.append(f"CRED_MISSING: {CREDS_FILE} が見つかりません")
        errors.append('  {"private_key":"...","public_key":"...","claims_email":"mailto:..."}')
        return None, errors

    try:
        creds = json.loads(CREDS_FILE.read_text())
    except json.JSONDecodeError as e:
        errors.append(f"CRED_JSON_INVALID: {e}")
        return None, errors

    for key in ["private_key", "public_key", "claims_email"]:
        if not creds.get(key, ""):
            errors.append(f"CRED_KEY_EMPTY: '{key}' が未設定")

    if errors:
        return None, errors
    return creds, []


# ── 購読者管理 ──

def load_subscriptions() -> list[dict]:
    if not SUBSCRIPTIONS_FILE.exists():
        return []
    subs = []
    for line in SUBSCRIPTIONS_FILE.read_text().strip().split("\n"):
        if not line.strip():
            continue
        try:
            sub = json.loads(line)
            if sub.get("endpoint") and sub.get("keys"):
                subs.append(sub)
        except Exception:
            continue
    return subs


def remove_subscription(endpoint: str):
    """無効な購読を除去"""
    if not SUBSCRIPTIONS_FILE.exists():
        return
    lines = SUBSCRIPTIONS_FILE.read_text().strip().split("\n")
    valid = []
    for line in lines:
        if not line.strip():
            continue
        try:
            sub = json.loads(line)
            if sub.get("endpoint") != endpoint:
                valid.append(line)
        except Exception:
            valid.append(line)
    SUBSCRIPTIONS_FILE.write_text("\n".join(valid) + "\n" if valid else "")


# ── ログ ──

def _log(entry: dict):
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ── ガード ──

def _is_quiet_hours(config: dict) -> bool:
    quiet = config.get("push_rules", {}).get("quiet_hours", {})
    if not quiet:
        return False
    now = datetime.now(JST)
    start_h, start_m = map(int, quiet.get("start", "23:00").split(":"))
    end_h, end_m = map(int, quiet.get("end", "07:00").split(":"))
    current = now.hour * 60 + now.minute
    start = start_h * 60 + start_m
    end = end_h * 60 + end_m
    if start > end:
        return current >= start or current < end
    return start <= current < end


def _should_push(category: str, config: dict) -> bool:
    triggers = config.get("push_rules", {}).get("trigger_categories", ["breaking", "comeback"])
    return category in triggers


def _check_daily_limit(config: dict) -> tuple[bool, str]:
    max_daily = config.get("push_rules", {}).get("max_daily_pushes", 5)
    if not HISTORY_LOG.exists():
        return True, ""
    now = datetime.now(JST)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    count = 0
    for line in HISTORY_LOG.read_text().strip().split("\n"):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
            if rec.get("result") != "sent":
                continue
            ts = datetime.fromisoformat(rec["timestamp"].replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=JST)
            if ts >= today_start:
                count += 1
        except Exception:
            continue
    if count >= max_daily:
        return False, f"本日の配信上限（{max_daily}件）に到達"
    return True, ""


# ── 通知ペイロード構築 ──

def build_payload(title: str, url: str, image_url: str = "",
                   category: str = "breaking", config: dict = None) -> dict:
    config = config or {}
    defaults = config.get("notification_defaults", {})

    category_labels = {
        "breaking": "速報",
        "comeback": "カムバック",
        "ranking": "ランキング",
    }

    body_prefix = category_labels.get(category, "ニュース")
    # タイトルから本文を生成（短縮版）
    body = f"【{body_prefix}】{title[:50]}"

    payload = {
        "title": "K-POP Journal",
        "body": body,
        "url": url,
        "icon": defaults.get("icon", "/wp-content/uploads/kpopjournal-icon-192.png"),
        "badge": defaults.get("badge", "/wp-content/uploads/kpopjournal-badge-72.png"),
        "tag": f"kpopjournal-{category}",
        "renotify": True,
        "requireInteraction": category == "breaking",
    }

    if image_url:
        payload["image"] = image_url

    return payload


# ── Web Push送信 ──

def send_notifications(payload: dict, creds: dict, config: dict,
                        dry_run: bool = False) -> dict:
    """全購読者へWebプッシュ通知を送信"""
    subscriptions = load_subscriptions()
    total = len(subscriptions)

    if total == 0:
        return {"total": 0, "sent": 0, "failed": 0, "expired": 0}

    if dry_run:
        print(f"  [DRY-RUN] {total}件の購読者へ送信予定")
        return {"total": total, "sent": 0, "failed": 0, "expired": 0, "dry_run": True}

    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        print("❌ pywebpush が未インストール: pip install pywebpush", file=sys.stderr)
        return {"total": total, "sent": 0, "failed": total, "expired": 0,
                "error": "pywebpush not installed"}

    ttl = config.get("push_rules", {}).get("ttl_seconds", 86400)
    urgency = config.get("push_rules", {}).get("urgency", "normal")
    payload_json = json.dumps(payload, ensure_ascii=False)

    stats = {"total": total, "sent": 0, "failed": 0, "expired": 0}
    expired_endpoints = []

    for i, sub in enumerate(subscriptions):
        try:
            webpush(
                subscription_info=sub,
                data=payload_json,
                vapid_private_key=creds["private_key"],
                vapid_claims={"sub": creds["claims_email"]},
                ttl=ttl,
            )
            stats["sent"] += 1
        except WebPushException as e:
            if "410" in str(e) or "404" in str(e):
                # 購読期限切れ → 除去対象
                stats["expired"] += 1
                expired_endpoints.append(sub.get("endpoint", ""))
            else:
                stats["failed"] += 1
                if stats["failed"] <= 3:
                    print(f"  ⚠️ 送信失敗 [{i+1}/{total}]: {str(e)[:100]}", file=sys.stderr)
        except Exception as e:
            stats["failed"] += 1

        # バッチ間の小休止（APIレート対策）
        if (i + 1) % BATCH_SIZE == 0 and i + 1 < total:
            time.sleep(1)

    # 期限切れ購読を除去
    for ep in expired_endpoints:
        remove_subscription(ep)
    if expired_endpoints:
        print(f"  🗑️ 期限切れ購読 {len(expired_endpoints)}件を除去", file=sys.stderr)

    return stats


# ── メイン ──

def main():
    parser = argparse.ArgumentParser(description="Webプッシュ通知 v1.0")
    parser.add_argument("--title", default="", help="記事タイトル")
    parser.add_argument("--url", default="", help="記事URL")
    parser.add_argument("--image", default="", help="サムネイル画像URL")
    parser.add_argument("--category", default="breaking", help="記事カテゴリ")
    parser.add_argument("--validate", action="store_true", help="credential検証のみ")
    parser.add_argument("--dry-run", action="store_true", help="送信せずプレビュー")
    parser.add_argument("--stats", action="store_true", help="購読者統計")
    parser.add_argument("--force", action="store_true", help="制限を無視")
    args = parser.parse_args()

    config = load_config()
    creds, cred_errors = load_credentials()

    if args.stats:
        subs = load_subscriptions()
        print(f"Webプッシュ購読者: {len(subs)}件")
        sys.exit(0)

    if args.validate:
        if cred_errors:
            print("❌ WebPush VAPID検証: 問題あり")
            for err in cred_errors:
                print(f"  {err}")
            sys.exit(1)
        subs = load_subscriptions()
        print("✅ WebPush VAPID検証: 正常")
        print(f"  購読者数: {len(subs)}")
        sys.exit(0)

    if not args.title or not args.url:
        print("Usage: python3 lib/webpush_notifier.py --title '...' --url '...'")
        sys.exit(1)

    if cred_errors:
        print("❌ WebPush VAPID検証失敗:", file=sys.stderr)
        for err in cred_errors:
            print(f"  {err}", file=sys.stderr)
        sys.exit(1)

    # ガード
    if not args.force:
        if not _should_push(args.category, config):
            print(f"⏭️ カテゴリ '{args.category}' はWebプッシュ対象外")
            sys.exit(0)
        if _is_quiet_hours(config):
            print("⏭️ 静粛時間帯のため配信スキップ")
            sys.exit(0)
        allowed, reason = _check_daily_limit(config)
        if not allowed:
            print(f"⏭️ {reason}")
            sys.exit(0)

    # ペイロード構築
    payload = build_payload(args.title, args.url, args.image, args.category, config)

    if args.dry_run:
        subs = load_subscriptions()
        print("\n[DRY-RUN] Webプッシュ通知プレビュー")
        print(f"  購読者数: {len(subs)}")
        print(f"  ペイロード:")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        sys.exit(0)

    # 送信
    stats = send_notifications(payload, creds, config)
    print(f"✅ Webプッシュ配信完了")
    print(f"  対象: {stats['total']}件 / 成功: {stats['sent']}件 / 失敗: {stats['failed']}件 / 期限切れ: {stats['expired']}件")

    _log({
        "timestamp": datetime.now(JST).isoformat(),
        "title": args.title[:80], "url": args.url,
        "category": args.category,
        "result": "sent" if stats["sent"] > 0 else "failed",
        "stats": stats,
    })

    if stats["sent"] == 0 and stats["total"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
