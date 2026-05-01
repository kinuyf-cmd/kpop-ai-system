"""
X/Twitter自動投稿（OAuth 1.0a 正規API版）v2.0
- credential自動検証・診断
- 指数バックオフ付きリトライ（最大3回）
- HTTPステータス別ハンドリング（401/403/429/5xx）
- リトライログ記録

Usage:
  python3 post_to_x.py "投稿テキスト"
  python3 post_to_x.py "投稿テキスト" --reply-to TWEET_ID
  python3 post_to_x.py "投稿テキスト" --alt-text "画像ALTテキスト"
  python3 post_to_x.py --validate          # credential検証のみ

Output:
  ✅ X投稿成功: https://x.com/i/status/TWEET_ID
  TWEET_ID=TWEET_ID   ← シェルスクリプトから取得用
"""
import json, sys, os, hmac, hashlib, base64, time, uuid, argparse, random
import urllib.request, urllib.error, urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path

CREDS_FILE = os.path.expanduser("~/.x_credentials")
BASE_DIR = Path(__file__).parent.parent
LOGS_DIR = BASE_DIR / "logs"
RETRY_LOG = LOGS_DIR / "x_retry_log.jsonl"
CRED_DIAG_LOG = LOGS_DIR / "x_credential_diag.jsonl"

JST = timezone(timedelta(hours=9))

# ── リトライ設定 ──
MAX_RETRIES = 3
BASE_DELAY = 5       # 秒
MAX_DELAY = 60
# リトライ対象HTTPステータス
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
# リトライ不可（credential問題 → 即診断）
NO_RETRY_STATUS = {401, 403}


# ── credential検証 ──────────────────────────────────────────────

REQUIRED_KEYS = ["api_key", "api_secret", "access_token", "access_token_secret"]

def validate_credentials() -> tuple[dict | None, list[str]]:
    """
    credential fileを検証し、(creds_dict, errors) を返す。
    errors が空なら有効。
    """
    errors = []

    if not os.path.exists(CREDS_FILE):
        errors.append(f"CRED_MISSING: {CREDS_FILE} が見つかりません")
        errors.append("  修復: ~/.x_credentials に以下のJSON形式で保存してください:")
        errors.append('  {"api_key":"...","api_secret":"...","access_token":"...","access_token_secret":"..."}')
        return None, errors

    # ファイル権限チェック（600推奨）
    stat = os.stat(CREDS_FILE)
    mode = oct(stat.st_mode)[-3:]
    if mode not in ("600", "400"):
        errors.append(f"CRED_PERMISSION: パーミッション {mode} — 推奨は 600（chmod 600 ~/.x_credentials）")

    # JSON読み込み
    try:
        with open(CREDS_FILE) as f:
            creds = json.load(f)
    except json.JSONDecodeError as e:
        errors.append(f"CRED_JSON_INVALID: JSONパースエラー — {e}")
        return None, errors
    except Exception as e:
        errors.append(f"CRED_READ_ERROR: ファイル読み込み失敗 — {e}")
        return None, errors

    # 必須キーチェック
    for key in REQUIRED_KEYS:
        val = creds.get(key, "")
        if not val:
            errors.append(f"CRED_KEY_EMPTY: '{key}' が未設定または空です")
        elif len(str(val).strip()) < 10:
            errors.append(f"CRED_KEY_SHORT: '{key}' が短すぎます（{len(str(val))}文字） — 正しい値か確認してください")
        elif str(val).startswith("YOUR_") or str(val) == "xxx":
            errors.append(f"CRED_KEY_PLACEHOLDER: '{key}' がプレースホルダーのままです — 実際の値に置換してください")

    if errors:
        return None, errors

    return creds, []


