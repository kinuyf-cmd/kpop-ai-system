#!/usr/bin/env python3
"""
週刊メールマガジン自動生成・配信 v1.0
- 週間PV/CTRトップ記事を自動選定
- HTML/テキストメール両対応
- Brevo（旧Sendinblue）API v3連携
- エディターズピック対応

Usage:
  python3 lib/newsletter_builder.py                    # ビルド＋配信
  python3 lib/newsletter_builder.py --build-only       # HTMLビルドのみ（配信しない）
  python3 lib/newsletter_builder.py --dry-run          # プレビュー
  python3 lib/newsletter_builder.py --validate         # credential検証
  python3 lib/newsletter_builder.py --test-send EMAIL  # テスト配信（1通）

前提:
  ~/.newsletter_credentials に以下のJSON:
  {
    "api_key": "Brevo APIキー (xkeysib-...)",
    "sender_email": "news@kpopjournal.tokyo",
    "sender_name": "K-POP Journal",
    "list_id": 3
  }

  Brevo設定手順:
  1. https://app.brevo.com → SMTP & API → APIキーを生成
  2. Contacts → Lists → リスト作成（IDを控える）
  3. ~/.newsletter_credentials に保存（chmod 600）
"""
import json
import sys
import os
import re
import argparse
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
LOGS_DIR = BASE_DIR / "logs"
CONFIG_PATH = BASE_DIR / "config" / "sns_config.json"
CREDS_FILE = Path(os.path.expanduser("~/.newsletter_credentials"))
KPI_LOG = LOGS_DIR / "kpi_posts.jsonl"
HISTORY_LOG = LOGS_DIR / "newsletter_history.jsonl"
OUTPUT_DIR = BASE_DIR / "reports" / "newsletter"

JST = timezone(timedelta(hours=9))

BREVO_CAMPAIGN_URL = "https://api.brevo.com/v3/emailCampaigns"
BREVO_SEND_URL = "https://api.brevo.com/v3/smtp/email"


# ── 設定・認証 ──

def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text()).get("newsletter", {})
    except Exception:
        return {}


def load_credentials() -> tuple[dict | None, list[str]]:
    errors = []
    if not CREDS_FILE.exists():
        errors.append(f"CRED_MISSING: {CREDS_FILE} が見つかりません")
        errors.append('  {"api_key":"xkeysib-...","sender_email":"...","sender_name":"...","list_id":3}')
        return None, errors

    try:
        creds = json.loads(CREDS_FILE.read_text())
    except json.JSONDecodeError as e:
        errors.append(f"CRED_JSON_INVALID: {e}")
        return None, errors

    for key in ["api_key", "sender_email"]:
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


# ── 記事選定 ──

def select_articles(config: dict) -> list[dict]:
    """過去7日間のKPIログから週間ベスト記事を選定"""
    max_articles = config.get("content_rules", {}).get("max_articles", 7)
    min_articles = config.get("content_rules", {}).get("min_articles", 3)

    if not KPI_LOG.exists():
        return []

    cutoff = datetime.now(JST) - timedelta(days=7)
    articles = []

    for line in KPI_LOG.read_text().strip().split("\n"):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
            date_str = rec.get("date", "")
            if not date_str:
                continue
            rec_date = datetime.fromisoformat(date_str).replace(tzinfo=JST)
            if rec_date < cutoff:
                continue
            if rec.get("status") != "published" and not rec.get("post_id"):
                continue
            articles.append(rec)
        except Exception:
            continue

    if not articles:
        return []

    # スコアリング: PV重視 + CTRボーナス
    for a in articles:
        pv = a.get("pv", 0) or 0
        ctr = a.get("ctr", 0) or 0
        char_count = a.get("char_count", 0) or 0
        score = pv * 1.0 + (ctr * 100) * 0.5
        if char_count >= 4000:
            score *= 1.2  # 力作ボーナス
        a["_newsletter_score"] = score

    articles.sort(key=lambda x: x.get("_newsletter_score", 0), reverse=True)

    selected = articles[:max_articles]
    if len(selected) < min_articles:
        print(f"  ⚠️ 選定記事数が最小未満: {len(selected)}/{min_articles}", file=sys.stderr)

    return selected


# ── HTML生成 ──

