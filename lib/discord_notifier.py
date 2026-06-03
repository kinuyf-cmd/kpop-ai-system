#!/usr/bin/env python3
"""
discord_notifier.py — AI会社 オーナー向け経営異常通知システム v2.0
CEO: ミュウツー / オーナー: 人間（閲覧専用）

【通知3段階】
  CRITICAL : urgent_errors チャネルへ即時送信（抑制: 30分）
             → パイプライン停止・タイトル崩壊・WP投稿失敗・HARD_FAIL多発・売上直結停止
  WARNING  : alert_summary チャネルへ集約送信（抑制: 6時間）
             → 空出力増加・サボり・成功率低下・サムネ/CTA未設定
  INFO     : 通知せず dashboard.html のみ更新

【重複通知抑制】
  logs/discord_alert_history.jsonl に送信済みイベントを記録。
  同一 event_key が抑制時間内に送信済みなら再送しない。
  event_key 形式: "rule_id__対象識別子"
  例: "C1_pipeline_down__pipeline", "C3_title_collapse__2555"

【送信失敗の分類】
  webhook_not_set  : Webhook URLが空（config未設定）
  http_403         : Discord 403 Forbidden（URL期限切れ・Bot保護）
  http_404         : Discord 404 Not Found（Webhook削除済み）
  http_other       : その他HTTPエラー
  network_error    : タイムアウト・接続エラー

Usage:
  python3 lib/discord_notifier.py              # 通常実行
  python3 lib/discord_notifier.py --dry-run    # 判定のみ（送信しない）
  python3 lib/discord_notifier.py --summary    # WARNINGまとめ通知のみ
  python3 lib/discord_notifier.py --test-critical  # CRITICALテスト送信（1件）
  python3 lib/discord_notifier.py --test-warning   # WARNINGテスト送信（1件）
  python3 lib/discord_notifier.py --rules      # 通知ルール一覧を表示
  python3 lib/discord_notifier.py --status     # Webhook設定状況を確認
"""

import argparse
import json
import os
import re
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).parent.parent
# lib/ 内から lib.alert_queue を import できるよう BASE を sys.path に追加
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))
CONFIG_PATH  = BASE / "config" / "discord_webhooks.json"
# Discord 送信用 UA は lib/resolve_discord_webhook.py に集約(DRY)。
from lib.resolve_discord_webhook import DISCORD_USER_AGENT  # noqa: E402
METRICS_PATH = BASE / "agent_metrics.json"
REVENUE_PATH = BASE / "revenue_metrics.json"
SUMMARY_PATH = BASE / "dashboard_summary.json"
HISTORY_PATH = BASE / "logs" / "discord_alert_history.jsonl"

JST = timezone(timedelta(hours=9))

# ─────────────────────────────────────────────────────────────
# チャネル・色定義
# ─────────────────────────────────────────────────────────────
CHANNEL_CRITICAL = "urgent_errors"
CHANNEL_WARNING  = "alert_summary"
CHANNEL_REVENUE  = "sales_monetization"

COLOR_CRITICAL = 0xE74C3C   # 赤
COLOR_WARNING  = 0xF39C12   # オレンジ
COLOR_INFO     = 0x3498DB   # 青
COLOR_TEST     = 0x9B59B6   # 紫（テスト送信）

# 抑制時間
SUPPRESS_MINUTES = {
    "CRITICAL": 30,
    "WARNING":  360,   # 6時間
}

# ─────────────────────────────────────────────────────────────
# 売上直結エージェント定義
# ─────────────────────────────────────────────────────────────
REVENUE_CRITICAL_AGENTS = {
    "arceus":         "アルセウス（最終投稿承認）",
    "wordpress_post": "WP投稿（WordPress直結）",
    "カイリュー":       "カイリュー（CVR・回遊最適化）",
    "meowth":         "ニャース（収益化責任者）",
}

# ─────────────────────────────────────────────────────────────
# 重複通知抑制（alert_history）
# ─────────────────────────────────────────────────────────────

def _load_history() -> list[dict]:
    """送信済みイベント履歴を読み込む"""
    if not HISTORY_PATH.exists():
        return []
    records = []
    with HISTORY_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def _is_suppressed(event_key: str, severity: str) -> bool:
    """
    同一 event_key が抑制時間内に送信済みなら True を返す。
    抑制時間: CRITICAL=30分, WARNING=360分
    """
    suppress_min = SUPPRESS_MINUTES.get(severity, 30)
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=suppress_min)
    history = _load_history()
    for rec in reversed(history):
        if rec.get("event_key") != event_key:
            continue
        if rec.get("severity") != severity:
            continue
        if rec.get("result") != "sent":
            continue
        try:
            sent_at_str = rec.get("sent_at", "")
            sent_at_str = sent_at_str.replace("Z", "+00:00")
            sent_at = datetime.fromisoformat(sent_at_str)
            if sent_at.tzinfo is None:
                sent_at = sent_at.replace(tzinfo=timezone.utc)
            if sent_at >= cutoff:
                return True
        except Exception:
            continue
    return False


