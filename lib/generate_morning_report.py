#!/usr/bin/env python3
"""
generate_morning_report.py — オーナー向けモーニングレポート生成・送信

毎朝の朝会データ + 自律実行ログを集約し、オーナーが5秒で状況把握できる
レポートを生成して Discord の daily_ceo_report チャネルに送信する。

Usage:
  python3 lib/generate_morning_report.py            # 生成＋Discord送信
  python3 lib/generate_morning_report.py --dry-run  # stdout出力のみ（送信しない）
  python3 lib/generate_morning_report.py --date 2026-04-21
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
TEMPLATE_PATH = BASE_DIR / "templates" / "owner_morning_report.md"
STANDUP_DIR = BASE_DIR / "data" / "meetings" / "general"
AUTONOMY_LOG = BASE_DIR / "logs" / "autonomy_executions.jsonl"
METRICS_PATH = BASE_DIR / "agent_metrics.json"
POSTS_LOG = BASE_DIR / "logs" / "kpi_posts.jsonl"

JST = timezone(timedelta(hours=9))


def _load_template() -> str:
    """Load the Mustache-style template."""
    if not TEMPLATE_PATH.exists():
        print(f"[morning-report] テンプレートが見つかりません: {TEMPLATE_PATH}", file=sys.stderr)
        sys.exit(1)
    return TEMPLATE_PATH.read_text(encoding="utf-8")


def _find_latest_standup(target_date: str) -> Path | None:
    """Find the standup file for target_date or the most recent one."""
    target_file = STANDUP_DIR / f"standup_{target_date}.md"
    if target_file.exists():
        return target_file
    # Fallback: find most recent
    standups = sorted(STANDUP_DIR.glob("standup_*.md"), reverse=True)
    return standups[0] if standups else None


def _parse_standup(standup_path: Path) -> dict:
    """Extract key metrics from standup markdown."""
    content = standup_path.read_text(encoding="utf-8")
    data = {
        "articles_count": 0,
        "error_count": 0,
        "success_rate": 0,
        "active_agents": 0,
        "green_agents": 0,
        "yellow_agents": 0,
        "red_agents": 0,
        "error_agents": [],
    }

    # Parse post count
    m = re.search(r"投稿数\s*\|\s*(\d+)\s*件", content)
    if m:
        data["articles_count"] = int(m.group(1))

    # Parse error count
    m = re.search(r"エラー件数\s*\|\s*(\d+)\s*件", content)
    if m:
        data["error_count"] = int(m.group(1))

    # Parse success rate
    m = re.search(r"全社成功率\s*\|\s*([\d.]+)%", content)
    if m:
        data["success_rate"] = float(m.group(1))

    # Parse active agents
    m = re.search(r"アクティブ社員\s*\|\s*(\d+)", content)
    if m:
        data["active_agents"] = int(m.group(1))

    # Parse agent rankings
    m = re.search(r"優秀\(🟢\)\s*\|\s*(\d+)", content)
    if m:
        data["green_agents"] = int(m.group(1))
    m = re.search(r"要注意\(🟡\)\s*\|\s*(\d+)", content)
    if m:
        data["yellow_agents"] = int(m.group(1))
    m = re.search(r"危険\(🔴\)\s*\|\s*(\d+)", content)
    if m:
        data["red_agents"] = int(m.group(1))

    # Parse error-flagged agents
    for match in re.finditer(r"\*\*(.+?)\*\*\s*\(.+?\):\s*成功率\s*[\d.]+%", content):
        data["error_agents"].append(match.group(1))

    return data


def _load_autonomy_executions(target_date: str) -> dict:
    """Load and classify autonomy executions from JSONL log."""
    red_items = []
    yellow_items = []
    green_count = 0

    if not AUTONOMY_LOG.exists():
        return {"red_items": red_items, "yellow_items": yellow_items, "green_count": green_count}

    with open(AUTONOMY_LOG, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            # Filter by date
            ts = entry.get("timestamp", "")
            if not ts.startswith(target_date):
                continue

            level = entry.get("level", "green").lower()
            if level == "red":
                red_items.append({
                    "description": entry.get("description", "不明"),
                    "reason": entry.get("reason", "要確認"),
                })
            elif level == "yellow":
                yellow_items.append({
                    "description": entry.get("description", "不明"),
                    "result": entry.get("result", "処理済"),
                })
            else:
                green_count += 1

    return {"red_items": red_items, "yellow_items": yellow_items, "green_count": green_count}


def _count_today_planned() -> int:
    """Estimate today's planned article count from cron schedule."""
    # Based on crontab: kpop_pipeline x3 + beauty + strategy + lifestyle + comparison = 7 runs
    # Average ~1-2 articles per pipeline run
    return 7


