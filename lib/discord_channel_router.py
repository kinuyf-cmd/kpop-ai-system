#!/usr/bin/env python3
"""
discord_channel_router.py — Discord通知ルーター v2.0

【4チャネル設計】
  morning  : モーニングブリーフィング（CEO朝礼・KPIスナップ）
  seo      : SEOレポート（GSC・CTR・検索パフォーマンス）
  publish  : 投稿通知（記事公開・リライト・X投稿）
  error    : エラー通知（CRITICAL/WARNING 全て統合）

【使い方】
  from lib.discord_channel_router import send_to_channel, ChannelType

  send_to_channel(ChannelType.MORNING, title, body)
  send_to_channel(ChannelType.SEO, title, body)
  send_to_channel(ChannelType.PUBLISH, title, body)
  send_to_channel(ChannelType.ERROR, title, body)
"""
import json
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from enum import Enum
from pathlib import Path

BASE = Path(__file__).parent.parent
CONFIG_PATH = BASE / "config" / "discord_webhooks.json"
LOGS_DIR = BASE / "logs"
ROUTER_LOG = LOGS_DIR / "discord_router.jsonl"
JST = timezone(timedelta(hours=9))


# 2026-07-15: ChannelType の値を config/discord_webhooks.json の実キーへ修正。
# 旧値 (morning/seo/publish/error) は config に存在せず send_to_channel が常に
# webhook_not_set でサイレント失敗していた。実キーに揃えることで既存の
# 呼び出しインターフェースを保ったまま通知を復活させる。
class ChannelType(Enum):
    MORNING = "daily_ceo_report"
    SEO = "seo_insights"
    PUBLISH = "publishing_log"
    ERROR = "urgent_errors"

    # 後方互換エイリアス（既存コードの段階移行用）
    DAILY_REPORT = "daily_ceo_report"
    ARTICLE = "publishing_log"
    ALERT = "urgent_errors"
    WEEKLY = "weekly_board_report"


# チャネル別色
CHANNEL_COLORS = {
    ChannelType.MORNING: 0x3498DB,   # 青
    ChannelType.SEO:     0x27AE60,   # 緑
    ChannelType.PUBLISH: 0x2ECC71,   # 明緑
    ChannelType.ERROR:   0xE74C3C,   # 赤
}


def _load_webhooks() -> dict:
    # 2026-07-15: 生 json.load では ${DISCORD_WEBHOOK_*} が未展開のまま返り
    # 送信失敗していた。resolve_discord_webhook.resolve() (=.env 自前ロード+
    # expandvars+URL 検証) で各チャンネルを実 URL へ解決する。
    if not CONFIG_PATH.exists():
        return {}
    try:
        from lib.resolve_discord_webhook import resolve
    except Exception:
        return {}
    out = {}
    try:
        keys = json.loads(CONFIG_PATH.read_text()).keys()
    except Exception:
        return {}
    for k in keys:
        if k.startswith("_"):
            continue
        url = resolve(k)
        if url:
            out[k] = url
    return out


