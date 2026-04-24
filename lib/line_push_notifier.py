#!/usr/bin/env python3
"""
LINE Messaging API プッシュ通知 v1.0
- 速報・カムバック記事をLINE公式アカウント登録者へ即配信
- Flex Messageでリッチなカード型通知
- 静粛時間帯・レートリミット・重複防止

Usage:
  python3 lib/line_push_notifier.py --title "タイトル" --url "記事URL" --category breaking
  python3 lib/line_push_notifier.py --title "タイトル" --url "記事URL" --image "サムネURL"
  python3 lib/line_push_notifier.py --validate
  python3 lib/line_push_notifier.py --dry-run --title "..." --url "..."

前提:
  ~/.line_credentials に以下のJSON:
  {
    "channel_access_token": "長期チャネルアクセストークン",
    "channel_secret": "チャネルシークレット"
  }

  LINE公式アカウント設定手順:
  1. LINE Developers Console → プロバイダー → チャネル作成（Messaging API）
  2. Messaging API設定 → チャネルアクセストークン（長期）を発行
  3. ~/.line_credentials に保存（chmod 600）
  4. Webhook URL を設定（友だち追加・ブロック管理用）
"""
import json
import sys
import os
import time
import argparse
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
LOGS_DIR = BASE_DIR / "logs"
CONFIG_PATH = BASE_DIR / "config" / "sns_config.json"
CREDS_FILE = Path(os.path.expanduser("~/.line_credentials"))
HISTORY_LOG = LOGS_DIR / "line_push_history.jsonl"

JST = timezone(timedelta(hours=9))

LINE_BROADCAST_URL = "https://api.line.me/v2/bot/message/broadcast"
LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"
LINE_QUOTA_URL = "https://api.line.me/v2/bot/message/quota/consumption"

MAX_RETRIES = 3
BASE_DELAY = 5


# ── 設定・認証 ──

def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        full = json.loads(CONFIG_PATH.read_text())
        return full.get("line", {})
    except Exception:
        return {}


def load_credentials() -> tuple[dict | None, list[str]]:
    errors = []
    if not CREDS_FILE.exists():
        errors.append(f"CRED_MISSING: {CREDS_FILE} が見つかりません")
        errors.append('  {"channel_access_token":"...","channel_secret":"..."}')
        return None, errors

    stat = os.stat(CREDS_FILE)
    mode = oct(stat.st_mode)[-3:]
    if mode not in ("600", "400"):
        errors.append(f"CRED_PERMISSION: パーミッション {mode} — 推奨は 600")

    try:
        creds = json.loads(CREDS_FILE.read_text())
    except json.JSONDecodeError as e:
        errors.append(f"CRED_JSON_INVALID: JSONパースエラー — {e}")
        return None, errors

    for key in ["channel_access_token"]:
        if not creds.get(key, ""):
            errors.append(f"CRED_KEY_EMPTY: '{key}' が未設定")

    if errors:
        return None, errors
    return creds, []


# ── ログ ──

def _log(entry: dict):
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ── ガード ──

def _is_quiet_hours(config: dict) -> bool:
    rules = config.get("push_rules", {})
    quiet = rules.get("quiet_hours", {})
    if not quiet:
        return False

    now = datetime.now(JST)
    start_h, start_m = map(int, quiet.get("start", "23:00").split(":"))
    end_h, end_m = map(int, quiet.get("end", "07:00").split(":"))
    current = now.hour * 60 + now.minute
    start = start_h * 60 + start_m
    end = end_h * 60 + end_m

    if start > end:  # 23:00 - 07:00 のような深夜跨ぎ
        return current >= start or current < end
    return start <= current < end


def _is_duplicate(url: str) -> bool:
    if not HISTORY_LOG.exists():
        return False
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    for line in HISTORY_LOG.read_text().strip().split("\n"):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
            if rec.get("url") == url and rec.get("result") == "sent":
                ts = datetime.fromisoformat(rec["timestamp"].replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=JST)
                if ts >= cutoff:
                    return True
        except Exception:
            continue
    return False


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


def _should_push(category: str, config: dict) -> bool:
    triggers = config.get("push_rules", {}).get("trigger_categories", ["breaking", "comeback"])
    return category in triggers


# ── Flex Message構築 ──

def build_flex_message(title: str, url: str, image_url: str = "",
                        category: str = "breaking") -> dict:
    """LINE Flex Messageでリッチカード型通知を構築"""
    category_labels = {
        "breaking": "速報",
        "comeback": "カムバ",
        "ranking": "ランキング",
        "beauty": "ビューティー",
    }
    label = category_labels.get(category, "ニュース")
    label_color = {
        "breaking": "#FF3B30",
        "comeback": "#FF9500",
        "ranking": "#5856D6",
        "beauty": "#FF2D55",
    }.get(category, "#007AFF")

    hero = None
    if image_url:
        hero = {
            "type": "image",
            "url": image_url,
            "size": "full",
            "aspectRatio": "20:13",
            "aspectMode": "cover",
            "action": {"type": "uri", "uri": url},
        }

    bubble = {
        "type": "bubble",
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "box",
                    "layout": "horizontal",
                    "contents": [
                        {
                            "type": "text",
                            "text": f"K-POP Journal | {label}",
                            "size": "xs",
                            "color": label_color,
                            "weight": "bold",
                        }
                    ],
                },
                {
                    "type": "text",
                    "text": title[:60],
                    "weight": "bold",
                    "size": "md",
                    "wrap": True,
                    "margin": "md",
                },
            ],
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "button",
                    "action": {
                        "type": "uri",
                        "label": "記事を読む",
                        "uri": url,
                    },
                    "style": "primary",
                    "color": "#1a1a2e",
                }
            ],
        },
    }

    if hero:
        bubble["hero"] = hero

    return {
        "type": "flex",
        "altText": f"【{label}】{title[:40]}",
        "contents": bubble,
    }


