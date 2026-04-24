#!/usr/bin/env python3
"""
generate_department_standup.py — 部門別朝会スタンドアップ生成
毎朝07:30に全5部門のスタンドアップレポートを生成し、Discordへ送信。

Usage:
  python3 lib/generate_department_standup.py
  python3 lib/generate_department_standup.py --date 2026-04-21
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
PIPELINE_LOG = LOGS_DIR / "pipeline.jsonl"
ERROR_PATTERNS_PATH = CONFIG_DIR / "error_patterns.json"
WEBHOOKS_PATH = CONFIG_DIR / "discord_webhooks.json"

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("dept_standup")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> dict:
    """JSONファイルを安全に読み込む。"""
    if not path.exists():
        log.warning("ファイル未検出: %s", path)
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        log.error("JSON読み込みエラー %s: %s", path, e)
        return {}


def _load_jsonl_last24h(path: Path, ref_date: str) -> list[dict]:
    """pipeline.jsonl から直近24時間分を読み込む。"""
    entries: list[dict] = []
    if not path.exists():
        return entries
    ref_dt = datetime.strptime(ref_date, "%Y-%m-%d")
    cutoff = (ref_dt - timedelta(days=1)).isoformat()
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    ts = obj.get("timestamp", obj.get("date", obj.get("ts", "")))
                    if ts >= cutoff:
                        entries.append(obj)
                except json.JSONDecodeError:
                    continue
    except OSError as e:
        log.error("JSONL読み込みエラー %s: %s", path, e)
    return entries


def _get_active_issues(error_patterns: dict) -> list[dict]:
    """未解決のエラーパターンを抽出。"""
    issues = []
    patterns = error_patterns.get("patterns", {})
    for key, pat in patterns.items():
        if pat.get("resolved_at"):
            continue
        if pat.get("fix", "") == "調査が必要":
            issues.append({
                "key": key,
                "example": pat.get("example", ""),
                "agent": pat.get("agent", "unknown"),
                "last_seen": pat.get("last_seen", ""),
            })
    return issues


def _agent_metrics_for_dept(agents_data: dict, member_ids: list[str]) -> list[dict]:
    """部門メンバーのメトリクスを取得。"""
    results = []
    for mid in member_ids:
        info = agents_data.get(mid, {})
        if not info:
            # IDバリエーション試行
            for alt in [mid.replace("_kpop", ""), mid.replace("_hook_critic", "")]:
                if alt in agents_data:
                    info = agents_data[alt]
                    break
        results.append({
            "id": mid,
            "name": info.get("name_ja", mid),
            "success_rate": info.get("success_rate", 0),
            "rank": info.get("rank", "—"),
            "status": info.get("status", "不明"),
            "last_run": info.get("last_run_time", "—"),
        })
    return results


def _pipeline_stats_for_dept(pipeline_entries: list[dict], member_ids: list[str]) -> dict:
    """パイプラインログから部門関連の統計を抽出。"""
    total = 0
    success = 0
    errors = 0
    for entry in pipeline_entries:
        agent = entry.get("agent", "")
        if agent in member_ids or any(mid in agent for mid in member_ids):
            total += 1
            if entry.get("status") == "success" or entry.get("result") == "ok":
                success += 1
            if entry.get("status") == "error" or entry.get("error"):
                errors += 1
    return {"total": total, "success": success, "errors": errors}


# ---------------------------------------------------------------------------
# Department standup generation
# ---------------------------------------------------------------------------

def generate_department_standup(dept_key: str, dept_config: dict,
                                 agents_data: dict, pipeline_entries: list[dict],
                                 active_issues: list[dict], target_date: str) -> str:
    """1部門分のスタンドアップMarkdownを生成。"""
    yesterday = (datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    dept_name = dept_config["name"]
    manager = dept_config["manager"]
    members = dept_config["members"]
    kpis = dept_config.get("kpis", [])

    member_metrics = _agent_metrics_for_dept(agents_data, members)
    pipeline_stats = _pipeline_stats_for_dept(pipeline_entries, members)

    # 部門関連の未解決課題
    dept_issues = [i for i in active_issues
                   if i["agent"] in members or any(mid in i["agent"] for mid in members)]

    lines = [
        f"# {dept_name} 朝会スタンドアップ — {target_date}",
        f"**部長**: {manager['name']}（{manager['id']}）",
        f"**対象期間**: {yesterday} の実績",
        "",
        "---",
        "",
        "## 昨日の実績",
        "",
        f"| 指標 | 値 |",
        f"|------|-----|",
        f"| パイプライン実行数 | {pipeline_stats['total']} 件 |",
        f"| 成功数 | {pipeline_stats['success']} 件 |",
        f"| エラー数 | {pipeline_stats['errors']} 件 |",
        "",
        "### メンバー稼働状況",
        "",
        "| メンバー | 成功率 | ランク | ステータス |",
        "|----------|--------|--------|------------|",
    ]
    for m in member_metrics:
        rate_str = f"{m['success_rate']:.1%}" if isinstance(m['success_rate'], float) else str(m['success_rate'])
        lines.append(f"| {m['name']} | {rate_str} | {m['rank']} | {m['status']} |")

    lines.extend([
        "",
        "## 今日の予定",
        "",
        f"- 通常パイプライン実行（{dept_name}担当分）",
    ])
    for kpi in kpis[:3]:
        lines.append(f"- {kpi}の改善推進")

    lines.extend([
        "",
        "## 課題・ブロッカー",
        "",
    ])
    if dept_issues:
        for issue in dept_issues:
            lines.append(f"- **{issue['key']}**: {issue['example']}（最終検出: {issue['last_seen']}）")
    else:
        lines.append("- 現在ブロッカーなし")

    # 全社的な未解決課題のサマリ
    unresolved_count = len(active_issues)
    if unresolved_count > 0:
        lines.append(f"- 全社未解決課題: {unresolved_count} 件（詳細は error_patterns.json 参照）")

    lines.extend([
        "",
        "## 決定事項",
        "",
        f"- {dept_name}として本日も通常運用を継続",
    ])
    if pipeline_stats["errors"] > 0:
        lines.append(f"- 昨日のエラー {pipeline_stats['errors']} 件について原因調査・対応を実施")
    if dept_issues:
        lines.append(f"- 未解決課題 {len(dept_issues)} 件の優先対応を決定")

    lines.extend([
        "",
        "---",
        f"*自動生成: {datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S')} JST*",
    ])

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Discord notification
# ---------------------------------------------------------------------------

def _send_to_discord(webhook_url: str, title: str, body: str, color: int = 0x3498db) -> bool:
    """Discord Webhookへ送信。"""
    # Discord embed descriptionの2048文字制限対応
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


def _build_discord_summary(dept_name: str, pipeline_stats: dict,
                           member_metrics: list[dict], dept_issues: list[dict]) -> str:
    """Discord用の簡潔なサマリを生成。"""
    lines = [
        f"**パイプライン**: {pipeline_stats['total']}件 (成功: {pipeline_stats['success']}, エラー: {pipeline_stats['errors']})",
        "",
        "**メンバー状況**:",
    ]
    for m in member_metrics:
        rate_str = f"{m['success_rate']:.1%}" if isinstance(m['success_rate'], float) else str(m['success_rate'])
        lines.append(f"  {m['rank']} {m['name']}: {rate_str}")

    if dept_issues:
        lines.append("")
        lines.append(f"**課題**: {len(dept_issues)}件")
        for issue in dept_issues[:3]:
            lines.append(f"  - {issue['key']}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="部門別朝会スタンドアップ生成")
    parser.add_argument("--date", default=datetime.now(JST).strftime("%Y-%m-%d"),
                        help="対象日 (default: today JST)")
    args = parser.parse_args()
    target_date = args.date

    log.info("部門スタンドアップ生成開始: %s", target_date)

    # データ読み込み
    org = _load_json(ORG_PATH)
    if not org or "departments" not in org:
        log.error("organization.json が読み込めません")
        sys.exit(1)

    metrics = _load_json(METRICS_PATH)
    agents_data = metrics.get("agents", {})
    pipeline_entries = _load_jsonl_last24h(PIPELINE_LOG, target_date)
    error_patterns = _load_json(ERROR_PATTERNS_PATH)
    active_issues = _get_active_issues(error_patterns)
    webhooks = _load_json(WEBHOOKS_PATH)

    webhook_url = webhooks.get("daily_ceo_report", "")

    output_base = LOGS_DIR / "standup" / "department" / target_date
    output_base.mkdir(parents=True, exist_ok=True)

    all_summaries = []

    for dept_key, dept_config in org["departments"].items():
        dept_name = dept_config["name"]
        log.info("生成中: %s", dept_name)

        # Markdown生成
        md = generate_department_standup(
            dept_key, dept_config, agents_data,
            pipeline_entries, active_issues, target_date
        )

        # ファイル保存
        out_path = output_base / f"{dept_name}.md"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(md)
        log.info("保存: %s", out_path)

        # Discord用サマリ構築
        member_metrics = _agent_metrics_for_dept(agents_data, dept_config["members"])
        pipeline_stats = _pipeline_stats_for_dept(pipeline_entries, dept_config["members"])
        dept_issues = [i for i in active_issues
                       if i["agent"] in dept_config["members"]
                       or any(mid in i["agent"] for mid in dept_config["members"])]

        summary = _build_discord_summary(dept_name, pipeline_stats, member_metrics, dept_issues)
        all_summaries.append(f"## {dept_config.get('icon', '')} {dept_name}\n{summary}")

    # Discord送信（全部門まとめ）
    if webhook_url:
        discord_body = "\n\n".join(all_summaries)
        title = f"部門別朝会スタンドアップ — {target_date}"
        _send_to_discord(webhook_url, title, discord_body, color=0x818cf8)
    else:
        log.warning("Discord Webhook URL未設定（daily_ceo_report）")

    log.info("部門スタンドアップ生成完了: %d部門", len(org["departments"]))
    print(f"[部門スタンドアップ] {len(org['departments'])}部門のレポートを {output_base} に保存しました")


if __name__ == "__main__":
    main()