def build_newsletter_html(articles: list[dict], config: dict) -> str:
    """メールマガジンのHTMLを生成"""
    now = datetime.now(JST)
    week_label = f"{(now - timedelta(days=7)).strftime('%m/%d')}〜{now.strftime('%m/%d')}"

    subject_prefix = config.get("content_rules", {}).get("subject_prefix", "K-POP Journal Weekly")

    # 記事ブロック生成
    article_blocks = []
    for i, a in enumerate(articles, 1):
        title = a.get("title", "無題")
        url = a.get("url", "#")
        category = a.get("article_type", "")
        char_count = a.get("char_count", 0) or 0

        badge = ""
        if i == 1:
            badge = '<span style="background:#FF3B30;color:#fff;padding:2px 8px;border-radius:3px;font-size:11px;margin-right:8px;">TOP</span>'
        elif category == "breaking":
            badge = '<span style="background:#FF9500;color:#fff;padding:2px 8px;border-radius:3px;font-size:11px;margin-right:8px;">速報</span>'

        article_blocks.append(f"""
        <tr>
          <td style="padding:16px 0;border-bottom:1px solid #eee;">
            <div style="margin-bottom:4px;">{badge}<span style="color:#666;font-size:12px;">{category}</span></div>
            <a href="{url}" style="color:#1a1a2e;text-decoration:none;font-size:16px;font-weight:bold;line-height:1.5;">
              {title}
            </a>
            <div style="margin-top:8px;">
              <a href="{url}" style="color:#007AFF;text-decoration:none;font-size:13px;">記事を読む &rarr;</a>
            </div>
          </td>
        </tr>""")

    articles_html = "\n".join(article_blocks)

    footer_text = config.get("template", {}).get("footer_text", "K-POP Journal | kpopjournal.tokyo")
    unsubscribe = config.get("template", {}).get("unsubscribe_url", "{{unsubscribe_url}}")

    html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{subject_prefix} — {week_label}</title>
</head>
<body style="margin:0;padding:0;background:#f5f5f5;font-family:-apple-system,BlinkMacSystemFont,'Hiragino Sans',sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f5f5f5;">
    <tr>
      <td align="center" style="padding:24px 16px;">
        <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:8px;overflow:hidden;max-width:600px;">

          <!-- ヘッダー -->
          <tr>
            <td style="background:linear-gradient(135deg,#1a1a2e,#16213e);padding:32px 24px;text-align:center;">
              <h1 style="color:#fff;margin:0;font-size:24px;letter-spacing:1px;">K-POP Journal</h1>
              <p style="color:#a8b2d1;margin:8px 0 0;font-size:14px;">Weekly Newsletter — {week_label}</p>
            </td>
          </tr>

          <!-- イントロ -->
          <tr>
            <td style="padding:24px;">
              <p style="color:#333;font-size:15px;line-height:1.7;margin:0;">
                今週もお読みいただきありがとうございます。<br>
                この1週間で最も読まれた記事をお届けします。
              </p>
            </td>
          </tr>

          <!-- 記事一覧 -->
          <tr>
            <td style="padding:0 24px;">
              <h2 style="color:#1a1a2e;font-size:18px;border-bottom:2px solid #1a1a2e;padding-bottom:8px;margin:0 0 8px;">
                今週のトップ記事
              </h2>
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                {articles_html}
              </table>
            </td>
          </tr>

          <!-- CTA -->
          <tr>
            <td style="padding:24px;text-align:center;">
              <a href="https://www.kpopjournal.tokyo" style="display:inline-block;background:#1a1a2e;color:#fff;padding:12px 32px;border-radius:6px;text-decoration:none;font-size:14px;font-weight:bold;">
                もっと読む
              </a>
            </td>
          </tr>

          <!-- フッター -->
          <tr>
            <td style="background:#f8f9fa;padding:20px 24px;text-align:center;border-top:1px solid #eee;">
              <p style="color:#999;font-size:12px;margin:0 0 8px;">{footer_text}</p>
              <a href="{unsubscribe}" style="color:#999;font-size:11px;">配信停止はこちら</a>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

    return html


def build_subject(config: dict) -> str:
    now = datetime.now(JST)
    prefix = config.get("content_rules", {}).get("subject_prefix", "K-POP Journal Weekly")
    week_label = f"{(now - timedelta(days=7)).strftime('%m/%d')}〜{now.strftime('%m/%d')}"
    return f"{prefix} — {week_label}"


# ── Brevo API送信 ──

