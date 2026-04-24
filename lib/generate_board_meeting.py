#!/usr/bin/env python3
"""
generate_board_meeting.py — 週次取締役会レポート生成
毎週月曜09:00にCEO（ミュウツー）主催で5部門の週次レビューを実施。

Usage:
  python3 lib/generate_board_meeting.py
  python3 lib/generate_board_meeting.py --date 2026-04-21
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
LOGS_DIR = BASE_DIR / "logs"
CONFIG_DIR = BASE_DIR / "config"
JST = timezone(timedelta(hours=9))

ORG_PATH = CONFIG_DIR / "organization.json"
METRICS_PATH = BASE_DIR / "agent_metrics.json"
ERROR_PATTERNS_PATH = CONFIG_DIR / "error_patterns.json"
GOOGLE_METRICS_PATH = BASE_DIR / "google_metrics" / "metrics_yesterday.json"
WEBHOOKS_PATH = CONFIG_DIR / "discord_webhooks.json"
STANDUP_BASE = LOGS_DIR / "standup" / "department"
BOARD_MEETING_DIR = LOGS_DIR / "board_meeting"

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("board_meeting")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> dict:
    if not path.exists():
        log.warning("ファイル未検出: %s", path)
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        log.error("JSON読み込みエラー %s: %s", path, e)
        return {}


def _week_dates(target_date: str) -> list[str]:
    """対象日を含む過去7日間の日付リスト。"""
    dt = datetime.strptime(target_date, "%Y-%m-%d")
    return [(dt - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]


def _load_week_standups(dept_name: str, week_dates: list[str]) -> list[dict]:
    """1部門の直近1週間分のスタンドアップを読み込む。"""
    standups = []
    for date_str in week_dates:
        path = STANDUP_BASE / date_str / f"{dept_name}.md"
        if path.exists():
            try:
                text = path.read_text(encoding="utf-8")
                standups.append({"date": date_str, "content": text})
            except OSError:
                continue
    return standups


def _count_unresolved_issues(error_patterns: dict) -> int:
    """未解決エラー件数。"""
    count = 0
    for key, pat in error_patterns.get("patterns", {}).items():
        if not pat.get("resolved_at"):
            count += 1
    return count


def _get_new_issues_this_week(error_patterns: dict, week_dates: list[str]) -> list[dict]:
    """今週新規発生したエラーパターン。"""
    issues = []
    earliest = min(week_dates)
    for key, pat in error_patterns.get("patterns", {}).items():
        last_seen = pat.get("last_seen", "")
        if last_seen >= earliest and not pat.get("resolved_at"):
            issues.append({
                "key": key,
                "example": pat.get("example", ""),
                "agent": pat.get("agent", "unknown"),
                "last_seen": last_seen,
            })
    return issues


def _extract_kpi_summary(metrics: dict, google_metrics: dict) -> dict:
    """各種メトリクスからKPIサマリを構築。"""
    summary = metrics.get("summary", {})
    ga4 = google_metrics.get("ga4", {}).get("summary", {})
    gsc = google_metrics.get("gsc", {}).get("summary", {})

    return {
        "overall_success_rate": summary.get("overall_success_rate", 0),
        "total_agents": summary.get("total_agents_defined", 0),
        "active_agents": summary.get("active_agents", 0),
        "excellent": summary.get("excellent_agents", 0),
        "warning": summary.get("warning_agents", 0),
        "critical": summary.get("critical_agents", 0),
        "sessions": ga4.get("sessions", "—"),
        "users": ga4.get("users", "—"),
        "pageviews": ga4.get("pageviews", "—"),
        "gsc_clicks": gsc.get("clicks", "—"),
        "gsc_impressions": gsc.get("impressions", "—"),
        "gsc_ctr": gsc.get("ctr", "—"),
    }


def _dept_week_summary(dept_name: str, standups: list[dict]) -> str:
    """部門の週次サマリを生成。"""
    if not standups:
        return f"スタンドアップ記録なし"

    lines = []
    lines.append(f"スタンドアップ記録: {len(standups)}日分")

    # 最新のスタンドアップから抜粋
    latest = standups[0]
    content = latest["content"]

    # メンバー稼働状況テーブルを抽出
    in_table = False
    table_lines = []
    for line in content.split("\n"):
        if "メンバー" in line and "成功率" in line:
            in_table = True
            continue
        if in_table:
            if line.startswith("|") and "---" not in line:
                table_lines.append(line.strip())
            elif not line.startswith("|"):
                in_table = False

    if table_lines:
        lines.append("最新メンバー状況:")
        for tl in table_lines:
            lines.append(f"  {tl}")

    # 課題抽出
    in_issues = False
    issue_lines = []
    for line in content.split("\n"):
        if "課題・ブロッカー" in line:
            in_issues = True
            continue
        if in_issues:
            if line.startswith("- "):
                issue_lines.append(line)
            elif line.startswith("##"):
                in_issues = False

    if issue_lines:
        lines.append("課題:")
        for il in issue_lines:
            lines.append(f"  {il}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Board meeting generation
# ---------------------------------------------------------------------------

def generate_board_meeting(target_date: str) -> str:
    """週次取締役会レポートを生成。"""
    org = _load_json(ORG_PATH)
    metrics = _load_json(METRICS_PATH)
    error_patterns = _load_json(ERROR_PATTERNS_PATH)
    google_metrics = _load_json(GOOGLE_METRICS_PATH)

    if not org or "departments" not in org:
        log.error("organization.json が読み込めません")
        return "# ERROR: organization.json が読み込めません"

    week_dates = _week_dates(target_date)
    kpi_summary = _extract_kpi_summary(metrics, google_metrics)
    unresolved_count = _count_unresolved_issues(error_patterns)
    new_issues = _get_new_issues_this_week(error_patterns, week_dates)

    # 週番号
    dt = datetime.strptime(target_date, "%Y-%m-%d")
    week_num = dt.isocalendar()[1]

    lines = [
        f"# 週次取締役会 — {target_date}（第{week_num}週）",
        f"**議長**: ミュウツー（CEO）",
        f"**出席**: 各部門長 + CEO",
        f"**対象期間**: {week_dates[-1]} 〜 {week_dates[0]}",
        "",
        "---",
        "",
        "## 1. 前週KPI達成状況",
        "",
        "| 指標 | 値 |",
        "|------|-----|",
        f"| 全社成功率 | {kpi_summary['overall_success_rate']:.1%} |",
        f"| 定義済社員数 | {kpi_summary['total_agents']} |",
        f"| アクティブ社員 | {kpi_summary['active_agents']} |",
        f"| 優秀(🟢) | {kpi_summary['excellent']} |",
        f"| 要注意(🟡) | {kpi_summary['warning']} |",
        f"| 危険(🔴) | {kpi_summary['critical']} |",
        f"| GA4セッション | {kpi_summary['sessions']} |",
        f"| GA4ユーザー | {kpi_summary['users']} |",
        f"| GA4ページビュー | {kpi_summary['pageviews']} |",
        f"| GSCクリック数 | {kpi_summary['gsc_clicks']} |",
        f"| GSC表示回数 | {kpi_summary['gsc_impressions']} |",
        f"| GSC CTR | {kpi_summary['gsc_ctr']} |",
        f"| 未解決エラー | {unresolved_count} 件 |",
        "",
    ]

    # 2. 各部署報告
    lines.extend([
        "## 2. 各部署報告",
        "",
    ])

    for dept_key, dept_config in org["departments"].items():
        dept_name = dept_config["name"]
        icon = dept_config.get("icon", "")
        manager = dept_config["manager"]
        standups = _load_week_standups(dept_name, week_dates)
        summary = _dept_week_summary(dept_name, standups)

        lines.extend([
            f"### {icon} {dept_name}（部長: {manager['name']}）",
            "",
            summary,
            "",
            "KPI:",
            "",
        ])
        for kpi in dept_config.get("kpis", []):
            lines.append(f"- {kpi}")
        lines.append("")

    # 3. 新規課題
    lines.extend([
        "## 3. 新規課題",
        "",
    ])
    if new_issues:
        for issue in new_issues:
            lines.append(f"- **{issue['key']}**: {issue['example']}（担当: {issue['agent']}, 検出: {issue['last_seen']}）")
    else:
        lines.append("- 今週の新規課題なし")
    lines.append("")

    # 4. 決定事項
    lines.extend([
        "## 4. 決定事項",
        "",
    ])
    if unresolved_count > 0:
        lines.append(f"- 未解決エラー {unresolved_count} 件の優先順位付けと対応方針を各部長が策定")
    if new_issues:
        lines.append(f"- 新規課題 {len(new_issues)} 件を担当部署に振り分け、次週までに対応完了を目指す")
    lines.append("- 各部門KPIのモニタリングを継続し、異常値には即時対応")
    lines.append("- パイプライン安定性と品質の両立を維持")
    lines.append("")

    # 5. 次週方針
    lines.extend([
        "## 5. 次週方針",
        "",
        "- 全社成功率の維持・向上（目標: 80%以上）",
        "- 品質ゲートのバランス調整（過剰BLOCKの防止）",
        "- GSCインデックス率の改善推進",
        "- 収益KPI（AdSense/アフィリエイト）の最適化継続",
        f"- 未解決課題 {unresolved_count} 件の計画的解消",
        "",
        "---",
        f"*自動生成: {datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S')} JST*",
    ])

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Discord notification
# ---------------------------------------------------------------------------

def _send_to_discord(webhook_url: str, title: str, body: str, color: int = 0x6366f1) -> bool:
    """Discord Webhookへ送信。"""
    if len(body) > 2000:
        body = body[:1997] + "..."

    payload = {
        "embeds": [{
            "title": title,
            "description": body,
            "color": color,
            "timestamp": datetime.now(JST).isoformat(),
        }]
    }
    try:
        resp = requests.post(webhook_url, json=payload, timeout=15)
        if resp.status_code in (200, 204):
            log.info("Discord送信成功: %s", title)
            return True
        else:
            log.warning("Discord送信失敗 [%d]: %s", resp.status_code, resp.text[:200])
            return False
    except requests.RequestException as e:
        log.error("Discord送信エラー: %s", e)
        return False


def _build_board_discord_summary(target_date: str, kpi_summary: dict,
                                  unresolved: int, new_issues: int, dept_count: int) -> str:
    """Discord用の取締役会サマリ。"""
    lines = [
        f"**議長**: ミュウツー（CEO）",
        f"**対象期間**: 過去7日間",
        "",
        f"**全社成功率**: {kpi_summary['overall_success_rate']:.1%}",
        f"**アクティブ社員**: {kpi_summary['active_agents']}/{kpi_summary['total_agents']}",
        f"**GA4セッション**: {kpi_summary['sessions']}",
        f"**GSC CTR**: {kpi_summary['gsc_ctr']}",
        "",
        f"**部署報告**: {dept_count}部門",
        f"**未解決エラー**: {unresolved}件",
        f"**今週新規課題**: {new_issues}件",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="週次取締役会レポート生成")
    parser.add_argument("--date", default=datetime.now(JST).strftime("%Y-%m-%d"),
                        help="対象日 (default: today JST)")
    args = parser.parse_args()
    target_date = args.date

    log.info("週次取締役会レポート生成開始: %s", target_date)

    # レポート生成
    report = generate_board_meeting(target_date)

    # 保存
    BOARD_MEETING_DIR.mkdir(parents=True, exist_ok=True)
    dt = datetime.strptime(target_date, "%Y-%m-%d")
    week_num = dt.isocalendar()[1]
    year = dt.isocalendar()[0]
    out_path = BOARD_MEETING_DIR / f"{year}-W{week_num:02d}.md"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)
    log.info("保存: %s", out_path)

    # Discord送信
    webhooks = _load_json(WEBHOOKS_PATH)
    webhook_url = webhooks.get("weekly_board_report", "")

    if webhook_url:
        org = _load_json(ORG_PATH)
        metrics = _load_json(METRICS_PATH)
        error_patterns = _load_json(ERROR_PATTERNS_PATH)
        google_metrics = _load_json(GOOGLE_METRICS_PATH)

        kpi_summary = _extract_kpi_summary(metrics, google_metrics)
        unresolved = _count_unresolved_issues(error_patterns)
        new_issues = len(_get_new_issues_this_week(error_patterns, _week_dates(target_date)))
        dept_count = len(org.get("departments", {}))

        discord_body = _build_board_discord_summary(
            target_date, kpi_summary, unresolved, new_issues, dept_count
        )
        title = f"週次取締役会 — {target_date}（第{week_num}週）"
        _send_to_discord(webhook_url, title, discord_body)
    else:
        log.warning("Discord Webhook URL未設定（weekly_board_report）")

    log.info("週次取締役会レポート生成完了")
    print(f"[取締役会] レポートを {out_path} に保存しました")


if __name__ == "__main__":
    main()