# ── LINE API送信 ──

def broadcast_message(message: dict, creds: dict) -> tuple[str, int]:
    """全友だちへブロードキャスト送信（リトライ付き）"""
    token = creds["channel_access_token"]
    payload = json.dumps({"messages": [message]}).encode("utf-8")

    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(
                LINE_BROADCAST_URL,
                data=payload,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as res:
                if res.status in (200, 202):
                    return "sent", attempt
                return f"http_{res.status}", attempt

        except urllib.error.HTTPError as e:
            resp_body = ""
            try:
                resp_body = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass

            if e.code in (400, 401, 403):
                print(f"❌ LINE API エラー (HTTP {e.code}): {resp_body[:300]}", file=sys.stderr)
                raise

            if e.code == 429:
                delay = 60
            else:
                delay = min(BASE_DELAY * (2 ** (attempt - 1)), 60)

            if attempt < MAX_RETRIES:
                print(f"  ⏳ リトライ {attempt}/{MAX_RETRIES}: HTTP {e.code} → {delay:.0f}秒待機", file=sys.stderr)
                time.sleep(delay)
            else:
                last_error = e

        except Exception as e:
            if attempt < MAX_RETRIES:
                time.sleep(min(BASE_DELAY * (2 ** (attempt - 1)), 60))
            else:
                last_error = e

    if last_error:
        raise RuntimeError(f"全{MAX_RETRIES}回リトライ失敗: {last_error}")


# ── メイン ──

def main():
    parser = argparse.ArgumentParser(description="LINE プッシュ通知 v1.0")
    parser.add_argument("--title", default="", help="記事タイトル")
    parser.add_argument("--url", default="", help="記事URL")
    parser.add_argument("--image", default="", help="サムネイル画像URL")
    parser.add_argument("--category", default="breaking", help="記事カテゴリ")
    parser.add_argument("--validate", action="store_true", help="credential検証のみ")
    parser.add_argument("--dry-run", action="store_true", help="送信せずプレビュー")
    parser.add_argument("--force", action="store_true", help="静粛時間・カテゴリ制限を無視")
    args = parser.parse_args()

    config = load_config()
    creds, cred_errors = load_credentials()

    if args.validate:
        if cred_errors:
            print("❌ LINE credential検証: 問題あり")
            for err in cred_errors:
                print(f"  {err}")
            sys.exit(1)
        print("✅ LINE credential検証: 正常")
        sys.exit(0)

    if not args.title or not args.url:
        print("Usage: python3 lib/line_push_notifier.py --title '...' --url '...'")
        sys.exit(1)

    if cred_errors:
        print("❌ LINE credential検証失敗:", file=sys.stderr)
        for err in cred_errors:
            print(f"  {err}", file=sys.stderr)
        sys.exit(1)

    # ガードチェック
    if not args.force:
        if not _should_push(args.category, config):
            print(f"⏭️ カテゴリ '{args.category}' はLINE配信対象外")
            sys.exit(0)

        if _is_quiet_hours(config):
            print("⏭️ 静粛時間帯のため配信スキップ")
            sys.exit(0)

        if _is_duplicate(args.url):
            print(f"⏭️ 重複スキップ: {args.url} は24時間以内に配信済み")
            sys.exit(0)

        allowed, reason = _check_daily_limit(config)
        if not allowed:
            print(f"⏭️ {reason}")
            sys.exit(0)

    # メッセージ構築
    message = build_flex_message(args.title, args.url, args.image, args.category)

    if args.dry_run:
        print("\n[DRY-RUN] LINE通知プレビュー")
        print(f"  altText: {message['altText']}")
        print(f"  タイトル: {args.title}")
        print(f"  URL: {args.url}")
        print(f"  カテゴリ: {args.category}")
        print(json.dumps(message, ensure_ascii=False, indent=2))
        sys.exit(0)

    # 送信
    try:
        result, attempts = broadcast_message(message, creds)
        retry_note = f" (リトライ{attempts}回目)" if attempts > 1 else ""
        print(f"✅ LINE配信成功{retry_note}")
        _log({
            "timestamp": datetime.now(JST).isoformat(),
            "title": args.title[:80], "url": args.url,
            "category": args.category, "result": "sent",
        })
    except Exception as e:
        print(f"❌ LINE配信失敗: {e}", file=sys.stderr)
        _log({
            "timestamp": datetime.now(JST).isoformat(),
            "title": args.title[:80], "url": args.url,
            "category": args.category, "result": "failed",
            "error": str(e)[:200],
        })
        sys.exit(1)


if __name__ == "__main__":
    main()