def _record_history(event_key: str, severity: str, rule: str,
                    channel: str, title: str, result: str, reason: str = "") -> None:
    """送信結果を logs/discord_alert_history.jsonl へ追記"""
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "sent_at":   datetime.now(timezone.utc).isoformat(),
        "event_key": event_key,
        "severity":  severity,
        "rule":      rule,
        "channel":   channel,
        "title":     title,
        "result":    result,   # "sent" | "suppressed" | "webhook_not_set" | "http_403" | "http_404" | "http_other" | "network_error"
        "reason":    reason,
    }
    with HISTORY_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


# ─────────────────────────────────────────────────────────────
# event_key 生成
# ─────────────────────────────────────────────────────────────

def _make_event_key(rule: str, agent: str | None, extra: str = "") -> str:
    """
    event_key = "rule_id__識別子"
    識別子は agent_id またはpost_id等。なければruleのみ。
    例: "C1_pipeline_down__pipeline"
        "C3_title_collapse__2555"
        "W4_no_cta__"
    """
    target = agent or extra or ""
    # 日本語・スペースをアンダースコアに正規化（keyとして使いやすくする）
    target = re.sub(r"[^\w]", "_", target)
    return f"{rule}__{target}"


# ─────────────────────────────────────────────────────────────
# Discord送信（失敗理由を明確に分類）
# ─────────────────────────────────────────────────────────────

def _expand_webhook(value: str) -> str:
    """M11.5.B: config の値が "${DISCORD_WEBHOOK_*}" プレースホルダーなら
    .env / 環境変数から実URLを解決する。実URLが直書きされていればそのまま返す
    (後方互換)。.env は自動で環境に入らないため、未ロードなら一度読む。"""
    value = (value or "").strip()
    if not value:
        return ""
    expanded = os.path.expandvars(value)
    # 環境に無く未展開のまま(${...} が残る)なら .env を読んで再試行
    if expanded.startswith("${") and expanded.endswith("}"):
        _load_dotenv_once()
        expanded = os.path.expandvars(value)
    # それでも未解決ならプレースホルダーは返さない(誤送信防止)
    return "" if expanded.startswith("${") else expanded


_DOTENV_LOADED = False


def _load_dotenv_once() -> None:
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return
    _DOTENV_LOADED = True
    env_path = BASE / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        # 既に環境にあれば上書きしない(明示 export を尊重)
        if k and k not in os.environ:
            os.environ[k] = v.strip().strip('"').strip("'")


def _get_webhook(channel: str) -> str:
    if not CONFIG_PATH.exists():
        return ""
    try:
        d = json.loads(CONFIG_PATH.read_text())
        return _expand_webhook(d.get(channel, "") or "")
    except Exception:
        return ""


def _clean_body(body: str) -> str:
    body = re.sub(r'\n{3,}', '\n\n', body.strip())
    if len(body) > 1900:
        body = body[:1900] + "\n…（省略）"
    return body


def _fmt_ts(ts: str) -> str:
    if not ts:
        return "不明"
    try:
        ts = ts.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts).astimezone(JST)
        return dt.strftime("%m/%d %H:%M JST")
    except Exception:
        return ts[:16]


def _fmt_age(hours: float) -> str:
    if hours >= 9990:
        return "不明"
    if hours >= 48:
        return f"{hours/24:.0f}日"
    return f"{hours:.0f}時間"


def _build_payload(title: str, body: str, color: int, event_key: str) -> dict:
    now_jst_str = datetime.now(JST).strftime("%Y-%m-%d %H:%M JST")
    return {
        "username": "K-POP AI 監視システム",
        "embeds": [{
            "title": title,
            "description": _clean_body(body),
            "color": color,
            "footer": {
                "text": (
                    f"AI会社 監視システム v2.0 | CEO: ミュウツー | {now_jst_str}"
                    f" | key: {event_key}"
                )
            },
        }]
    }


# 戻り値: ("sent"|"webhook_not_set"|"http_403"|"http_404"|"http_other"|"network_error", detail)
def _do_send(channel: str, title: str, body: str, color: int,
             event_key: str) -> tuple[str, str]:
    # alert_queue の transport 関数に委譲（User-Agent 等を一元管理）
    from lib.alert_queue import send_via_transport
    return send_via_transport(channel, title, body, color, event_key)


