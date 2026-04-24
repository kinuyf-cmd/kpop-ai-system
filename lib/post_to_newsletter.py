"""
Brevo (旧Sendinblue) ニュースレター送信 v1.0
- Brevo API v3 でウィークリーニュースレターを送信
- credential自動検証・診断
- レート制限（週1回まで）
- 送信履歴を logs/newsletter_history.jsonl に記録
- stdlib のみ使用（pip 不要）

Usage:
  python3 post_to_newsletter.py --send          # 実際に送信
  python3 post_to_newsletter.py --preview        # HTML をプレビュー表示
  python3 post_to_newsletter.py --validate       # APIキー検証のみ
  python3 post_to_newsletter.py --dry-run        # 送信シミュレーション（API呼び出しなし）

Config:
  ~/.brevo_credentials          {"api_key": "xkeysib-..."}
  config/sns_config.json        "newsletter" セクション
"""
import json
import sys
import os
import argparse
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── パス設定 ──
BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = BASE_DIR / "config" / "sns_config.json"
METRICS_FILE = BASE_DIR / "google_metrics" / "metrics_yesterday.json"
LOGS_DIR = BASE_DIR / "logs"
HISTORY_FILE = LOGS_DIR / "newsletter_history.jsonl"
DEFAULT_CREDS_FILE = os.path.expanduser("~/.brevo_credentials")

JST = timezone(timedelta(hours=9))

BREVO_SEND_URL = "https://api.brevo.com/v3/smtp/email"
BREVO_ACCOUNT_URL = "https://api.brevo.com/v3/account"

SITE_URL = "https://www.kpopjournal.tokyo"
SITE_NAME = "K-POP Journal"

# 週1回制限の秒数（6日 = 518400秒。日曜送信で翌日曜まで丸7日だが少し余裕を持たせる）
MIN_SEND_INTERVAL_SEC = 6 * 24 * 3600


# ── 設定読み込み ──────────────────────────────────────────────────

def load_config() -> dict:
    """sns_config.json から newsletter セクションを読み込む"""
    if not CONFIG_FILE.exists():
        print(f"WARN: {CONFIG_FILE} が見つかりません。デフォルト設定を使用します。", file=sys.stderr)
        return {}
    with open(CONFIG_FILE, encoding="utf-8") as f:
        full = json.load(f)
    return full.get("newsletter", {})


def load_credentials(config: dict) -> tuple:
    """
    credential を読み込み (api_key, errors) を返す。
    errors が空なら有効。
    """
    errors = []
    creds_path = os.path.expanduser(config.get("credentials_file", DEFAULT_CREDS_FILE))

    if not os.path.exists(creds_path):
        errors.append(f"CRED_MISSING: {creds_path} が見つかりません")
        errors.append('  修復: 以下のJSON形式で保存してください:')
        errors.append('  {"api_key": "xkeysib-..."}')
        return None, errors

    # ファイル権限チェック
    stat = os.stat(creds_path)
    mode = oct(stat.st_mode)[-3:]
    if mode not in ("600", "400"):
        errors.append(f"CRED_PERMISSION: パーミッション {mode} -- 推奨は 600")

    try:
        with open(creds_path, encoding="utf-8") as f:
            creds = json.load(f)
    except json.JSONDecodeError as e:
        errors.append(f"CRED_JSON_INVALID: JSONパースエラー -- {e}")
        return None, errors
    except Exception as e:
        errors.append(f"CRED_READ_ERROR: ファイル読み込み失敗 -- {e}")
        return None, errors

    api_key = creds.get("api_key", "").strip()
    if not api_key:
        errors.append("CRED_KEY_EMPTY: 'api_key' が未設定または空です")
        return None, errors
    if len(api_key) < 20:
        errors.append(f"CRED_KEY_SHORT: 'api_key' が短すぎます（{len(api_key)}文字）")
        return None, errors
    if api_key.startswith("YOUR_") or api_key == "xxx":
        errors.append("CRED_KEY_PLACEHOLDER: 'api_key' がプレースホルダーのままです")
        return None, errors

    return api_key, errors


# ── レート制限 ────────────────────────────────────────────────────