def diagnose_http_error(status_code: int, response_body: str) -> list[str]:
    """HTTPエラーの原因を診断し、修復手順を返す"""
    diag = []
    if status_code == 401:
        diag.append("DIAG_401: OAuth認証失敗")
        if "Invalid or expired token" in response_body:
            diag.append("  原因: access_tokenが無効または期限切れ")
            diag.append("  修復: X Developer Portalで新しいAccess Tokenを再生成してください")
            diag.append("  手順: https://developer.x.com/en/portal/projects-and-apps → Keys and tokens → Regenerate")
        elif "Could not authenticate" in response_body:
            diag.append("  原因: api_key/api_secretが不正")
            diag.append("  修復: Consumer Keys (API Key & Secret) を再確認してください")
        else:
            diag.append("  原因: OAuth署名の不一致 — キーの先頭・末尾に空白がないか確認")
            diag.append("  修復: ~/.x_credentials の全キーをコピー＆ペーストし直してください")
    elif status_code == 403:
        if "duplicate" in response_body.lower():
            diag.append("DIAG_DUPLICATE: 同一内容の重複投稿")
            diag.append("  原因: 投稿テキストが既存ツイートと同一または酷似")
            diag.append("  対策: テキストにユニーク要素を追加してリトライ")
            return diag  # credential問題ではないので早期リターン
        diag.append("DIAG_403: アクセス権限不足")
        if "temporarily locked" in response_body.lower():
            diag.append("DIAG_LOCKED: アカウントが一時ロック中")
            diag.append("  原因: スパム検知による一時ロック（大量投稿・duplicate連発が原因の可能性）")
            diag.append("  修復: https://twitter.com にログインしてアカウントロックを解除してください")
            return diag
        elif "suspended" in response_body.lower():
            diag.append("  原因: アカウントが停止されている可能性")
            diag.append("  修復: X Developer Portalでアカウント状態を確認してください")
        else:
            diag.append("  原因: アプリの権限がRead & Write になっていない可能性")
            diag.append("  修復: X Developer Portal → App settings → User authentication settings → Read and write")
    elif status_code == 429:
        diag.append("DIAG_429: レートリミット")
        diag.append("  対策: 自動リトライで待機後に再送します（15分サイクル）")
    elif 500 <= status_code < 600:
        diag.append(f"DIAG_{status_code}: X APIサーバーエラー")
        diag.append("  対策: 一時的な障害の可能性 — 自動リトライで再送します")
    return diag


