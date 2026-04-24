#!/usr/bin/env python3
"""
Instagram自動投稿（Graph API）v1.0
- サムネイル画像をInstagram用にリサイズ・投稿
- キャプション自動生成（記事タイトル＋ハッシュタグ）
- アーティスト検出による動的ハッシュタグ選択
- 投稿履歴・重複防止・レートリミット対応

Usage:
  python3 lib/post_to_instagram.py --title "タイトル" --url "記事URL" --image "thumbnail.jpg"
  python3 lib/post_to_instagram.py --title "タイトル" --url "記事URL" --image "thumbnail.jpg" --category breaking
  python3 lib/post_to_instagram.py --validate   # credential検証のみ
  python3 lib/post_to_instagram.py --dry-run --title "..." --url "..." --image "..."

前提:
  ~/.instagram_credentials に以下のJSON:
  {
    "access_token": "長期アクセストークン",
    "instagram_account_id": "17841400000000000",
    "facebook_page_id": "100000000000000"
  }

  アクセストークン取得手順:
  1. Meta for Developers → アプリ作成 → Instagram Graph API を追加
  2. instagram_basic, instagram_content_publish, pages_read_engagement 権限を取得
  3. 短期トークンを長期トークンに交換（60日有効）
  4. ~/.instagram_credentials に保存（chmod 600）
"""
import json
import sys
import os
import re
import time
import argparse
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
LOGS_DIR = BASE_DIR / "logs"
CONFIG_PATH = BASE_DIR / "config" / "sns_config.json"
CREDS_FILE = Path(os.path.expanduser("~/.instagram_credentials"))
HISTORY_LOG = LOGS_DIR / "instagram_post_history.jsonl"
RETRY_LOG = LOGS_DIR / "instagram_retry_log.jsonl"

JST = timezone(timedelta(hours=9))

MAX_RETRIES = 3
BASE_DELAY = 5
MAX_DELAY = 60


# ── 設定読み込み ──

def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        full = json.loads(CONFIG_PATH.read_text())
        return full.get("instagram", {})
    except Exception:
        return {}


def load_credentials() -> tuple[dict | None, list[str]]:
    errors = []
    if not CREDS_FILE.exists():
        errors.append(f"CRED_MISSING: {CREDS_FILE} が見つかりません")
        errors.append("  修復: ~/.instagram_credentials にJSON形式で保存してください")
        errors.append('  {"access_token":"...","instagram_account_id":"...","facebook_page_id":"..."}')
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

    for key in ["access_token", "instagram_account_id"]:
        val = creds.get(key, "")
        if not val:
            errors.append(f"CRED_KEY_EMPTY: '{key}' が未設定または空です")
        elif len(str(val).strip()) < 5:
            errors.append(f"CRED_KEY_SHORT: '{key}' が短すぎます")

    if errors:
        return None, errors
    return creds, []


# ── ログ記録 ──