def _brevo_request(url: str, data: dict, api_key: str) -> dict:
    payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload,
        headers={
            "api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as res:
        body = res.read().decode("utf-8")
        return json.loads(body) if body else {"status": res.status}


def send_campaign(html: str, subject: str, creds: dict, config: dict) -> dict:
    """Brevo APIでキャンペーンメールを作成・配信"""
    list_id = creds.get("list_id") or config.get("list_id")
    if not list_id:
        return {"error": "list_id が未設定"}

    api_key = creds["api_key"]

    # 1. キャンペーン作成
    campaign_data = {
        "name": f"KPJ Weekly {datetime.now(JST).strftime('%Y-%m-%d')}",
        "subject": subject,
        "sender": {
            "name": creds.get("sender_name", "K-POP Journal"),
            "email": creds["sender_email"],
        },
        "type": "classic",
        "htmlContent": html,
        "recipients": {"listIds": [int(list_id)]},
    }

    try:
        result = _brevo_request(BREVO_CAMPAIGN_URL, campaign_data, api_key)
        campaign_id = result.get("id")
        if not campaign_id:
            return {"error": f"キャンペーン作成失敗: {result}"}

        # 2. 即時配信
        send_url = f"{BREVO_CAMPAIGN_URL}/{campaign_id}/sendNow"
        req = urllib.request.Request(
            send_url,
            headers={
                "api-key": api_key,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as res:
            pass

        return {"success": True, "campaign_id": campaign_id}

    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        return {"error": f"HTTP {e.code}: {body[:300]}"}
    except Exception as e:
        return {"error": str(e)}


def send_test_email(html: str, subject: str, to_email: str, creds: dict) -> dict:
    """テスト配信（1通）"""
    data = {
        "sender": {
            "name": creds.get("sender_name", "K-POP Journal"),
            "email": creds["sender_email"],
        },
        "to": [{"email": to_email}],
        "subject": f"[TEST] {subject}",
        "htmlContent": html,
    }
    try:
        result = _brevo_request(BREVO_SEND_URL, data, creds["api_key"])
        return {"success": True, "messageId": result.get("messageId", "")}
    except Exception as e:
        return {"error": str(e)}


# ── メイン ──

def main():
    parser = argparse.ArgumentParser(description="週刊メールマガジン v1.0")
    parser.add_argument("--build-only", action="store_true", help="HTMLビルドのみ")
    parser.add_argument("--dry-run", action="store_true", help="プレビュー")
    parser.add_argument("--validate", action="store_true", help="credential検証")
    parser.add_argument("--test-send", default="", help="テスト配信先メール")
    args = parser.parse_args()

    config = load_config()
    creds, cred_errors = load_credentials()

    if args.validate:
        if cred_errors:
            print("❌ Newsletter credential検証: 問題あり")
            for err in cred_errors:
                print(f"  {err}")
            sys.exit(1)
        print("✅ Newsletter credential検証: 正常")
        print(f"  sender: {creds.get('sender_email')}")
        sys.exit(0)

    # 記事選定
    articles = select_articles(config)
    if not articles:
        print("⏭️ 選定可能な記事がありません（KPIログ不足）")
        sys.exit(0)

    print(f"  選定記事: {len(articles)}件")
    for i, a in enumerate(articles, 1):
        print(f"    {i}. {a.get('title', '無題')[:50]} (score: {a.get('_newsletter_score', 0):.0f})")

    # HTML生成
    html = build_newsletter_html(articles, config)
    subject = build_subject(config)

    # ファイル出力
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(JST).strftime("%Y%m%d")
    output_path = OUTPUT_DIR / f"newsletter_{date_str}.html"
    output_path.write_text(html, encoding="utf-8")
    print(f"  HTML出力: {output_path}")

    if args.build_only or args.dry_run:
        print(f"\n[{'BUILD-ONLY' if args.build_only else 'DRY-RUN'}]")
        print(f"  件名: {subject}")
        print(f"  記事数: {len(articles)}")
        print(f"  HTML: {len(html)}文字")
        sys.exit(0)

    if cred_errors:
        print("❌ credential検証失敗:", file=sys.stderr)
        for err in cred_errors:
            print(f"  {err}", file=sys.stderr)
        sys.exit(1)

    # テスト配信
    if args.test_send:
        result = send_test_email(html, subject, args.test_send, creds)
        if result.get("success"):
            print(f"✅ テストメール送信成功: {args.test_send}")
        else:
            print(f"❌ テストメール送信失敗: {result.get('error')}", file=sys.stderr)
            sys.exit(1)
        sys.exit(0)

    # 本番配信
    result = send_campaign(html, subject, creds, config)
    if result.get("success"):
        print(f"✅ ニュースレター配信成功 (campaign_id: {result['campaign_id']})")
        _log({
            "timestamp": datetime.now(JST).isoformat(),
            "subject": subject,
            "article_count": len(articles),
            "campaign_id": result["campaign_id"],
            "result": "sent",
        })
    else:
        print(f"❌ ニュースレター配信失敗: {result.get('error')}", file=sys.stderr)
        _log({
            "timestamp": datetime.now(JST).isoformat(),
            "subject": subject,
            "article_count": len(articles),
            "result": "failed",
            "error": result.get("error", "")[:200],
        })
        sys.exit(1)


if __name__ == "__main__":
    main()
