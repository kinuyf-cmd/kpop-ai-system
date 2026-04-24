#!/usr/bin/env python3
"""
discord_channel_router.py — Discord通知4チャネルルーター v1.0

既存の8 webhookチャネルを4つの論理チャネルにルーティングする。
各論理チャネルはDiscordサーバー上の1つのチャネルに対応する。

【4チャネル設計】

  #daily-report  : 毎日の経営サマリー（CEO朝礼・KPIスナップ・SEO概況）
    ← daily_ceo_report, seo_insights

  #article       : 記事公開通知（新規・リライト・X投稿成功）
    ← publishing_log

  #alert         : 異常通知（CRITICAL即時・WARNING集約）
    ← urgent_errors, alert_summary, sales_monetization

  #weekly        : 週次・月次レポート（ボード報告）
    ← weekly_board_report, monthly_board_report

【使い方】
  from lib.discord_channel_router import send_to_channel, ChannelType

  # 論理チャネルで送信
  send_to_channel(ChannelType.DAILY_REPORT, title, body)
  send_to_channel(ChannelType.ARTICLE, title, body)
  send_to_channel(ChannelType.ALERT, title, body, severity="CRITICAL")
  send_to_channel(ChannelType.WEEKLY, title, body)

  # 記事公開通知のヘルパー
  notify_article_published(post_id, title, url, category)
  notify_x_post_success(tweet_url, article_title)
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


class ChannelType(Enum):
    DAILY_REPORT = "daily-report"
    ARTICLE = "article"
    ALERT = "alert"
    WEEKLY = "weekly"


# 論理チャネル → 物理webhook(s) のマッピング
CHANNEL_MAP = {
    ChannelType.DAILY_REPORT: ["daily_ceo_report"],
    ChannelType.ARTICLE:      ["publishing_log"],
    ChannelType.ALERT:        ["urgent_errors", "alert_summary"],
    ChannelType.WEEKLY:       ["weekly_board_report"],
}

# チャネル別色
CHANNEL_COLORS = {
    ChannelType.DAILY_REPORT: 0x3498DB,   # 青
    ChannelType.ARTICLE:      0x2ECC71,   # 緑
    ChannelType.ALERT:        0xE74C3C,   # 赤
    ChannelType.WEEKLY:       0x9B59B6,   # 紫
}

# ALERT severity で送信先を分岐
ALERT_SEVERITY_MAP = {
    "CRITICAL": "urgent_errors",
    "WARNING":  "alert_summary",
    "REVENUE":  "sales_monetization",
}


def _load_webhooks() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text())
    except Exception:
        return {}


def _do_send(webhook_url: str, payload: dict) -> tuple[str, str]:
    """Discord webhook に送信。戻り値: (result, detail)"""
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    try:
        req = urllib.request.Request(
            webhook_url, data=data,
            headers={"Content-Type": "application/json", "User-Agent": "KpopJournal-Bot/1.0"},
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


def _log(channel_type: str, physical: str, title: str, result: str, detail: str = ""):
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(JST).isoformat(),
        "logical_channel": channel_type,
        "physical_channel": physical,
        "title": title[:80],
        "result": result,
        "detail": detail,
    }
    with open(ROUTER_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def send_to_channel(channel: ChannelType, title: str, body: str,
                    severity: str = "", color: int = None) -> list[dict]:
    """
    論理チャネルにメッセージを送信する。
    ALERT チャネルの場合、severity で物理チャネルを分岐する。

    Returns: list of {physical_channel, result, detail}
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

    # 送信先の物理チャネルを決定
    if channel == ChannelType.ALERT and severity:
        physical_keys = [ALERT_SEVERITY_MAP.get(severity, "alert_summary")]
    else:
        physical_keys = CHANNEL_MAP.get(channel, [])

    results = []
    for key in physical_keys:
        url = webhooks.get(key, "")
        if not url:
            _log(channel.value, key, title, "webhook_not_set")
            results.append({"physical_channel": key, "result": "webhook_not_set", "detail": ""})
            continue
        result, detail = _do_send(url, payload)
        _log(channel.value, key, title, result, detail)
        results.append({"physical_channel": key, "result": result, "detail": detail})

    return results


# ── 便利ヘルパー ──────────────────────────────────────────────