def _do_send_legacy(channel: str, title: str, body: str, color: int,
                    event_key: str) -> tuple[str, str]:
    """旧実装（参照用に残す。実際の送信は _do_send → send_via_transport を使用）"""
    url = _get_webhook(channel)
    if not url:
        return "webhook_not_set", f"channel={channel}"

    payload = _build_payload(title, body, color, event_key)
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    try:
        req = urllib.request.Request(
            url,
            data=data,
            # User-Agent 必須: 既定の python-urllib UA は Discord/Cloudflare に
            # error code 1010(HTTP 403)でブロックされる。明示 UA で 204 成功。
            headers={
                "Content-Type": "application/json",
                "User-Agent": DISCORD_USER_AGENT,
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status in (200, 204):
                return "sent", ""
            return "http_other", f"HTTP {resp.status}"
    except urllib.error.HTTPError as e:
        body_snippet = ""
        try:
            body_snippet = e.read().decode("utf-8", errors="replace")[:120]
        except Exception:
            pass
        if e.code == 403:
            return "http_403", f"403 Forbidden — {body_snippet}"
        if e.code == 404:
            return "http_404", f"404 Not Found（Webhook削除済みの可能性）— {body_snippet}"
        return "http_other", f"HTTP {e.code} — {body_snippet}"
    except Exception as e:
        return "network_error", str(e)[:120]


def send_discord(channel: str, title: str, body: str, color: int,
                 event_key: str, severity: str,
                 dry_run: bool = False) -> str:
    """
    Discord送信。重複抑制・履歴記録込み。
    戻り値: "sent" | "suppressed" | "dry_run" | エラー種別文字列
    """
    rule_id = event_key.split("__")[0] if "__" in event_key else event_key

    # 抑制チェック（dry_runとtest送信は抑制しない）
    if not dry_run and _is_suppressed(event_key, severity):
        _record_history(event_key, severity, rule_id, channel, title, "suppressed")
        print(f"  [notifier] 抑制中 ({SUPPRESS_MINUTES[severity]}分) {event_key}", file=sys.stderr)
        return "suppressed"

    if dry_run:
        print(f"\n[DRY-RUN] channel={channel} severity={severity}")
        print(f"  event_key : {event_key}")
        print(f"  title     : {title}")
        print(f"  body      : {body[:100].replace(chr(10),' ')}")
        return "dry_run"

    result, detail = _do_send(channel, title, body, color, event_key)

    # 失敗ログ（明確に区別）
    if result == "sent":
        print(f"  [notifier] ✅ 送信成功 channel={channel} key={event_key}", file=sys.stderr)
    elif result == "webhook_not_set":
        print(f"  [notifier] ⚠️  Webhook未設定 channel={channel} → キューに保存", file=sys.stderr)
    elif result == "http_403":
        print(f"  [notifier] ❌ 403 Forbidden channel={channel} → キューに保存", file=sys.stderr)
    elif result == "http_404":
        print(f"  [notifier] ❌ 404 Not Found channel={channel} → キューに保存", file=sys.stderr)
        print(f"             → Webhookが削除されています。Discordで新しいWebhookを作成してください。", file=sys.stderr)
    else:
        print(f"  [notifier] ❌ 送信失敗 [{result}] channel={channel} → キューに保存", file=sys.stderr)

    _record_history(event_key, severity, rule_id, channel, title, result, detail)

    # 送信失敗時は必ずキューへ保存（CRITICAL/WARNING 問わずロストさせない）
    if result != "sent":
        from lib.alert_queue import enqueue
        enqueue(
            severity=severity, channel=channel, title=title, body=body,
            color=color, event_key=event_key, rule=rule_id, last_error=f"{result}: {detail}",
        )

    return result


# ─────────────────────────────────────────────────────────────
# CRITICALアラート判定
# ─────────────────────────────────────────────────────────────

def check_critical(metrics: dict, revenue: dict, summary: dict) -> list[dict]:
    alerts = []
    agents = metrics.get("agents", {})

    # C1: パイプライン全体停止
    pipe = agents.get("pipeline", {})
    if pipe.get("total_count", 0) > 0 and pipe.get("success_rate", 1.0) == 0.0:
        alerts.append({
            "rule": "C1_pipeline_down",
            "event_key": _make_event_key("C1_pipeline_down", "pipeline"),
            "title": "🚨 パイプライン全体停止",
            "body": (
                f"**パイプライン（制御エージェント）が全試行で失敗しています。**\n\n"
                f"- 成功率: 0%（{pipe['fail_count']}回失敗）\n"
                f"- 最終実行: {_fmt_ts(pipe.get('last_run_time',''))}\n\n"
                f"**売上影響**: 記事投稿が完全停止します。\n"
                f"**確認ログ**: `logs/pipeline.jsonl` の末尾エラーを確認してください。"
            ),
            "channel": CHANNEL_CRITICAL,
            "agent": "パイプライン",
        })

    # C2: WordPress投稿失敗多発
    wp = agents.get("wordpress_post", {})
    wp_rate = wp.get("success_rate", 1.0)
    wp_total = wp.get("total_count", 0)
    if wp_total >= 3 and wp_rate < 0.80:
        alerts.append({
            "rule": "C2_wp_post_failure",
            "event_key": _make_event_key("C2_wp_post_failure", "wordpress_post"),
            "title": "🚨 WordPress投稿失敗多発",
            "body": (
                f"**WP投稿エージェントの成功率が危険域です。**\n\n"
                f"- 成功率: {wp_rate:.0%}（{wp['success_count']}/{wp_total}回）\n"
                f"- 空出力: {wp.get('empty_output_count',0)}件\n\n"
                f"**売上影響**: 記事がWordPressに投稿されず、収益機会を失います。\n"
                f"**確認ログ**: `logs/pipeline.jsonl` で `step=wordpress_post` のエラーを確認。"
            ),
            "channel": CHANNEL_CRITICAL,
            "agent": "WP投稿",
        })

    # C3: タイトル崩壊検出
    contaminated = revenue.get("summary", {}).get("contaminated_titles", [])
    if contaminated:
        titles_text = "\n".join(
            f"  - post_id={c.get('post_id') or '不明'}: `{c['title'][:45]}…`"
            for c in contaminated[:3]
        )
        # event_keyにpost_idを含める（複数ある場合は最初のpost_idを代表）
        rep_id = contaminated[0].get("post_id") or "unknown"
        alerts.append({
            "rule": "C3_title_collapse",
            "event_key": _make_event_key("C3_title_collapse", None, str(rep_id)),
            "title": "🚨 タイトル崩壊記事を検出",
            "body": (
                f"**AI応答文がタイトルに混入した記事が {len(contaminated)}件あります。**\n\n"
                f"{titles_text}\n\n"
                f"**売上影響**: CTRが著しく低下し、Google評価にも悪影響があります。\n"
                f"**確認ログ**: `logs/audit_feedback.jsonl` でタイトルを確認し、"
                f"対象記事を下書きに戻すかリライトしてください。"
            ),
            "channel": CHANNEL_CRITICAL,
            "agent": None,
        })

    # C4: HARD_FAIL多発（サーナイト）
    gardevoir = agents.get("gardevoir_hook_critic", {})
    g_fail = gardevoir.get("gardevoir_fail", gardevoir.get("hard_fail_count", 0))
    g_total = gardevoir.get("gardevoir_total", gardevoir.get("total_count", 0))
    if g_fail >= 10:
        fail_rate = g_fail / g_total if g_total > 0 else 0
        alerts.append({
            "rule": "C4_hard_fail_surge",
            "event_key": _make_event_key("C4_hard_fail_surge", "gardevoir_hook_critic"),
            "title": "🚨 サーナイト HARD_FAIL 多発",
            "body": (
                f"**品質ゲート（サーナイト）のHARD_FAILが多発しています。**\n\n"
                f"- HARD_FAIL: {g_fail}件 / 全{g_total}件（{fail_rate:.0%}）\n"
                f"- SCORE ERRORの場合: フォーマット不正によるパース失敗も含む\n\n"
                f"**売上影響**: 記事がパイプラインを通過できず投稿0になる連鎖リスクがあります。\n"
                f"**確認ログ**: `logs/gardevoir_hook.jsonl` でHARD_FAILタイトルを確認。\n"
                f"**対策**: `config/auto_directives.json` のSCOREフォーマット制約を確認してください。"
            ),
            "channel": CHANNEL_CRITICAL,
            "agent": "サーナイト",
        })

    # C5: 売上直結エージェント停止
    for agent_id, agent_name in REVENUE_CRITICAL_AGENTS.items():
        a = agents.get(agent_id, {})
        a_rate = a.get("success_rate", 1.0)
        a_total = a.get("total_count", 0)
        a_status = a.get("status", "")
        if (a_total >= 2 and a_rate < 0.60) or a_status == "停止":
            alerts.append({
                "rule": f"C5_revenue_agent_down",
                "event_key": _make_event_key("C5_revenue_agent_down", agent_id),
                "title": f"🚨 売上直結エージェント異常: {a.get('name_ja', agent_name)}",
                "body": (
                    f"**{agent_name}が正常に稼働していません。**\n\n"
                    f"- 成功率: {a_rate:.0%}（実行{a_total}回）\n"
                    f"- ステータス: {a_status}\n\n"
                    f"**売上影響**: このエージェントの停止は直接的な収益損失につながります。\n"
                    f"**確認ログ**: `logs/pipeline.jsonl` で `step={agent_id}` のエラーを確認。"
                ),
                "channel": CHANNEL_REVENUE,
                "agent": agent_id,
            })

    # C6: 本文AI混入検出
    contaminated_agents = [
        (k, v) for k, v in agents.items()
        if v.get("contamination_count", 0) > 0 and k != "pipeline"
    ]
    if contaminated_agents:
        lines = "\n".join(
            f"  - {v['name_ja']}（{v['contamination_count']}件）"
            for k, v in contaminated_agents[:5]
        )
        alerts.append({
            "rule": "C6_body_contamination",
            "event_key": _make_event_key("C6_body_contamination", contaminated_agents[0][0]),
            "title": "🚨 本文AI混入を検出",
            "body": (
                f"**記事本文にAI応答文・修正メモが混入しています。**\n\n"
                f"検出エージェント:\n{lines}\n\n"
                f"**売上影響**: Googleに「低品質コンテンツ」と判定されSEO評価が下がります。\n"
                f"**確認ログ**: `logs/audit_feedback.jsonl` と `logs/pipeline.jsonl` を確認。\n"
                f"**対策**: `config/auto_directives.json` に本文汚染禁止制約を追加してください。"
            ),
            "channel": CHANNEL_CRITICAL,
            "agent": None,
        })

    # C7: 今日の記事投稿0件（12時以降）
    now = datetime.now(JST)
    if now.hour >= 12:
        today_posts = summary.get("today_posts", -1)
        if today_posts == 0:
            date_key = now.strftime("%Y%m%d")
            alerts.append({
                "rule": "C7_zero_posts_today",
                "event_key": _make_event_key("C7_zero_posts_today", None, date_key),
                "title": "🚨 本日の記事投稿が0件（12時以降）",
                "body": (
                    f"**本日 {now.strftime('%m/%d')} の記事投稿が1件もありません。**\n\n"
                    f"- 現在時刻: {now.strftime('%H:%M JST')}\n"
                    f"- 今週の投稿数: {summary.get('week_posts', '不明')}件\n\n"
                    f"**売上影響**: 投稿0日は検索流入・収益の急落につながります。\n"
                    f"**確認ログ**: `logs/pipeline.jsonl` でパイプラインが起動しているか確認。\n"
                    f"**対策**: `bash kpop_pipeline.sh` で手動実行してください。"
                ),
                "channel": CHANNEL_CRITICAL,
                "agent": None,
            })

    return alerts


# ─────────────────────────────────────────────────────────────
# WARNINGアラート判定
# ─────────────────────────────────────────────────────────────

def check_warning(metrics: dict, revenue: dict, summary: dict) -> list[dict]:
    warnings = []
    agents = metrics.get("agents", {})

    # W1: CORE/INFRAが長期未実行
    sabori_agents = [
        (k, v) for k, v in agents.items()
        if v.get("sabori_flag") and v.get("total_count", 0) == 0
           and v.get("role_class") in ("CORE", "INFRA")
    ]
    if sabori_agents:
        lines = "\n".join(
            f"  - {v['name_ja']}（{v['role_class']} / 最終実行: {_fmt_age(v.get('hours_since_last_run',9999))}前）"
            for k, v in sabori_agents[:5]
        )
        warnings.append({
            "rule": "W1_sabori_core",
            "event_key": _make_event_key("W1_sabori_core", sabori_agents[0][0]),
            "title": "⚠️ CORE/INFRAエージェントが長期未実行",
            "body": (
                f"**以下のCORE担当エージェントが48時間以上実行されていません。**\n\n"
                f"{lines}\n\n"
                f"**確認**: cronスケジュール・pipeline定義を確認してください。\n"
                f"**参考**: `bash run_agent_monitor.sh` で最新状態を確認できます。"
            ),
        })

    # W2: 空出力増加
    empty_agents = [
        (k, v) for k, v in agents.items()
        if 1 <= v.get("empty_output_count", 0) < 3 and v.get("role_class") in ("CORE", "INFRA")
    ]
    if empty_agents:
        lines = "\n".join(
            f"  - {v['name_ja']}（空出力 {v['empty_output_count']}回）"
            for k, v in empty_agents[:5]
        )
        warnings.append({
            "rule": "W2_empty_output_growing",
            "event_key": _make_event_key("W2_empty_output_growing", empty_agents[0][0]),
            "title": "⚠️ 空出力が増加中",
            "body": (
                f"**以下のエージェントで空出力が発生しています（まだ軽微）。**\n\n"
                f"{lines}\n\n"
                f"**放置するとサボりフラグ（3回以上）でpipelineが停止します。**\n"
                f"**対策**: プロンプトに最小文字数とフォールバック出力テンプレートを追加してください。"
            ),
        })

    # W3: 成功率注意域（60〜85%）
    warn_rate_agents = [
        (k, v) for k, v in agents.items()
        if 0.60 <= v.get("success_rate", 1.0) < 0.85
           and v.get("total_count", 0) >= 5
           and v.get("role_class") not in ("DEPRECATED",)
    ]
    if warn_rate_agents:
        lines = "\n".join(
            f"  - {v['name_ja']}（{v['success_rate']:.0%} / {v['total_count']}回）"
            for k, v in warn_rate_agents[:5]
        )
        warnings.append({
            "rule": "W3_success_rate_decline",
            "event_key": _make_event_key("W3_success_rate_decline", warn_rate_agents[0][0]),
            "title": "⚠️ 成功率が注意域のエージェントあり",
            "body": (
                f"**以下のエージェントの成功率が60〜85%（注意域）にあります。**\n\n"
                f"{lines}\n\n"
                f"**対策**: 出力フォーマット制約の強化を検討してください。\n"
                f"**参考**: `optimization_actions.json` の改善提案を確認してください。"
            ),
        })

    # W4: CTA未設置記事
    cta_rate = revenue.get("summary", {}).get("cta_rate", 1.0)
    total_articles = revenue.get("summary", {}).get("total_articles", 0)
    if cta_rate < 0.90 and total_articles >= 5:
        no_cta_count = round(total_articles * (1 - cta_rate))
        warnings.append({
            "rule": "W4_no_cta",
            "event_key": _make_event_key("W4_no_cta", None, ""),
            "title": "⚠️ CTA未設置記事あり（CVR低下リスク）",
            "body": (
                f"**記事のCTA設置率が{cta_rate:.0%}です（目標: 100%）。**\n\n"
                f"- 未設置推定: 約{no_cta_count}件 / 全{total_articles}件\n\n"
                f"**売上影響**: CTAなし記事はアフィリエイト・メルマガ登録の機会を失います。\n"
                f"**対策**: カイリュー（CVR最適化）のCTA挿入ロジックを確認してください。"
            ),
        })

    # W5: サムネイル未設置
    thumb_rate = revenue.get("summary", {}).get("thumbnail_rate", 1.0)
    if thumb_rate < 0.98 and total_articles >= 5:
        no_thumb_count = round(total_articles * (1 - thumb_rate))
        warnings.append({
            "rule": "W5_no_thumbnail",
            "event_key": _make_event_key("W5_no_thumbnail", None, ""),
            "title": "⚠️ サムネイル未設置記事あり（CTR低下リスク）",
            "body": (
                f"**記事のサムネイル設置率が{thumb_rate:.0%}です。**\n\n"
                f"- 未設置推定: 約{no_thumb_count}件\n\n"
                f"**売上影響**: サムネなし記事はGoogle検索・SNSでのCTRが著しく低下します。\n"
                f"**対策**: `bash post_audit.sh` でサムネイル自動生成を実行してください。"
            ),
        })

    # W6: 全体成功率低下
    overall_rate = metrics.get("summary", {}).get("overall_success_rate", 1.0)
    if 0.70 <= overall_rate < 0.85:
        warnings.append({
            "rule": "W6_overall_rate_decline",
            "event_key": _make_event_key("W6_overall_rate_decline", None, ""),
            "title": "⚠️ 全体成功率が低下しています",
            "body": (
                f"**AI組織全体の平均成功率が{overall_rate:.0%}です（目標: 85%以上）。**\n\n"
                f"- CRITICAL(要改善): {metrics.get('summary',{}).get('critical_agents',0)}エージェント\n"
                f"- WARNING(注意):    {metrics.get('summary',{}).get('warning_agents',0)}エージェント\n\n"
                f"**確認**: `dashboard.html` でエージェント別の詳細を確認してください。"
            ),
        })

    return warnings


# ─────────────────────────────────────────────────────────────
# テスト送信
# ─────────────────────────────────────────────────────────────

def run_test_critical() -> dict:
    """CRITICALチャネルへテスト送信（抑制なし・1件のみ）"""
    event_key = "TEST_critical__test"
    title = "🚨 [テスト送信] CRITICAL通知の動作確認"
    body = (
        "**これはCRITICAL通知のテスト送信です。**\n\n"
        "- チャネル: `urgent_errors`\n"
        "- 目的: Webhook接続・表示の確認\n"
        "- 本番異常ではありません\n\n"
        "**テスト項目**:\n"
        "  ✅ Webhook到達確認\n"
        "  ✅ embed表示確認\n"
        "  ✅ footerのevent_key表示確認\n\n"
        "このメッセージが届いていれば urgent_errors チャネルは正常です。"
    )
    result, detail = _do_send(CHANNEL_CRITICAL, title, body, COLOR_TEST, event_key)
    _record_history(event_key, "CRITICAL", "TEST", CHANNEL_CRITICAL, title, result, detail)
    print(f"  [test-critical] channel={CHANNEL_CRITICAL} result={result}", file=sys.stderr)
    if result != "sent":
        print(f"  [test-critical] detail: {detail}", file=sys.stderr)
        from lib.alert_queue import enqueue
        enqueue("CRITICAL", CHANNEL_CRITICAL, title, body, COLOR_TEST, event_key, "TEST", f"{result}: {detail}")
    return {"result": result, "detail": detail, "channel": CHANNEL_CRITICAL}


def run_test_warning() -> dict:
    """WARNINGチャネルへテスト送信（抑制なし・1件のみ）"""
    event_key = "TEST_warning__test"
    title = "⚠️ [テスト送信] WARNING通知の動作確認"
    body = (
        "**これはWARNING通知のテスト送信です。**\n\n"
        "- チャネル: `alert_summary`\n"
        "- 目的: Webhook接続・表示の確認\n"
        "- 本番異常ではありません\n\n"
        "**設定確認チェックリスト**:\n"
        "  ✅ Webhook到達確認\n"
        "  ✅ embed表示確認（オレンジ色）\n"
        "  ✅ footerのevent_key表示確認\n\n"
        "このメッセージが届いていれば alert_summary チャネルは正常です。\n"
        "`config/discord_webhooks.json` の `alert_summary` が設定済みです。"
    )
    result, detail = _do_send(CHANNEL_WARNING, title, body, COLOR_TEST, event_key)
    _record_history(event_key, "WARNING", "TEST", CHANNEL_WARNING, title, result, detail)
    print(f"  [test-warning] channel={CHANNEL_WARNING} result={result}", file=sys.stderr)
    if result != "sent":
        print(f"  [test-warning] detail: {detail}", file=sys.stderr)
        from lib.alert_queue import enqueue
        enqueue("WARNING", CHANNEL_WARNING, title, body, COLOR_TEST, event_key, "TEST", f"{result}: {detail}")
    return {"result": result, "detail": detail, "channel": CHANNEL_WARNING}


# ─────────────────────────────────────────────────────────────
# Webhook設定状況確認
# ─────────────────────────────────────────────────────────────

def print_webhook_status():
    """全チャネルのWebhook設定状況を表示"""
    print("\n=== Discord Webhook 設定状況 ===")
    if not CONFIG_PATH.exists():
        print(f"  ❌ {CONFIG_PATH} が見つかりません")
        return
    try:
        d = json.loads(CONFIG_PATH.read_text())
    except Exception as e:
        print(f"  ❌ 読み込みエラー: {e}")
        return

    required = {
        CHANNEL_CRITICAL: "CRITICAL通知（必須）",
        CHANNEL_WARNING:  "WARNING通知（推奨）",
        CHANNEL_REVENUE:  "売上異常通知（推奨）",
    }
    for ch, desc in required.items():
        url = _expand_webhook(d.get(ch, ""))
        if url:
            print(f"  ✅ {ch:<25} {desc}")
        else:
            print(f"  ❌ {ch:<25} {desc} ← 未設定（通知スキップ）")

    print()
    # M11.5.B: メタキー(_comment 等、_ 始まり)は走査対象外。
    other_channels = [k for k in d if k not in required and not k.startswith("_")]
    if other_channels:
        print("  その他チャネル（参考）:")
        for ch in other_channels:
            url = _expand_webhook(d.get(ch, ""))
            status = "✅" if url else "—"
            print(f"    {status} {ch}")

    # WARNING未設定の場合は明示的に警告
    if not _expand_webhook(d.get(CHANNEL_WARNING, "")):
        print()
        print("  ⚠️  WARNING通知チャネル（alert_summary）が未設定です。")
        print("     W1〜W6のWARNINGアラートが送信されません。")
        print("     設定方法: Discordサーバーで新しいWebhookを作成し、")
        print(f'     config/discord_webhooks.json の "alert_summary" にURLを設定してください。')
    print()


# ─────────────────────────────────────────────────────────────
# メイン実行
# ─────────────────────────────────────────────────────────────

def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def run(dry_run: bool = False, summary_only: bool = False) -> dict:
    """
    通知判定・送信を実行。

    Returns:
        {
            "sent": int,          # 送信成功件数
            "suppressed": int,    # 抑制件数
            "skipped": int,       # Webhook未設定スキップ件数
            "failed": int,        # 送信失敗件数（403/404/network等）
            "alerts": list[dict], # 全アラート詳細
        }
    """
    metrics = load_json(METRICS_PATH)
    revenue = load_json(REVENUE_PATH)
    summary = load_json(SUMMARY_PATH)

    result = {"sent": 0, "suppressed": 0, "skipped": 0, "failed": 0, "alerts": []}

    def _tally(send_result: str):
        if send_result == "sent":
            result["sent"] += 1
        elif send_result == "suppressed":
            result["suppressed"] += 1
        elif send_result == "webhook_not_set":
            result["skipped"] += 1
        elif send_result == "dry_run":
            pass
        else:
            result["failed"] += 1

    if not summary_only:
        critical_alerts = check_critical(metrics, revenue, summary)
        for alert in critical_alerts:
            channel = alert.get("channel", CHANNEL_CRITICAL)
            color = COLOR_WARNING if channel == CHANNEL_REVENUE else COLOR_CRITICAL
            sr = send_discord(
                channel, alert["title"], alert["body"], color,
                alert["event_key"], "CRITICAL", dry_run,
            )
            _tally(sr)
            result["alerts"].append({
                "rule":      alert["rule"],
                "event_key": alert["event_key"],
                "title":     alert["title"],
                "severity":  "CRITICAL",
                "channel":   channel,
                "result":    sr,
            })

    # WARNING: まとめて1通
    warning_alerts = check_warning(metrics, revenue, summary)
    if warning_alerts:
        # まとめ通知のevent_keyは全ルールIDの連結（抑制キーとして機能）
        combined_key = _make_event_key("W_batch", None, "_".join(w["rule"] for w in warning_alerts))
        combined_title = f"⚠️ 定期監視レポート — {len(warning_alerts)}件の注意事項"
        combined_parts = []
        for i, w in enumerate(warning_alerts, 1):
            combined_parts.append(f"**[{i}] {w['title'].replace('⚠️ ', '')}**\n{w['body']}")
        combined_body = "\n\n---\n\n".join(combined_parts)
        combined_body += "\n\n---\n📊 詳細は `dashboard.html` または `agent_metrics.json` を確認してください。"

        sr = send_discord(
            CHANNEL_WARNING, combined_title, combined_body, COLOR_WARNING,
            combined_key, "WARNING", dry_run,
        )
        _tally(sr)
        for w in warning_alerts:
            result["alerts"].append({
                "rule":      w["rule"],
                "event_key": w["event_key"],
                "title":     w["title"],
                "severity":  "WARNING",
                "channel":   CHANNEL_WARNING,
                "result":    sr,
            })

    return result


def print_rule_table():
    print("""
╔══════════════════════════════════════════════════════════════════════════════╗
║      K-POP AI会社 Discord通知ルール一覧 v2.0                                 ║
╠══════════════╦═════════════════════════════════╦════════════╦═══════════════╣
║ ルールID     ║ 条件                            ║ severity   ║ 抑制時間      ║
╠══════════════╬═════════════════════════════════╬════════════╬═══════════════╣
║ C1           ║ パイプライン成功率0%（実行あり） ║ CRITICAL   ║ 30分          ║
║ C2           ║ WP投稿成功率 < 80%（3回以上）   ║ CRITICAL   ║ 30分          ║
║ C3           ║ タイトル崩壊記事を検出          ║ CRITICAL   ║ 30分          ║
║ C4           ║ HARD_FAIL 10件以上              ║ CRITICAL   ║ 30分          ║
║ C5           ║ 売上直結エージェント停止/低率    ║ CRITICAL   ║ 30分          ║
║ C6           ║ 本文AI混入を検出                ║ CRITICAL   ║ 30分          ║
║ C7           ║ 本日投稿0件（12時以降）          ║ CRITICAL   ║ 30分          ║
╠══════════════╬═════════════════════════════════╬════════════╬═══════════════╣
║ W1           ║ CORE/INFRA 48h以上未実行        ║ WARNING    ║ 6時間         ║
║ W2           ║ 空出力1〜2回（増加傾向）         ║ WARNING    ║ 6時間         ║
║ W3           ║ 成功率 60〜85%（注意域）         ║ WARNING    ║ 6時間         ║
║ W4           ║ CTA設置率 < 90%                 ║ WARNING    ║ 6時間         ║
║ W5           ║ サムネイル設置率 < 98%           ║ WARNING    ║ 6時間         ║
║ W6           ║ 全体成功率 70〜85%              ║ WARNING    ║ 6時間         ║
╠══════════════╬═════════════════════════════════╬════════════╬═══════════════╣
║ INFO (全て) ║ 上記以外の状態変化              ║ INFO       ║ 通知なし      ║
╚══════════════╩═════════════════════════════════╩════════════╩═══════════════╝

【チャネル対応表】
  urgent_errors      → CRITICAL 即時送信（パイプライン停止・タイトル崩壊等）
  sales_monetization → 売上直結エージェント異常（C5専用）
  alert_summary      → WARNING まとめ通知（1通/6時間・ノイズ削減）
  dashboard.html     → INFO はダッシュボードのみ更新

【重複抑制ログ】
  logs/discord_alert_history.jsonl に全送信・抑制・失敗を記録
  event_key形式: "rule_id__対象識別子"  例: "C3_title_collapse__2555"
""")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI会社 Discord通知システム v2.0")
    parser.add_argument("--dry-run",       action="store_true", help="判定のみ（送信しない）")
    parser.add_argument("--summary",       action="store_true", help="WARNINGまとめ通知のみ")
    parser.add_argument("--test-critical", action="store_true", help="CRITICALテスト送信（1件・抑制なし）")
    parser.add_argument("--test-warning",  action="store_true", help="WARNINGテスト送信（1件・抑制なし）")
    parser.add_argument("--rules",         action="store_true", help="通知ルール一覧を表示")
    parser.add_argument("--status",        action="store_true", help="Webhook設定状況を確認")
    args = parser.parse_args()

    if args.rules:
        print_rule_table()
        sys.exit(0)

    if args.status:
        print_webhook_status()
        sys.exit(0)

    if args.test_critical:
        print("[discord_notifier v2.0] CRITICALテスト送信...", file=sys.stderr)
        res = run_test_critical()
        print(f"  result: {res['result']}", file=sys.stderr)
        if res["detail"]:
            print(f"  detail: {res['detail']}", file=sys.stderr)
        sys.exit(0 if res["result"] == "sent" else 1)

    if args.test_warning:
        print("[discord_notifier v2.0] WARNINGテスト送信...", file=sys.stderr)
        res = run_test_warning()
        print(f"  result: {res['result']}", file=sys.stderr)
        if res["detail"]:
            print(f"  detail: {res['detail']}", file=sys.stderr)
        sys.exit(0 if res["result"] == "sent" else 1)

    print("[discord_notifier v2.0] 異常判定開始...", file=sys.stderr)
    result = run(dry_run=args.dry_run, summary_only=args.summary)

    # 標準エラーへ詳細サマリー
    print(f"  送信成功: {result['sent']}件", file=sys.stderr)
    print(f"  抑制:     {result['suppressed']}件", file=sys.stderr)
    print(f"  未設定スキップ: {result['skipped']}件", file=sys.stderr)
    if result["failed"] > 0:
        print(f"  ❌ 送信失敗: {result['failed']}件（上記エラー詳細を確認してください）", file=sys.stderr)

    if args.dry_run:
        print("\n[DRY-RUN 判定結果]")
        for a in result["alerts"]:
            icon = "🚨" if a["severity"] == "CRITICAL" else "⚠️"
            print(f"  {icon} [{a['severity']}] {a['rule']} key={a['event_key']}")

    # stdout へ機械読み取り用サマリーJSON（run_agent_monitor.sh から grep 可能）
    summary_line = json.dumps({
        "notifier": "v2.0",
        "sent": result["sent"],
        "suppressed": result["suppressed"],
        "skipped": result["skipped"],
        "failed": result["failed"],
    }, ensure_ascii=False)
    print(summary_line)

    print("[discord_notifier v2.0] 完了", file=sys.stderr)