def check_rate_limit() -> tuple:
    """
    最終送信から十分な時間が経過しているか確認。
    (ok: bool, last_send_iso: str|None, seconds_remaining: int)
    """
    if not HISTORY_FILE.exists():
        return True, None, 0

    last_entry = None
    with open(HISTORY_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    last_entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

    if not last_entry:
        return True, None, 0

    # status が success のものだけカウント
    if last_entry.get("status") != "success":
        return True, None, 0

    last_ts = last_entry.get("sent_at", "")
    if not last_ts:
        return True, None, 0

    try:
        last_dt = datetime.fromisoformat(last_ts)
        now = datetime.now(JST)
        elapsed = (now - last_dt).total_seconds()
        if elapsed < MIN_SEND_INTERVAL_SEC:
            remaining = int(MIN_SEND_INTERVAL_SEC - elapsed)
            return False, last_ts, remaining
    except (ValueError, TypeError):
        pass

    return True, last_ts, 0


# ── 記事収集 ──────────────────────────────────────────────────────

def collect_top_articles(config: dict) -> list:
    """
    google_metrics/metrics_yesterday.json から上位記事を収集。
    GA4 の top_landing_pages と GSC の top_pages を統合し、
    PV/クリック数で上位を選出。
    """
    content_rules = config.get("content_rules", {})
    max_articles = content_rules.get("max_articles", 7)

    if not METRICS_FILE.exists():
        print(f"WARN: {METRICS_FILE} が見つかりません。記事なしで続行。", file=sys.stderr)
        return []

    try:
        with open(METRICS_FILE, encoding="utf-8") as f:
            metrics = json.load(f)
    except (json.JSONDecodeError, Exception) as e:
        print(f"WARN: メトリクス読み込み失敗: {e}", file=sys.stderr)
        return []

    # GA4 top_landing_pages からスコア算出
    articles = {}
    ga4 = metrics.get("ga4", {})
    for page in ga4.get("top_landing_pages", []):
        path = page.get("page", "")
        if not path or path in ("(not set)", "/"):
            continue
        sessions = int(page.get("sessions", 0))
        pageviews = int(page.get("pageviews", 0))
        engaged = int(page.get("engaged_sessions", 0))
        # スコア: PV + engaged * 3
        score = pageviews + engaged * 3
        title = _path_to_title(path)
        articles[path] = {
            "path": path,
            "url": f"{SITE_URL}{path}",
            "title": title,
            "sessions": sessions,
            "pageviews": pageviews,
            "engaged_sessions": engaged,
            "score": score,
            "ctr": 0.0,
            "gsc_clicks": 0,
        }

    # GSC top_pages からクリック/CTR情報を追加
    gsc = metrics.get("gsc", {})
    for page in gsc.get("top_pages", []):
        full_url = page.get("page", "")
        if not full_url:
            continue
        # URLからパスを抽出
        path = full_url.replace(SITE_URL, "")
        if not path or path == "/":
            continue
        clicks = int(page.get("clicks", 0))
        ctr = float(page.get("ctr", 0))

        if path in articles:
            articles[path]["gsc_clicks"] = clicks
            articles[path]["ctr"] = ctr
            articles[path]["score"] += clicks * 5
        else:
            title = _path_to_title(path)
            articles[path] = {
                "path": path,
                "url": full_url if full_url.startswith("http") else f"{SITE_URL}{path}",
                "title": title,
                "sessions": 0,
                "pageviews": 0,
                "engaged_sessions": 0,
                "score": clicks * 5,
                "ctr": ctr,
                "gsc_clicks": clicks,
            }

    # スコア降順で上位を選出
    sorted_articles = sorted(articles.values(), key=lambda a: a["score"], reverse=True)
    return sorted_articles[:max_articles]


def _path_to_title(path: str) -> str:
    """URLパスから仮タイトルを生成（slug を人間可読に変換）"""
    slug = path.strip("/").split("/")[-1] if "/" in path else path.strip("/")
    # ハイフンをスペースに、各語の先頭を大文字に
    words = slug.replace("-", " ").replace("_", " ").split()
    # 日本語を含む場合はそのまま
    if any(ord(c) > 127 for c in slug):
        return slug.replace("-", " ")
    return " ".join(w.capitalize() for w in words)


# ── HTML テンプレート ─────────────────────────────────────────────

def generate_newsletter_html(articles: list, config: dict, date_range: str) -> str:
    """レスポンシブ対応のHTMLニュースレターを生成"""
    template_cfg = config.get("template", {})
    header_image = template_cfg.get("header_image", "")
    footer_text = template_cfg.get("footer_text", f"{SITE_NAME} | kpopjournal.tokyo")
    unsubscribe_url = template_cfg.get("unsubscribe_url", "{{unsubscribe_url}}")

    # セクション振り分け
    content_rules = config.get("content_rules", {})
    include_sections = content_rules.get("include_sections",
                                         ["top_stories", "chart_update", "upcoming_events"])

    # 記事を HTML リスト化
    articles_html = ""
    if articles:
        for i, art in enumerate(articles, 1):
            ctr_str = f"{art['ctr']*100:.1f}%" if art.get("ctr") else ""
            badge = ""
            if i == 1:
                badge = '<span style="background:#ff4081;color:#fff;padding:2px 8px;border-radius:3px;font-size:11px;margin-left:8px;">MOST READ</span>'
            articles_html += f"""
            <tr>
              <td style="padding:12px 0;border-bottom:1px solid #f0f0f0;">
                <a href="{_escape_html(art['url'])}" style="color:#1a1a2e;text-decoration:none;font-size:16px;font-weight:600;line-height:1.5;">
                  {_escape_html(art['title'])}{badge}
                </a>
                <div style="color:#888;font-size:12px;margin-top:4px;">
                  PV: {art.get('pageviews', 0)} | Clicks: {art.get('gsc_clicks', 0)}{(' | CTR: ' + ctr_str) if ctr_str else ''}
                </div>
              </td>
            </tr>"""
    else:
        articles_html = """
            <tr>
              <td style="padding:12px 0;color:#888;">
                今週のピックアップ記事はありません。サイトをご覧ください。
              </td>
            </tr>"""

    # セクションHTML組み立て
    sections_html = ""

    if "top_stories" in include_sections:
        sections_html += f"""
        <!-- Top Stories -->
        <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:24px;">
          <tr>
            <td style="padding:16px 0 8px;border-bottom:3px solid #6c5ce7;">
              <h2 style="margin:0;color:#1a1a2e;font-size:20px;">TOP STORIES</h2>
            </td>
          </tr>
          {articles_html}
        </table>"""

    if "chart_update" in include_sections:
        sections_html += """
        <!-- Chart Update -->
        <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:24px;">
          <tr>
            <td style="padding:16px 0 8px;border-bottom:3px solid #00b894;">
              <h2 style="margin:0;color:#1a1a2e;font-size:20px;">CHART UPDATE</h2>
            </td>
          </tr>
          <tr>
            <td style="padding:12px 0;">
              <a href="https://www.kpopjournal.tokyo/category/chart/" style="color:#6c5ce7;text-decoration:none;font-size:14px;">
                最新チャート記事をチェック &rarr;
              </a>
            </td>
          </tr>
        </table>"""

    if "upcoming_events" in include_sections:
        sections_html += """
        <!-- Upcoming Events -->
        <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:24px;">
          <tr>
            <td style="padding:16px 0 8px;border-bottom:3px solid #fdcb6e;">
              <h2 style="margin:0;color:#1a1a2e;font-size:20px;">UPCOMING EVENTS</h2>
            </td>
          </tr>
          <tr>
            <td style="padding:12px 0;">
              <a href="https://www.kpopjournal.tokyo/category/event/" style="color:#6c5ce7;text-decoration:none;font-size:14px;">
                今後のK-POPイベント情報 &rarr;
              </a>
            </td>
          </tr>
        </table>"""

    # ヘッダー画像
    header_html = ""
    if header_image:
        img_url = header_image if header_image.startswith("http") else f"{SITE_URL}{header_image}"
        header_html = f"""
          <tr>
            <td style="padding:0;">
              <img src="{_escape_html(img_url)}" alt="{SITE_NAME}" style="width:100%;max-width:600px;height:auto;display:block;" />
            </td>
          </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{SITE_NAME} Weekly | {_escape_html(date_range)}</title>
  <!--[if mso]>
  <style>table {{border-collapse:collapse;}} td {{font-family:Arial,sans-serif;}}</style>
  <![endif]-->
</head>
<body style="margin:0;padding:0;background-color:#f5f5f5;font-family:'Helvetica Neue',Arial,'Hiragino Sans',sans-serif;-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f5f5f5;">
    <tr>
      <td align="center" style="padding:20px 10px;">
        <!-- Container -->
        <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="background-color:#ffffff;border-radius:8px;overflow:hidden;max-width:600px;width:100%;">

          {header_html}

          <!-- Title Bar -->
          <tr>
            <td style="background:linear-gradient(135deg,#6c5ce7,#a29bfe);padding:24px 30px;">
              <h1 style="margin:0;color:#ffffff;font-size:22px;font-weight:700;letter-spacing:0.5px;">
                {SITE_NAME} Weekly
              </h1>
              <p style="margin:6px 0 0;color:rgba(255,255,255,0.85);font-size:13px;">
                {_escape_html(date_range)}
              </p>
            </td>
          </tr>

          <!-- Body -->
          <tr>
            <td style="padding:24px 30px;">
              {sections_html}
            </td>
          </tr>

          <!-- CTA -->
          <tr>
            <td align="center" style="padding:0 30px 24px;">
              <a href="{SITE_URL}" style="display:inline-block;background:#6c5ce7;color:#ffffff;text-decoration:none;padding:12px 32px;border-radius:6px;font-size:14px;font-weight:600;">
                {SITE_NAME} を読む
              </a>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="background-color:#f8f8f8;padding:20px 30px;border-top:1px solid #e0e0e0;">
              <p style="margin:0;color:#888;font-size:12px;line-height:1.6;">
                {_escape_html(footer_text)}<br>
                <a href="{_escape_html(unsubscribe_url)}" style="color:#888;text-decoration:underline;">配信停止</a>
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

    return html


def _escape_html(text: str) -> str:
    """基本的なHTMLエスケープ"""
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


# ── Brevo API 呼び出し ───────────────────────────────────────────

def brevo_api_call(api_key: str, method: str, url: str,
                   payload: dict = None) -> tuple:
    """
    Brevo API を呼び出し (status_code, response_dict) を返す。
    """
    headers = {
        "api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "KPOPJournalNewsletter/1.0",
    }
    data = json.dumps(payload).encode("utf-8") if payload else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            body = res.read().decode("utf-8")
            return res.status, json.loads(body) if body.strip() else {}
    except urllib.error.HTTPError as e:
        resp_body = ""
        try:
            resp_body = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        try:
            resp_json = json.loads(resp_body)
        except (json.JSONDecodeError, ValueError):
            resp_json = {"raw": resp_body[:500]}
        return e.code, resp_json
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return 0, {"error": str(e)}


def validate_api_key(api_key: str) -> tuple:
    """
    Brevo APIキーの有効性を検証。
    (ok: bool, account_info: dict, error_msg: str)
    """
    status, resp = brevo_api_call(api_key, "GET", BREVO_ACCOUNT_URL)
    if status == 200:
        email = resp.get("email", "")
        plan = resp.get("plan", [{}])
        plan_type = plan[0].get("type", "unknown") if isinstance(plan, list) and plan else "unknown"
        return True, {"email": email, "plan": plan_type}, ""
    elif status == 401:
        return False, {}, "APIキーが無効です。Brevo管理画面でキーを再確認してください。"
    elif status == 0:
        return False, {}, f"接続エラー: {resp.get('error', '不明')}"
    else:
        msg = resp.get("message", resp.get("raw", f"HTTP {status}"))
        return False, {}, f"API検証失敗 (HTTP {status}): {msg}"


def send_email(api_key: str, config: dict, subject: str,
               html_content: str, list_id: str) -> tuple:
    """
    Brevo transactional email API で送信。
    list_id が設定されている場合はリスト宛て、なければ設定エラー。
    (ok: bool, result: dict, error_msg: str)
    """
    if not list_id:
        return False, {}, "list_id が未設定です。config/sns_config.json の newsletter.list_id を設定してください。"

    sender_name = SITE_NAME
    sender_email = f"newsletter@kpopjournal.tokyo"

    payload = {
        "sender": {"name": sender_name, "email": sender_email},
        "to": [{"email": sender_email, "name": sender_name}],
        "subject": subject,
        "htmlContent": html_content,
        "messageVersions": [
            {
                "to": [{"email": sender_email, "name": sender_name}],
                "params": {},
            }
        ],
    }

    # リストIDが数値の場合、Brevo Campaign API を使用
    # transactional ではリスト送信できないため、ここでは
    # Campaign 作成 + 即時送信の 2-step を行う
    if list_id.isdigit():
        return _send_via_campaign(api_key, config, subject, html_content, int(list_id))

    # list_id が email アドレスの場合は transactional で直接送信
    payload["to"] = [{"email": list_id}]
    del payload["messageVersions"]

    status, resp = brevo_api_call(api_key, "POST", BREVO_SEND_URL, payload)
    if status in (200, 201):
        return True, resp, ""
    else:
        msg = resp.get("message", resp.get("raw", f"HTTP {status}"))
        return False, resp, f"送信失敗 (HTTP {status}): {msg}"


def _send_via_campaign(api_key: str, config: dict, subject: str,
                       html_content: str, list_id: int) -> tuple:
    """
    Brevo Email Campaign API で送信。
    Step 1: キャンペーン作成
    Step 2: 即時送信
    """
    campaign_url = "https://api.brevo.com/v3/emailCampaigns"
    sender_email = "newsletter@kpopjournal.tokyo"

    create_payload = {
        "name": f"Weekly Newsletter {datetime.now(JST).strftime('%Y-%m-%d')}",
        "subject": subject,
        "sender": {"name": SITE_NAME, "email": sender_email},
        "htmlContent": html_content,
        "recipients": {"listIds": [list_id]},
        "inlineImageActivation": False,
    }

    # Step 1: キャンペーン作成
    status, resp = brevo_api_call(api_key, "POST", campaign_url, create_payload)
    if status not in (200, 201):
        msg = resp.get("message", resp.get("raw", f"HTTP {status}"))
        return False, resp, f"キャンペーン作成失敗 (HTTP {status}): {msg}"

    campaign_id = resp.get("id")
    if not campaign_id:
        return False, resp, "キャンペーンIDが取得できませんでした"

    # Step 2: 即時送信
    send_url = f"{campaign_url}/{campaign_id}/sendNow"
    status2, resp2 = brevo_api_call(api_key, "POST", send_url)
    if status2 in (200, 201, 204):
        return True, {"campaign_id": campaign_id}, ""
    else:
        msg = resp2.get("message", resp2.get("raw", f"HTTP {status2}"))
        return False, resp2, f"キャンペーン送信失敗 (HTTP {status2}): {msg}"


# ── 履歴ログ ──────────────────────────────────────────────────────

def log_history(entry: dict):
    """送信履歴を JSONL 形式で追記"""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ── 日付範囲計算 ──────────────────────────────────────────────────

def get_week_date_range() -> str:
    """今日を基準に過去1週間の日付範囲文字列を返す"""
    now = datetime.now(JST)
    end = now
    start = now - timedelta(days=7)
    return f"{start.strftime('%Y/%m/%d')} - {end.strftime('%Y/%m/%d')}"


# ── メイン ────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Brevo ニュースレター送信 v1.0"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--send", action="store_true",
                       help="ニュースレターを実際に送信")
    group.add_argument("--preview", action="store_true",
                       help="HTMLプレビューを標準出力に表示")
    group.add_argument("--validate", action="store_true",
                       help="Brevo APIキー検証のみ")
    group.add_argument("--dry-run", action="store_true",
                       help="送信シミュレーション（API呼び出しなし）")
    args = parser.parse_args()

    # ── 設定読み込み ──
    config = load_config()
    enabled = config.get("enabled", False)

    # ── credential読み込み ──
    api_key, cred_errors = load_credentials(config)

    # --validate: APIキー検証のみ
    if args.validate:
        if cred_errors:
            print("NG Brevo credential検証: 問題あり")
            for err in cred_errors:
                print(f"  {err}")
            sys.exit(1)
        ok, account_info, err_msg = validate_api_key(api_key)
        if ok:
            print("OK Brevo credential検証: 正常")
            print(f"  account: {account_info.get('email', '?')}")
            print(f"  plan: {account_info.get('plan', '?')}")
        else:
            print(f"NG Brevo credential検証失敗: {err_msg}")
            sys.exit(1)
        sys.exit(0)

    # credential が無い場合: graceful skip
    if cred_errors:
        # preview / dry-run は credential なしでも続行可能
        if not (args.preview or args.dry_run):
            print("SKIP ニュースレター: credential未設定")
            for err in cred_errors:
                print(f"  {err}", file=sys.stderr)
            sys.exit(0)

    # ── 記事収集 ──
    articles = collect_top_articles(config)
    content_rules = config.get("content_rules", {})
    min_articles = content_rules.get("min_articles", 3)

    date_range = get_week_date_range()
    subject = f"{content_rules.get('subject_prefix', 'K-POP Journal Weekly')} | {date_range}"

    # ── HTML生成 ──
    html = generate_newsletter_html(articles, config, date_range)

    # --preview: HTML を出力して終了
    if args.preview:
        print(html)
        print(f"\n--- Preview Info ---", file=sys.stderr)
        print(f"Subject: {subject}", file=sys.stderr)
        print(f"Articles: {len(articles)}", file=sys.stderr)
        for i, a in enumerate(articles, 1):
            print(f"  {i}. {a['title']} (score={a['score']})", file=sys.stderr)
        sys.exit(0)

    # --dry-run: シミュレーション
    if args.dry_run:
        print(f"DRY-RUN ニュースレター送信シミュレーション")
        print(f"  Subject: {subject}")
        print(f"  Articles: {len(articles)}")
        for i, a in enumerate(articles, 1):
            print(f"    {i}. {a['title']} (score={a['score']}, pv={a.get('pageviews',0)})")
        print(f"  Enabled: {enabled}")
        print(f"  List ID: {config.get('list_id', '(未設定)')}")

        # レート制限チェック
        rate_ok, last_send, remaining = check_rate_limit()
        if not rate_ok:
            hours = remaining // 3600
            print(f"  Rate limit: BLOCKED (前回送信: {last_send}, 残り{hours}時間)")
        else:
            print(f"  Rate limit: OK (前回送信: {last_send or 'なし'})")

        # 記事数チェック
        if len(articles) < min_articles:
            print(f"  WARNING: 記事数 {len(articles)} < 最小 {min_articles} -- 送信スキップされます")

        log_history({
            "sent_at": datetime.now(JST).isoformat(),
            "status": "dry_run",
            "subject": subject,
            "article_count": len(articles),
        })
        sys.exit(0)

    # ── --send: 実際に送信 ──
    if not enabled:
        print("SKIP ニュースレター: config で enabled=false です。")
        print("  有効化: config/sns_config.json の newsletter.enabled を true に変更")
        sys.exit(0)

    # 記事数チェック
    if len(articles) < min_articles:
        print(f"SKIP ニュースレター: 記事数不足 ({len(articles)} < {min_articles})")
        log_history({
            "sent_at": datetime.now(JST).isoformat(),
            "status": "skipped_insufficient_articles",
            "article_count": len(articles),
        })
        sys.exit(0)

    # レート制限チェック
    rate_ok, last_send, remaining = check_rate_limit()
    if not rate_ok:
        hours = remaining // 3600
        print(f"SKIP ニュースレター: 週1回制限 (前回: {last_send}, 残り約{hours}時間)")
        sys.exit(0)

    # 送信実行
    list_id = config.get("list_id", "")
    ok, result, err_msg = send_email(api_key, config, subject, html, list_id)

    if ok:
        print(f"OK ニュースレター送信成功")
        print(f"  Subject: {subject}")
        print(f"  Articles: {len(articles)}")
        if result.get("campaign_id"):
            print(f"  Campaign ID: {result['campaign_id']}")
        log_history({
            "sent_at": datetime.now(JST).isoformat(),
            "status": "success",
            "subject": subject,
            "article_count": len(articles),
            "result": result,
        })
    else:
        print(f"NG ニュースレター送信失敗: {err_msg}", file=sys.stderr)
        log_history({
            "sent_at": datetime.now(JST).isoformat(),
            "status": "failed",
            "subject": subject,
            "article_count": len(articles),
            "error": err_msg,
        })
        sys.exit(1)


if __name__ == "__main__":
    main()