def _do_send(webhook_url: str, payload: dict) -> tuple[str, str]:
    """Discord webhook に送信。戻り値: (result, detail)"""
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    try:
        req = urllib.request.Request(
            webhook_url, data=data,
            headers={"Content-Type": "application/json", "User-Agent": "KpopJournal-Bot/2.0"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status in (200, 204):
                return "sent", ""
            return "http_other", f"HTTP {resp.status}"
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")[:120]
        except Exception:
            pass
        return f"http_{e.code}", body
    except Exception as e:
        return "network_error", str(e)[:120]


def _log(channel: str, title: str, result: str, detail: str = ""):
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(JST).isoformat(),
        "channel": channel,
        "title": title[:80],
        "result": result,
        "detail": detail,
    }
    with open(ROUTER_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def send_to_channel(channel: ChannelType, title: str, body: str,
                    severity: str = "", color: int = None) -> list[dict]:
    """
    チャネルにメッセージを送信する。
    severity は後方互換用（無視して全て channel の webhook に送信）。

    Returns: list of {channel, result, detail}
    """
    webhooks = _load_webhooks()
    now_jst = datetime.now(JST).strftime("%Y-%m-%d %H:%M JST")

    if color is None:
        color = CHANNEL_COLORS.get(channel, 0x95A5A6)

    # body を 1900文字に制限
    if len(body) > 1900:
        body = body[:1900] + "\n...(省略)"

    payload = {
        "username": "K-POP AI System",
        "embeds": [{
            "title": title,
            "description": body,
            "color": color,
            "footer": {"text": f"#{channel.value} | {now_jst}"},
        }],
    }

    # 物理webhook名 = channel.value
    webhook_key = channel.value
    url = webhooks.get(webhook_key, "")
    if not url:
        _log(webhook_key, title, "webhook_not_set")
        return [{"channel": webhook_key, "result": "webhook_not_set", "detail": ""}]

    result, detail = _do_send(url, payload)
    _log(webhook_key, title, result, detail)
    return [{"channel": webhook_key, "result": result, "detail": detail}]


# ── 便利ヘルパー ──────────────────────────────────────────────

def notify_article_published(post_id: int, title: str, url: str,
                             category: str = "", is_rewrite: bool = False):
    """記事公開通知を #publish チャネルに送信"""
    action = "リライト公開" if is_rewrite else "新規公開"
    cat_label = f" [{category}]" if category else ""
    body = (
        f"**{action}{cat_label}**\n\n"
        f"**{title}**\n"
        f"post_id: {post_id}\n"
        f"{url}"
    )
    return send_to_channel(ChannelType.PUBLISH, f"📰 {action}: {title[:50]}", body)


def notify_x_post_success(tweet_url: str, article_title: str, article_url: str = ""):
    """X投稿成功通知を #publish チャネルに送信"""
    body = (
        f"**X/Twitter 投稿成功**\n\n"
        f"記事: {article_title[:60]}\n"
        f"Tweet: {tweet_url}"
    )
    if article_url:
        body += f"\n記事URL: {article_url}"
    return send_to_channel(ChannelType.PUBLISH, f"🐦 X投稿成功: {article_title[:40]}", body)


def notify_morning_brief(report_body: str, date_str: str = ""):
    """モーニングブリーフィングを送信"""
    if not date_str:
        date_str = datetime.now(JST).strftime("%Y-%m-%d")
    return send_to_channel(ChannelType.MORNING, f"☀️ モーニングブリーフ {date_str}", report_body)


def notify_seo_report(report_body: str, label: str = ""):
    """SEOレポートを送信"""
    if not label:
        label = datetime.now(JST).strftime("%Y-%m-%d")
    return send_to_channel(ChannelType.SEO, f"📊 SEOレポート {label}", report_body)


def notify_error(title: str, body: str, severity: str = "CRITICAL"):
    """エラー通知を送信"""
    color = 0xE74C3C if severity == "CRITICAL" else 0xF39C12
    return send_to_channel(ChannelType.ERROR, title, body, color=color)


# 後方互換ヘルパー
def notify_daily_report(report_body: str, date_str: str = ""):
    return notify_morning_brief(report_body, date_str)

def notify_weekly_report(report_body: str, week_label: str = ""):
    return notify_morning_brief(report_body, week_label)

def notify_alert(title: str, body: str, severity: str = "WARNING"):
    return notify_error(title, body, severity)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Discord 4チャネルルーター v2.0")
    parser.add_argument("--design", action="store_true", help="チャネル設計を表示")
    parser.add_argument("--test", choices=["morning", "seo", "publish", "error"],
                        help="テスト送信")
    args = parser.parse_args()

    if args.test:
        ch_map = {
            "morning": ChannelType.MORNING,
            "seo": ChannelType.SEO,
            "publish": ChannelType.PUBLISH,
            "error": ChannelType.ERROR,
        }
        ch = ch_map[args.test]
        results = send_to_channel(
            ch,
            f"[テスト] #{args.test} チャネル動作確認",
            f"これは #{args.test} チャネルのテスト送信です。\n正常に表示されていれば設定完了です。",
        )
        for r in results:
            icon = "✅" if r["result"] == "sent" else "❌"
            print(f"  {icon} {r['channel']}: {r['result']}")
    else:
        print("""
Discord 4チャネル設計 v2.0
══════════════════════════════════════════
  #morning  : モーニングブリーフィング
  #seo      : SEOレポート
  #publish  : 投稿通知（記事公開・X投稿）
  #error    : エラー通知（CRITICAL/WARNING統合）
══════════════════════════════════════════
テスト: python3 lib/discord_channel_router.py --test morning
""")