def _log_diag(event: str, details: list[str]):
    """credential診断ログを記録"""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(JST).isoformat(),
        "event": event,
        "details": details,
    }
    with open(CRED_DIAG_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _log_retry(attempt: int, status_code: int, message: str):
    """リトライログを記録"""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(JST).isoformat(),
        "attempt": attempt,
        "status_code": status_code,
        "message": message,
    }
    with open(RETRY_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ── OAuth 1.0a ──────────────────────────────────────────────────

def make_oauth_header(method: str, endpoint: str,
                      api_key: str, api_secret: str,
                      access_token: str, access_token_secret: str) -> str:
    """OAuth 1.0a 署名ヘッダを生成"""
    params = {
        "oauth_consumer_key":     api_key,
        "oauth_nonce":            uuid.uuid4().hex,
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp":        str(int(time.time())),
        "oauth_token":            access_token,
        "oauth_version":          "1.0",
    }
    params_string = "&".join(
        f"{urllib.parse.quote(k, safe='')}={urllib.parse.quote(v, safe='')}"
        for k, v in sorted(params.items())
    )
    base_string = f"{method}&{urllib.parse.quote(endpoint, safe='')}&{urllib.parse.quote(params_string, safe='')}"
    signing_key = f"{urllib.parse.quote(api_secret, safe='')}&{urllib.parse.quote(access_token_secret, safe='')}"
    signature = base64.b64encode(
        hmac.new(signing_key.encode(), base_string.encode(), hashlib.sha1).digest()
    ).decode()
    params["oauth_signature"] = signature
    return "OAuth " + ", ".join(
        f'{urllib.parse.quote(k, safe="")}="{urllib.parse.quote(v, safe="")}"'
        for k, v in sorted(params.items())
    )


# ── 投稿（リトライ付き）────────────────────────────────────────

def post_tweet(text: str, reply_to_id: str, creds: dict) -> tuple[str, int]:
    """
    ツイートを投稿し (tweet_id, attempt_count) を返す。
    指数バックオフ付きリトライ（最大MAX_RETRIES回）。
    リトライ不可エラー（401/403）は即座に診断結果を出力して終了。
    """
    endpoint = "https://api.twitter.com/2/tweets"
    body: dict = {"text": text}
    if reply_to_id:
        body["reply"] = {"in_reply_to_tweet_id": reply_to_id}

    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            auth_header = make_oauth_header(
                "POST", endpoint,
                creds["api_key"], creds["api_secret"],
                creds["access_token"], creds["access_token_secret"],
            )
            payload = json.dumps(body).encode()
            req = urllib.request.Request(
                endpoint,
                data=payload,
                headers={
                    "Authorization":  auth_header,
                    "Content-Type":   "application/json",
                    "User-Agent":     "KPOPJournalBot/2.0",
                },
            )
            with urllib.request.urlopen(req, timeout=30) as res:
                result = json.loads(res.read())
            tweet_id = result.get("data", {}).get("id", "")
            if attempt > 1:
                _log_retry(attempt, 200, f"成功（{attempt}回目）tweet_id={tweet_id}")
            return tweet_id, attempt

        except urllib.error.HTTPError as e:
            resp_body = ""
            try:
                resp_body = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass

            _log_retry(attempt, e.code, f"HTTP {e.code}: {resp_body[:200]}")

            # duplicate content: テキスト変更してリトライ可能
            if e.code == 403 and "duplicate" in resp_body.lower():
                diag = diagnose_http_error(e.code, resp_body)
                _log_diag("duplicate_content", diag)
                # テキストにタイムスタンプを付加して重複回避
                now_str = datetime.now(JST).strftime("%H:%M")
                body["text"] = text.rstrip() + f" ({now_str})"
                _log_retry(attempt, 403, "duplicate content → テキスト変更してリトライ")
                time.sleep(2)
                continue

            # リトライ不可: credential問題
            if e.code in NO_RETRY_STATUS:
                diag = diagnose_http_error(e.code, resp_body)
                _log_diag(f"http_{e.code}", diag)
                print(f"❌ X投稿失敗 (HTTP {e.code}): {resp_body[:300]}", file=sys.stderr)
                for line in diag:
                    print(f"  {line}", file=sys.stderr)
                raise

            # 429: レートリミット — Retry-After ヘッダを尊重
            if e.code == 429:
                retry_after = e.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    delay = min(int(retry_after), MAX_DELAY)
                else:
                    delay = min(BASE_DELAY * (2 ** (attempt - 1)), MAX_DELAY)
            elif e.code in RETRYABLE_STATUS:
                delay = min(BASE_DELAY * (2 ** (attempt - 1)), MAX_DELAY)
            else:
                # 未知の4xxはリトライしない
                print(f"❌ X投稿失敗 (HTTP {e.code}): {resp_body[:300]}", file=sys.stderr)
                raise

            # ジッター追加（0.5x〜1.5x）
            delay = delay * (0.5 + random.random())

            if attempt < MAX_RETRIES:
                print(f"  ⏳ リトライ {attempt}/{MAX_RETRIES}: HTTP {e.code} → {delay:.0f}秒待機", file=sys.stderr)
                time.sleep(delay)
            else:
                last_error = e

        except (urllib.error.URLError, TimeoutError, OSError) as e:
            _log_retry(attempt, 0, f"Network error: {e}")
            if attempt < MAX_RETRIES:
                delay = min(BASE_DELAY * (2 ** (attempt - 1)), MAX_DELAY)
                delay = delay * (0.5 + random.random())
                print(f"  ⏳ リトライ {attempt}/{MAX_RETRIES}: ネットワークエラー → {delay:.0f}秒待機", file=sys.stderr)
                time.sleep(delay)
            else:
                last_error = e

    # 全リトライ失敗
    if last_error:
        if isinstance(last_error, urllib.error.HTTPError):
            raise last_error
        raise RuntimeError(f"全{MAX_RETRIES}回リトライ失敗: {last_error}")


# ── メイン ──────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="X/Twitter投稿 v2.0（リトライ・診断付き）")
    parser.add_argument("text", nargs="?", default="", help="投稿テキスト")
    parser.add_argument("--reply-to", default="", help="返信先ツイートID")
    parser.add_argument("--alt-text", default="", help="画像ALTテキスト（将来拡張用）")
    parser.add_argument("--validate", action="store_true", help="credential検証のみ（投稿しない）")
    parser.add_argument("--delete", default="", help="指定tweet_idを削除")
    args = parser.parse_args()

    # ── credential検証（常に実行）──
    creds, cred_errors = validate_credentials()

    # ── ツイート削除 ──
    if args.delete:
        if cred_errors:
            print(f"❌ X credential検証失敗（削除不可）", file=sys.stderr)
            sys.exit(1)
        delete_id = args.delete.strip()
        endpoint = f"https://api.twitter.com/2/tweets/{delete_id}"
        auth_header = make_oauth_header(
            "DELETE", endpoint,
            creds["api_key"], creds["api_secret"],
            creds["access_token"], creds["access_token_secret"],
        )
        try:
            req = urllib.request.Request(endpoint, method="DELETE",
                                        headers={"Authorization": auth_header})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
                if data.get("data", {}).get("deleted"):
                    print(f"✅ ツイート削除成功: {delete_id}")
                    sys.exit(0)
                else:
                    print(f"⚠️ ツイート削除応答: {data}")
                    sys.exit(0)
        except urllib.error.HTTPError as e:
            print(f"❌ ツイート削除失敗 (HTTP {e.code}): {delete_id}", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"❌ ツイート削除エラー: {e}", file=sys.stderr)
            sys.exit(1)

    if args.validate:
        if cred_errors:
            print("❌ X credential検証: 問題あり")
            for err in cred_errors:
                print(f"  {err}")
            _log_diag("validate_fail", cred_errors)
            sys.exit(1)
        else:
            print("✅ X credential検証: 正常")
            print(f"  api_key: {creds['api_key'][:8]}...")
            print(f"  access_token: {creds['access_token'][:8]}...")
            _log_diag("validate_ok", ["全キー検証パス"])
            sys.exit(0)

    text = args.text.strip()
    reply_to = args.reply_to.strip()

    if not text:
        print("Usage: python3 post_to_x.py \"投稿テキスト\"")
        sys.exit(1)

    if cred_errors:
        print("❌ X credential検証失敗:", file=sys.stderr)
        for err in cred_errors:
            print(f"  {err}", file=sys.stderr)
        _log_diag("post_blocked_by_cred", cred_errors)
        sys.exit(1)

    # ── 投稿（リトライ付き）──
    try:
        tweet_id, attempts = post_tweet(text, reply_to, creds)
        retry_note = f" (リトライ{attempts}回目で成功)" if attempts > 1 else ""
        if tweet_id:
            tweet_url = f"https://x.com/i/status/{tweet_id}"
            if reply_to:
                print(f"✅ X返信投稿成功: {tweet_url}{retry_note}")
            else:
                print(f"✅ X投稿成功: {tweet_url}{retry_note}")
            print(f"  投稿文: {text[:80]}{'...' if len(text)>80 else ''}")
            print(f"TWEET_ID={tweet_id}")   # シェルスクリプトから grep で取得
        else:
            print(f"✅ X投稿完了 (IDなし){retry_note}")
            print("TWEET_ID=")
    except urllib.error.HTTPError as e:
        # 診断は post_tweet 内で既に出力済み
        sys.exit(1)
    except Exception as e:
        print(f"❌ X投稿失敗（全リトライ失敗）: {e}", file=sys.stderr)
        _log_diag("post_all_retries_failed", [str(e)])
        sys.exit(1)


if __name__ == "__main__":
    main()
