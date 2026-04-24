#!/usr/bin/env python3
"""
LINE Messaging API自動投稿 v1.0
- Flex Messageでリッチなニュース通知をブロードキャスト配信
- 画像・タイトル・リンクボタン付きカード形式
- 投稿履歴・重複防止・レートリミット・静寂時間対応

Usage:
  python3 lib/post_to_line.py --title "タイトル" --url "記事URL" --image "thumbnail.jpg"
  python3 lib/post_to_line.py --title "タイトル" --url "記事URL" --image "thumbnail.jpg" --category breaking
  python3 lib/post_to_line.py --validate   # credential検証のみ
  python3 lib/post_to_line.py --dry-run --title "..." --url "..." --image "..."

前提:
  ~/.line_credentials に以下のJSON:
  {
    "channel_access_token": "長期チャネルアクセストークン",
    "channel_secret": "チャネルシークレット"
  }

  トークン取得手順:
  1. LINE Developers → Messaging APIチャネル作成
  2. チャネルアクセストークン（長期）を発行
  3. ~/.line_credentials に保存（chmod 600）
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
HISTORY_LOG = LOGS_DIR / "line_post_history.jsonl"
RETRY_LOG = LOGS_DIR / "line_retry_log.jsonl"

JST = timezone(timedelta(hours=9))

BROADCAST_URL = "https://api.line.me/v2/bot/message/broadcast"

MAX_RETRIES = 3
BASE_DELAY = 5
MAX_DELAY = 60


# ── 設定読み込み ──

def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        full = json.loads(CONFIG_PATH.read_text())
        return full.get("line", {})
    except Exception:
        return {}


def load_credentials() -> tuple:
    """Returns (creds_dict | None, error_list)."""
    errors = []
    if not CREDS_FILE.exists():
        errors.append(f"CRED_MISSING: {CREDS_FILE} が見つかりません")
        errors.append("  修復: ~/.line_credentials にJSON形式で保存してください")
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

    for key in ["channel_access_token", "channel_secret"]:
        val = creds.get(key, "")
        if not val:
            errors.append(f"CRED_KEY_EMPTY: '{key}' が未設定または空です")
        elif len(str(val).strip()) < 10:
            errors.append(f"CRED_KEY_SHORT: '{key}' が短すぎます")

    if errors:
        return None, errors
    return creds, []


# ── ログ記録 ──

def _log(path: Path, entry: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _log_history(title: str, url: str, result: str, detail: str = ""):
    _log(HISTORY_LOG, {
        "timestamp": datetime.now(JST).isoformat(),
        "title": title[:80],
        "url": url,
        "result": result,
        "detail": detail,
    })


# ── 重複チェック ──

def _is_duplicate(url: str) -> bool:
    if not HISTORY_LOG.exists():
        return False
    cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
    for line in HISTORY_LOG.read_text().strip().split("\n"):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
            if rec.get("url") == url and rec.get("result") == "broadcast":
                ts = rec.get("timestamp", "").replace("Z", "+00:00")
                posted_at = datetime.fromisoformat(ts)
                if posted_at.tzinfo is None:
                    posted_at = posted_at.replace(tzinfo=JST)
                if posted_at >= cutoff:
                    return True
        except Exception:
            continue
    return False


# ── レートリミットチェック ──

def _check_rate_limit(config: dict) -> tuple:
    """Returns (allowed: bool, reason: str)."""
    rules = config.get("push_rules", {})
    max_daily = rules.get("max_daily_pushes", 5)
    min_interval = rules.get("min_interval_minutes", 60)

    if not HISTORY_LOG.exists():
        return True, ""

    now = datetime.now(JST)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_count = 0
    last_post_time = None

    for line in HISTORY_LOG.read_text().strip().split("\n"):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
            if rec.get("result") != "broadcast":
                continue
            ts = datetime.fromisoformat(rec["timestamp"].replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=JST)
            if ts >= today_start:
                today_count += 1
            if last_post_time is None or ts > last_post_time:
                last_post_time = ts
        except Exception:
            continue

    if today_count >= max_daily:
        return False, f"本日の配信上限（{max_daily}件）に到達"

    if last_post_time:
        elapsed = (now - last_post_time).total_seconds() / 60
        if elapsed < min_interval:
            return False, f"最小配信間隔（{min_interval}分）未満（経過: {elapsed:.0f}分）"

    return True, ""


# ── 静寂時間チェック ──

def _is_quiet_hours(config: dict) -> tuple:
    """Returns (is_quiet: bool, reason: str)."""
    rules = config.get("push_rules", {})
    quiet = rules.get("quiet_hours", {})
    start_str = quiet.get("start", "23:00")
    end_str = quiet.get("end", "07:00")

    now = datetime.now(JST)
    current_minutes = now.hour * 60 + now.minute

    start_parts = start_str.split(":")
    start_minutes = int(start_parts[0]) * 60 + int(start_parts[1])
    end_parts = end_str.split(":")
    end_minutes = int(end_parts[0]) * 60 + int(end_parts[1])

    # Handle overnight quiet hours (e.g., 23:00 - 07:00)
    if start_minutes > end_minutes:
        is_quiet = current_minutes >= start_minutes or current_minutes < end_minutes
    else:
        is_quiet = start_minutes <= current_minutes < end_minutes

    if is_quiet:
        return True, f"静寂時間帯（{start_str}〜{end_str} JST）のため配信スキップ"
    return False, ""


# ── Flex Message構築 ──

def _build_flex_message(title: str, url: str, image_url: str,
                        category: str, config: dict) -> dict:
    """LINE Flex Messageカード形式を構築する。"""
    max_chars = config.get("push_rules", {}).get("message_max_chars", 500)

    # カテゴリラベル
    category_labels = {
        "breaking": "BREAKING",
        "comeback": "COMEBACK",
        "ranking": "RANKING",
        "beauty": "BEAUTY",
        "analysis": "ANALYSIS",
        "default": "NEWS",
    }
    cat_label = category_labels.get(category, "NEWS")

    # カテゴリごとの色
    category_colors = {
        "breaking": "#FF3B30",
        "comeback": "#AF52DE",
        "ranking": "#FF9500",
        "beauty": "#FF2D55",
        "analysis": "#007AFF",
        "default": "#34C759",
    }
    cat_color = category_colors.get(category, "#34C759")

    # タイトルを制限
    display_title = title[:max_chars] if len(title) > max_chars else title

    # Flex Message bubble
    bubble = {
        "type": "bubble",
        "size": "mega",
        "hero": {
            "type": "image",
            "url": image_url,
            "size": "full",
            "aspectRatio": "20:13",
            "aspectMode": "cover",
            "action": {
                "type": "uri",
                "label": "記事を読む",
                "uri": url,
            },
        },
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
                            "text": cat_label,
                            "size": "xs",
                            "color": "#FFFFFF",
                            "weight": "bold",
                            "align": "center",
                        },
                    ],
                    "backgroundColor": cat_color,
                    "cornerRadius": "md",
                    "paddingAll": "4px",
                    "paddingStart": "8px",
                    "paddingEnd": "8px",
                    "width": "80px",
                },
                {
                    "type": "text",
                    "text": display_title,
                    "weight": "bold",
                    "size": "lg",
                    "wrap": True,
                    "margin": "md",
                },
                {
                    "type": "text",
                    "text": "K-POP Journal",
                    "size": "xs",
                    "color": "#999999",
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
                    "style": "primary",
                    "color": "#905CF5",
                    "action": {
                        "type": "uri",
                        "label": "記事を読む",
                        "uri": url,
                    },
                },
            ],
            "spacing": "sm",
        },
    }

    return {
        "type": "flex",
        "altText": f"[{cat_label}] {display_title}",
        "contents": bubble,
    }


# ── LINE Messaging API ブロードキャスト ──

def _broadcast_message(message: dict, creds: dict) -> tuple:
    """
    LINE Messaging API v2 broadcast endpoint.
    Returns (success: bool, attempts: int).
    """
    token = creds["channel_access_token"]
    payload = json.dumps({"messages": [message]}).encode("utf-8")

    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(
                BROADCAST_URL,
                data=payload,
                method="POST",
            )
            req.add_header("Content-Type", "application/json")
            req.add_header("Authorization", f"Bearer {token}")

            with urllib.request.urlopen(req, timeout=30) as res:
                # broadcast returns 200 with empty body on success
                _ = res.read()

            if attempt > 1:
                _log(RETRY_LOG, {
                    "timestamp": datetime.now(JST).isoformat(),
                    "attempt": attempt, "status": "success",
                })
            return True, attempt

        except urllib.error.HTTPError as e:
            resp_body = ""
            try:
                resp_body = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass

            _log(RETRY_LOG, {
                "timestamp": datetime.now(JST).isoformat(),
                "attempt": attempt, "status_code": e.code,
                "error": resp_body[:300],
            })

            # 認証・権限エラーはリトライしない
            if e.code in (400, 401, 403):
                print(f"LINE API エラー (HTTP {e.code}): {resp_body[:300]}",
                      file=sys.stderr)
                raise

            if attempt < MAX_RETRIES:
                delay = min(BASE_DELAY * (2 ** (attempt - 1)), MAX_DELAY)
                print(f"  リトライ {attempt}/{MAX_RETRIES}: HTTP {e.code} "
                      f"-> {delay:.0f}秒待機", file=sys.stderr)
                time.sleep(delay)
            else:
                last_error = e

        except Exception as e:
            _log(RETRY_LOG, {
                "timestamp": datetime.now(JST).isoformat(),
                "attempt": attempt, "error": str(e)[:200],
            })
            if attempt < MAX_RETRIES:
                delay = min(BASE_DELAY * (2 ** (attempt - 1)), MAX_DELAY)
                time.sleep(delay)
            else:
                last_error = e

    if last_error:
        raise RuntimeError(f"全{MAX_RETRIES}回リトライ失敗: {last_error}")
    return False, MAX_RETRIES


# ── メイン ──

def main():
    parser = argparse.ArgumentParser(description="LINE Messaging API自動投稿 v1.0")
    parser.add_argument("--title", default="", help="記事タイトル")
    parser.add_argument("--url", default="", help="記事URL")
    parser.add_argument("--image", default="", help="サムネイル画像の公開URL")
    parser.add_argument("--category", default="default", help="記事カテゴリ")
    parser.add_argument("--validate", action="store_true", help="credential検証のみ")
    parser.add_argument("--dry-run", action="store_true", help="配信せずプレビュー")
    args = parser.parse_args()

    config = load_config()
    creds, cred_errors = load_credentials()

    # ── --validate モード ──
    if args.validate:
        if cred_errors:
            print("LINE credential検証: 問題あり")
            for err in cred_errors:
                print(f"  {err}")
            sys.exit(1)
        print("LINE credential検証: 正常")
        print(f"  channel_secret: {creds['channel_secret'][:8]}...")
        sys.exit(0)

    # ── 引数チェック ──
    if not args.title or not args.url:
        print("Usage: python3 lib/post_to_line.py --title '...' --url '...' "
              "[--image '...'] [--category breaking]")
        sys.exit(1)

    # ── credential不備は graceful skip ──
    if cred_errors:
        print("LINE credential未設定 — スキップ", file=sys.stderr)
        for err in cred_errors:
            print(f"  {err}", file=sys.stderr)
        sys.exit(0)

    # ── 重複チェック ──
    if _is_duplicate(args.url):
        print(f"重複スキップ: {args.url} は48時間以内に配信済み")
        sys.exit(0)

    # ── 静寂時間チェック ──
    quiet, quiet_reason = _is_quiet_hours(config)
    if quiet:
        print(f"静寂時間スキップ: {quiet_reason}")
        _log_history(args.title, args.url, "skipped_quiet", quiet_reason)
        sys.exit(0)

    # ── レートリミット（graceful skip） ──
    allowed, reason = _check_rate_limit(config)
    if not allowed:
        print(f"レートリミット: {reason}")
        _log_history(args.title, args.url, "skipped_rate", reason)
        sys.exit(0)

    # ── Flex Message構築 ──
    image_url = args.image or ""
    if image_url:
        message = _build_flex_message(
            args.title, args.url, image_url, args.category, config)
    else:
        # 画像なしの場合はシンプルテキスト＋ボタン
        message = _build_flex_message_text_only(
            args.title, args.url, args.category, config)

    # ── dry-run ──
    if args.dry_run:
        print("\n[DRY-RUN] LINE配信プレビュー")
        print(f"  タイトル: {args.title}")
        print(f"  URL: {args.url}")
        print(f"  画像: {image_url or '(なし)'}")
        print(f"  カテゴリ: {args.category}")
        print(f"  altText: {message.get('altText', '')}")
        print(f"  メッセージJSON:")
        print(json.dumps(message, ensure_ascii=False, indent=2))
        sys.exit(0)

    # ── ブロードキャスト配信 ──
    try:
        success, attempts = _broadcast_message(message, creds)
        retry_note = f" (リトライ{attempts}回目)" if attempts > 1 else ""
        print(f"LINE配信成功{retry_note}")
        print(f"  タイトル: {args.title[:60]}")
        print(f"LINE_BROADCAST=ok")
        _log_history(args.title, args.url, "broadcast")
    except Exception as e:
        print(f"LINE配信失敗: {e}", file=sys.stderr)
        _log_history(args.title, args.url, "failed", str(e)[:200])
        sys.exit(1)


def _build_flex_message_text_only(title: str, url: str,
                                   category: str, config: dict) -> dict:
    """画像なしの場合のFlex Messageカード。"""
    max_chars = config.get("push_rules", {}).get("message_max_chars", 500)

    category_labels = {
        "breaking": "BREAKING",
        "comeback": "COMEBACK",
        "ranking": "RANKING",
        "beauty": "BEAUTY",
        "analysis": "ANALYSIS",
        "default": "NEWS",
    }
    cat_label = category_labels.get(category, "NEWS")

    category_colors = {
        "breaking": "#FF3B30",
        "comeback": "#AF52DE",
        "ranking": "#FF9500",
        "beauty": "#FF2D55",
        "analysis": "#007AFF",
        "default": "#34C759",
    }
    cat_color = category_colors.get(category, "#34C759")

    display_title = title[:max_chars] if len(title) > max_chars else title

    bubble = {
        "type": "bubble",
        "size": "mega",
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
                            "text": cat_label,
                            "size": "xs",
                            "color": "#FFFFFF",
                            "weight": "bold",
                            "align": "center",
                        },
                    ],
                    "backgroundColor": cat_color,
                    "cornerRadius": "md",
                    "paddingAll": "4px",
                    "paddingStart": "8px",
                    "paddingEnd": "8px",
                    "width": "80px",
                },
                {
                    "type": "text",
                    "text": display_title,
                    "weight": "bold",
                    "size": "lg",
                    "wrap": True,
                    "margin": "md",
                },
                {
                    "type": "text",
                    "text": "K-POP Journal",
                    "size": "xs",
                    "color": "#999999",
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
                    "style": "primary",
                    "color": "#905CF5",
                    "action": {
                        "type": "uri",
                        "label": "記事を読む",
                        "uri": url,
                    },
                },
            ],
            "spacing": "sm",
        },
    }

    return {
        "type": "flex",
        "altText": f"[{cat_label}] {display_title}",
        "contents": bubble,
    }


if __name__ == "__main__":
    main()