def _log(path: Path, entry: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _log_history(title: str, url: str, ig_id: str, result: str, detail: str = ""):
    _log(HISTORY_LOG, {
        "timestamp": datetime.now(JST).isoformat(),
        "title": title[:80],
        "url": url,
        "instagram_id": ig_id,
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
            if rec.get("url") == url and rec.get("result") == "published":
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

def _check_rate_limit(config: dict) -> tuple[bool, str]:
    max_daily = config.get("posting_rules", {}).get("max_daily_posts", 3)
    min_interval = config.get("posting_rules", {}).get("min_interval_minutes", 120)

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
            if rec.get("result") != "published":
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
        return False, f"本日の投稿上限（{max_daily}件）に到達"

    if last_post_time:
        elapsed = (now - last_post_time).total_seconds() / 60
        if elapsed < min_interval:
            return False, f"最小投稿間隔（{min_interval}分）未満（経過: {elapsed:.0f}分）"

    return True, ""


# ── アーティスト検出・ハッシュタグ生成 ──

def detect_artists(title: str, config: dict) -> list[str]:
    artist_tags = config.get("hashtag_groups", {}).get("artist_specific", {})
    found = []
    title_lower = title.lower()
    for artist, tags in artist_tags.items():
        if artist.lower() in title_lower:
            found.extend(tags)
    return found


def build_hashtags(title: str, category: str, config: dict) -> list[str]:
    hg = config.get("hashtag_groups", {})
    optimal = config.get("posting_rules", {}).get("optimal_hashtags", 15)

    tags = list(hg.get("base", []))
    tags.extend(hg.get(category, []))
    tags.extend(detect_artists(title, config))

    # 重複除去（大文字小文字を区別しない）
    seen = set()
    unique = []
    for t in tags:
        key = t.lower().replace(" ", "").replace("_", "")
        if key not in seen:
            seen.add(key)
            unique.append(t)

    return [f"#{t}" for t in unique[:optimal]]


def build_caption(title: str, url: str, category: str, config: dict) -> str:
    max_chars = config.get("posting_rules", {}).get("caption_max_chars", 2200)

    hashtags = build_hashtags(title, category, config)
    hashtag_block = " ".join(hashtags)

    caption = (
        f"{title}\n"
        f"\n"
        f"詳しくはプロフィールのリンクから\n"
        f"@kpopjournal.tokyo\n"
        f"\n"
        f"{'.' * 5}\n"
        f"\n"
        f"{hashtag_block}"
    )

    if len(caption) > max_chars:
        caption = caption[:max_chars - 3] + "..."

    return caption


# ── Instagram Graph API 投稿 ──

def _api_request(url: str, data: dict | None = None, method: str = "GET") -> dict:
    if data:
        payload = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(url, data=payload, method=method)
        req.add_header("Content-Type", "application/json")
    else:
        req = urllib.request.Request(url, method=method)

    with urllib.request.urlopen(req, timeout=30) as res:
        return json.loads(res.read())


def upload_image_and_publish(image_url: str, caption: str, creds: dict,
                              config: dict) -> tuple[str, int]:
    """
    Instagram Graph API 2段階投稿:
    1. メディアコンテナ作成（画像URL指定）
    2. コンテナをパブリッシュ

    image_url: 公開アクセス可能な画像URL（WPメディアライブラリ等）
    """
    api_ver = config.get("api_version", "v19.0")
    ig_id = creds["instagram_account_id"]
    token = creds["access_token"]
    base = f"https://graph.facebook.com/{api_ver}/{ig_id}"

    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            # Step 1: メディアコンテナ作成
            container_url = (
                f"{base}/media"
                f"?image_url={urllib.parse.quote(image_url, safe='')}"
                f"&caption={urllib.parse.quote(caption, safe='')}"
                f"&access_token={token}"
            )
            container = _api_request(container_url, method="POST")
            creation_id = container.get("id")
            if not creation_id:
                raise RuntimeError(f"コンテナ作成失敗: {container}")

            # Step 2: パブリッシュ（コンテナが処理完了するまで最大30秒待機）
            for _ in range(6):
                time.sleep(5)
                status_url = f"https://graph.facebook.com/{api_ver}/{creation_id}?fields=status_code&access_token={token}"
                status = _api_request(status_url)
                if status.get("status_code") == "FINISHED":
                    break
            else:
                print(f"  ⚠️ コンテナ処理タイムアウト（続行試行）", file=sys.stderr)

            publish_url = (
                f"{base}/media_publish"
                f"?creation_id={creation_id}"
                f"&access_token={token}"
            )
            result = _api_request(publish_url, method="POST")
            ig_media_id = result.get("id", "")

            if attempt > 1:
                _log(RETRY_LOG, {
                    "timestamp": datetime.now(JST).isoformat(),
                    "attempt": attempt, "status": "success",
                })
            return ig_media_id, attempt

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

            # 認証エラーはリトライしない
            if e.code in (400, 401, 403):
                print(f"❌ Instagram API エラー (HTTP {e.code}): {resp_body[:300]}", file=sys.stderr)
                raise

            if attempt < MAX_RETRIES:
                delay = min(BASE_DELAY * (2 ** (attempt - 1)), MAX_DELAY)
                print(f"  ⏳ リトライ {attempt}/{MAX_RETRIES}: HTTP {e.code} → {delay:.0f}秒待機", file=sys.stderr)
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


# ── メイン ──

def main():
    parser = argparse.ArgumentParser(description="Instagram自動投稿 v1.0")
    parser.add_argument("--title", default="", help="記事タイトル")
    parser.add_argument("--url", default="", help="記事URL")
    parser.add_argument("--image", default="", help="サムネイル画像の公開URL")
    parser.add_argument("--category", default="default", help="記事カテゴリ")
    parser.add_argument("--validate", action="store_true", help="credential検証のみ")
    parser.add_argument("--dry-run", action="store_true", help="投稿せずプレビュー")
    args = parser.parse_args()

    config = load_config()
    creds, cred_errors = load_credentials()

    if args.validate:
        if cred_errors:
            print("❌ Instagram credential検証: 問題あり")
            for err in cred_errors:
                print(f"  {err}")
            sys.exit(1)
        print("✅ Instagram credential検証: 正常")
        print(f"  account_id: {creds['instagram_account_id']}")
        sys.exit(0)

    if not args.title or not args.image:
        print("Usage: python3 lib/post_to_instagram.py --title '...' --url '...' --image '...'")
        sys.exit(1)

    if cred_errors:
        print("❌ Instagram credential検証失敗:", file=sys.stderr)
        for err in cred_errors:
            print(f"  {err}", file=sys.stderr)
        sys.exit(1)

    # 重複チェック
    if args.url and _is_duplicate(args.url):
        print(f"⏭️ 重複スキップ: {args.url} は48時間以内に投稿済み")
        sys.exit(0)

    # レートリミット
    allowed, reason = _check_rate_limit(config)
    if not allowed:
        print(f"⏭️ レートリミット: {reason}")
        sys.exit(0)

    # キャプション生成
    caption = build_caption(args.title, args.url, args.category, config)

    if args.dry_run:
        print("\n[DRY-RUN] Instagram投稿プレビュー")
        print(f"  画像: {args.image}")
        print(f"  キャプション:\n{caption}")
        print(f"  文字数: {len(caption)}")
        sys.exit(0)

    # 投稿
    try:
        ig_id, attempts = upload_image_and_publish(args.image, caption, creds, config)
        retry_note = f" (リトライ{attempts}回目)" if attempts > 1 else ""
        print(f"✅ Instagram投稿成功{retry_note}")
        print(f"  media_id: {ig_id}")
        print(f"INSTAGRAM_ID={ig_id}")
        _log_history(args.title, args.url, ig_id, "published")
    except Exception as e:
        print(f"❌ Instagram投稿失敗: {e}", file=sys.stderr)
        _log_history(args.title, args.url, "", "failed", str(e)[:200])
        sys.exit(1)


if __name__ == "__main__":
    main()