def _render_template(template: str, data: dict) -> str:
    """Simple Mustache-like template rendering."""
    output = template

    # Simple variable substitution
    for key, value in data.items():
        if isinstance(value, (str, int, float)):
            output = output.replace("{{" + key + "}}", str(value))

    # Section rendering for red_items
    red_section_pattern = r"\{\{#red_items\}\}(.*?)\{\{/red_items\}\}"
    red_match = re.search(red_section_pattern, output, re.DOTALL)
    if red_match:
        item_template = red_match.group(1).strip()
        if data.get("red_items"):
            items_rendered = []
            for item in data["red_items"]:
                rendered = item_template
                rendered = rendered.replace("{{description}}", item.get("description", ""))
                rendered = rendered.replace("{{reason}}", item.get("reason", ""))
                items_rendered.append(rendered)
            output = output[:red_match.start()] + "\n".join(items_rendered) + output[red_match.end():]
        else:
            output = output[:red_match.start()] + "- なし（全て自律処理完了）" + output[red_match.end():]

    # Section rendering for yellow_items
    yellow_section_pattern = r"\{\{#yellow_items\}\}(.*?)\{\{/yellow_items\}\}"
    yellow_match = re.search(yellow_section_pattern, output, re.DOTALL)
    if yellow_match:
        item_template = yellow_match.group(1).strip()
        if data.get("yellow_items"):
            items_rendered = []
            for item in data["yellow_items"]:
                rendered = item_template
                rendered = rendered.replace("{{description}}", item.get("description", ""))
                rendered = rendered.replace("{{result}}", item.get("result", ""))
                items_rendered.append(rendered)
            output = output[:yellow_match.start()] + "\n".join(items_rendered) + output[yellow_match.end():]
        else:
            output = output[:yellow_match.start()] + "- なし" + output[yellow_match.end():]

    return output


def _send_to_discord(report: str) -> bool:
    """Send report to Discord daily_ceo_report channel."""
    try:
        sys.path.insert(0, str(SCRIPT_DIR))
        from discord_channel_router import send_to_channel, ChannelType
        results = send_to_channel(
            ChannelType.DAILY_REPORT,
            "☀️ オーナーモーニングレポート",
            report[:1900],  # Discord embed limit
        )
        for r in results:
            if r["result"] == "sent":
                print(f"[morning-report] Discord送信成功: {r['physical_channel']}")
                return True
            else:
                print(f"[morning-report] Discord送信失敗: {r['physical_channel']} -> {r['result']}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"[morning-report] Discord送信エラー: {e}", file=sys.stderr)
        return False


def generate_report(target_date: str) -> str:
    """Generate the full morning report."""
    template = _load_template()

    # Load standup data
    standup_path = _find_latest_standup(target_date)
    if standup_path:
        standup_data = _parse_standup(standup_path)
        print(f"[morning-report] 朝会データ読み込み: {standup_path.name}")
    else:
        standup_data = {
            "articles_count": 0, "error_count": 0,
            "success_rate": 0, "active_agents": 0,
            "green_agents": 0, "yellow_agents": 0, "red_agents": 0,
            "error_agents": [],
        }
        print("[morning-report] 朝会データなし — デフォルト値使用", file=sys.stderr)

    # Load autonomy executions
    autonomy_data = _load_autonomy_executions(target_date)

    # If no autonomy log, generate red/yellow from standup errors
    if not autonomy_data["red_items"] and not autonomy_data["yellow_items"] and standup_data["error_count"] > 0:
        # Treat pipeline errors as yellow (already happened, need review)
        autonomy_data["yellow_items"].append({
            "description": f"パイプラインエラー {standup_data['error_count']}件",
            "result": "ログ確認推奨",
        })
        # Treat critical agents as red if many
        critical_count = standup_data["red_agents"]
        if critical_count >= 5:
            autonomy_data["red_items"].append({
                "description": f"危険ランク社員 {critical_count}名",
                "reason": "成功率低下 — 設定見直し推奨",
            })

    # Build template data
    data = {
        "date": target_date,
        "red_count": len(autonomy_data["red_items"]),
        "yellow_count": len(autonomy_data["yellow_items"]),
        "green_count": autonomy_data["green_count"],
        "articles_count": standup_data["articles_count"],
        "pv_count": "—",  # PV requires GA integration, placeholder
        "today_planned": _count_today_planned(),
        "red_items": autonomy_data["red_items"],
        "yellow_items": autonomy_data["yellow_items"],
        "success_rate": f"{standup_data['success_rate']:.1f}",
        "active_agents": standup_data["active_agents"],
        "green_agents": standup_data["green_agents"],
        "yellow_agents": standup_data["yellow_agents"],
        "red_agents": standup_data["red_agents"],
    }

    return _render_template(template, data)


def main():
    parser = argparse.ArgumentParser(description="オーナーモーニングレポート生成")
    parser.add_argument("--date", default=datetime.now(JST).strftime("%Y-%m-%d"),
                        help="対象日 (default: today)")
    parser.add_argument("--dry-run", action="store_true",
                        help="stdout出力のみ（Discord送信しない）")
    args = parser.parse_args()

    report = generate_report(args.date)

    if args.dry_run:
        print(report)
        print("\n--- [DRY-RUN] Discord送信スキップ ---")
    else:
        # Save to file
        output_dir = BASE_DIR / "data" / "reports"
        output_dir.mkdir(parents=True, exist_ok=True)
        out_path = output_dir / f"morning_report_{args.date}.md"
        out_path.write_text(report, encoding="utf-8")
        print(f"[morning-report] レポート保存: {out_path}")

        # Send to Discord
        _send_to_discord(report)


if __name__ == "__main__":
    main()