def notify_article_published(post_id: int, title: str, url: str,
                             category: str = "", is_rewrite: bool = False):
    """記事公開通知を #article チャネルに送信"""
    action = "リライト公開" if is_rewrite else "新規公開"
    cat_label = f" [{category}]" if category else ""
    body = (
        f"**{action}{cat_label}**\n\n"
        f"**{title}**\n"
        f"post_id: {post_id}\n"
        f"{url}"
    )
    return send_to_channel(
        ChannelType.ARTICLE,
        f"📰 {action}: {title[:50]}",
        body,
        color=0x2ECC71,
    )


def notify_x_post_success(tweet_url: str, article_title: str, article_url: str = ""):
    """X投稿成功通知を #article チャネルに送信"""
    body = (
        f"**X/Twitter 投稿成功**\n\n"
        f"記事: {article_title[:60]}\n"
        f"Tweet: {tweet_url}"
    )
    if article_url:
        body += f"\n記事URL: {article_url}"
    return send_to_channel(
        ChannelType.ARTICLE,
        f"🐦 X投稿成功: {article_title[:40]}",
        body,
        color=0x1DA1F2,
    )


def notify_daily_report(report_body: str, date_str: str = ""):
    """日次レポートを #daily-report チャネルに送信"""
    if not date_str:
        date_str = datetime.now(JST).strftime("%Y-%m-%d")
    return send_to_channel(
        ChannelType.DAILY_REPORT,
        f"📊 日次レポート {date_str}",
        report_body,
    )


def notify_weekly_report(report_body: str, week_label: str = ""):
    """週次レポートを #weekly チャネルに送信"""
    if not week_label:
        week_label = datetime.now(JST).strftime("W%W")
    return send_to_channel(
        ChannelType.WEEKLY,
        f"📈 週次ボードレポート {week_label}",
        report_body,
    )


def notify_alert(title: str, body: str, severity: str = "WARNING"):
    """アラートを #alert チャネルに送信"""
    color = {
        "CRITICAL": 0xE74C3C,
        "WARNING": 0xF39C12,
        "REVENUE": 0xE67E22,
    }.get(severity, 0xF39C12)
    return send_to_channel(
        ChannelType.ALERT,
        title,
        body,
        severity=severity,
        color=color,
    )


def print_channel_design():
    """4チャネル設計を表示"""
    print("""
╔══════════════════════════════════════════════════════════════════════╗
║   Discord 4チャネル設計 v1.0                                         ║
╠══════════════════╦═══════════════════════════════╦════════════════════╣
║ 論理チャネル     ║ 用途                          ║ 物理webhook        ║
╠══════════════════╬═══════════════════════════════╬════════════════════╣
║ #daily-report    ║ CEO朝礼・KPI・SEO概況         ║ daily_ceo_report   ║
║ #article         ║ 記事公開・X投稿成功            ║ publishing_log     ║
║ #alert           ║ CRITICAL即時・WARNING集約      ║ urgent_errors      ║
║                  ║                               ║ alert_summary      ║
║                  ║                               ║ sales_monetization ║
║ #weekly          ║ 週次・月次ボードレポート        ║ weekly_board_report║
╚══════════════════╩═══════════════════════════════╩════════════════════╝

【通知フロー】
  記事公開 → #article (publishing_log)
  X投稿成功 → #article (publishing_log)
  パイプライン停止 → #alert (urgent_errors) [CRITICAL]
  成功率低下 → #alert (alert_summary) [WARNING]
  売上異常 → #alert (sales_monetization) [REVENUE]
  毎朝KPI → #daily-report (daily_ceo_report)
  週次まとめ → #weekly (weekly_board_report)
""")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Discord 4チャネルルーター")
    parser.add_argument("--design", action="store_true", help="チャネル設計を表示")
    parser.add_argument("--test", choices=["daily-report", "article", "alert", "weekly"],
                        help="テスト送信")
    args = parser.parse_args()

    if args.design:
        print_channel_design()
    elif args.test:
        ch_map = {
            "daily-report": ChannelType.DAILY_REPORT,
            "article": ChannelType.ARTICLE,
            "alert": ChannelType.ALERT,
            "weekly": ChannelType.WEEKLY,
        }
        ch = ch_map[args.test]
        results = send_to_channel(
            ch,
            f"[テスト] #{args.test} チャネル動作確認",
            f"これは #{args.test} チャネルのテスト送信です。\n正常に表示されていれば設定完了です。",
        )
        for r in results:
            icon = "+" if r["result"] == "sent" else "!"
            print(f"  [{icon}] {r['physical_channel']}: {r['result']}")
    else:
        print_channel_design()
