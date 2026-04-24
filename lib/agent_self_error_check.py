#!/usr/bin/env python3
"""
agent_self_error_check.py — エージェント自己エラー認識システム

各エージェントが所有するエラーパターンを確認し、
未解決・再発パターンに対してゾーン分類→自動修正/通知/承認キューを実行する。

Usage:
  python3 lib/agent_self_error_check.py --agent eevee
  python3 lib/agent_self_error_check.py --all
  python3 lib/agent_self_error_check.py --all --dry-run
"""

import json
import sys
import argparse
import requests
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import defaultdict

BASE_DIR = Path(__file__).resolve().parent.parent
ERROR_OWNERSHIP_PATH = BASE_DIR / "config" / "error_ownership.json"
ERROR_PATTERNS_PATH = BASE_DIR / "config" / "error_patterns.json"
AGENT_METRICS_PATH = BASE_DIR / "agent_metrics.json"
AUTONOMY_MATRIX_PATH = BASE_DIR / "config" / "autonomy_matrix.json"
PIPELINE_LOG_PATH = BASE_DIR / "logs" / "pipeline.jsonl"
EXECUTIONS_LOG_PATH = BASE_DIR / "logs" / "autonomy_executions.jsonl"
APPROVAL_QUEUE_PATH = BASE_DIR / "logs" / "owner_approval_queue.jsonl"
DISCORD_WEBHOOKS_PATH = BASE_DIR / "config" / "discord_webhooks.json"


def _load_json(path, default=None):
    """JSON読み込み。ファイル不在・パースエラー時はdefaultを返す。"""
    if default is None:
        default = {}
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def _load_jsonl_recent(path, hours=24):
    """JSONL から直近N時間のエントリを読み込む。"""
    entries = []
    if not path.exists():
        return entries
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    ts_str = entry.get("timestamp", entry.get("ts", ""))
                    ts = _parse_ts(ts_str)
                    if ts and ts >= cutoff:
                        entries.append(entry)
                except (json.JSONDecodeError, KeyError):
                    continue
    except OSError:
        pass
    return entries


def _parse_ts(ts_str):
    """各種タイムスタンプ形式をdatetimeに変換。"""
    if not ts_str:
        return None
    for fmt in (
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(ts_str, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def _append_jsonl(path, entry):
    """JSONLファイルにエントリを追記。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _get_discord_webhook(webhook_key="urgent_errors"):
    """Discord webhook URLを取得。"""
    webhooks = _load_json(DISCORD_WEBHOOKS_PATH)
    return webhooks.get(webhook_key, "")


def _send_discord(message, webhook_key="urgent_errors"):
    """Discord通知を送信。"""
    url = _get_discord_webhook(webhook_key)
    if not url:
        return False
    try:
        resp = requests.post(url, json={
            "content": message[:2000],
            "username": "Agent Self-Check",
        }, timeout=10)
        return resp.status_code in (200, 204)
    except requests.RequestException:
        return False


def _get_owned_errors(agent_id):
    """指定エージェントが所有するエラーキーの一覧を返す。"""
    ownership = _load_json(ERROR_OWNERSHIP_PATH)
    owned = []
    for error_key, info in ownership.items():
        if error_key.startswith("_") or error_key == "updated_at":
            continue
        if not isinstance(info, dict):
            continue
        owner = info.get("owner", "")
        if isinstance(owner, list):
            if agent_id in owner:
                owned.append(error_key)
        elif owner == agent_id:
            owned.append(error_key)
    return owned


def _classify_zone(error_key, error_info):
    """エラーのゾーン分類: GREEN/YELLOW/RED。"""
    matrix = _load_json(AUTONOMY_MATRIX_PATH)
    if not matrix:
        return "RED"

    # 解決済みならGREEN（監視継続）
    if error_info.get("resolved_at"):
        return "GREEN"

    count = error_info.get("count", 0)

    # 高頻度の未解決はRED
    if count >= 10 and not error_info.get("resolved_at"):
        return "RED"

    # 再発パターン（解決後に再検出）はYELLOW
    if count >= 3:
        return "YELLOW"

    # 低頻度はGREEN
    return "GREEN"


def _determine_action(zone, error_key, error_info):
    """ゾーンに応じたアクションを決定。"""
    if zone == "GREEN":
        if error_info.get("resolved_at"):
            return "monitor_continue"
        return "auto_fix_proposal"
    elif zone == "YELLOW":
        return "notify_and_propose"
    else:
        return "queue_for_approval"


def check_agent_errors(agent_id, dry_run=False):
    """
    指定エージェントの所有エラーをチェックし、ゾーン分類→アクション実行。

    Returns:
        list of {error_key, zone, action, status}
    """
    owned_errors = _get_owned_errors(agent_id)
    error_patterns = _load_json(ERROR_PATTERNS_PATH)
    patterns = error_patterns.get("patterns", {})
    agent_metrics = _load_json(AGENT_METRICS_PATH)
    recent_pipeline = _load_jsonl_recent(PIPELINE_LOG_PATH, hours=24)

    # 直近のpipeline失敗をエージェント別に集計
    recent_failures = defaultdict(int)
    for entry in recent_pipeline:
        if entry.get("status") in ("error", "fail", "HARD_FAIL"):
            step = entry.get("step", "")
            recent_failures[step] += 1

    results = []
    now_iso = datetime.now(timezone.utc).isoformat()

    for error_key in owned_errors:
        error_info = patterns.get(error_key, {})
        if not error_info:
            # phase4_monitorsにある可能性
            monitors = error_patterns.get("phase4_monitors", {})
            error_info = monitors.get(error_key, {})

        zone = _classify_zone(error_key, error_info)
        action = _determine_action(zone, error_key, error_info)

        result = {
            "error_key": error_key,
            "zone": zone,
            "action": action,
            "status": "checked",
            "count": error_info.get("count", 0),
            "last_seen": error_info.get("last_seen", ""),
            "resolved_at": error_info.get("resolved_at", ""),
            "recent_pipeline_failures": recent_failures.get(agent_id, 0),
        }

        if dry_run:
            result["status"] = "dry_run"
            results.append(result)
            continue

        # ゾーン別アクション実行
        if zone == "GREEN" and action == "auto_fix_proposal":
            # 自動修正提案をログに記録
            _append_jsonl(EXECUTIONS_LOG_PATH, {
                "timestamp": now_iso,
                "agent": agent_id,
                "error_key": error_key,
                "zone": "GREEN",
                "action": "auto_fix_proposal",
                "description": f"エラー'{error_key}'の自動修正提案を生成（count={error_info.get('count', 0)}）",
            })
            result["status"] = "logged"

        elif zone == "GREEN" and action == "monitor_continue":
            # 監視継続（解決済み）
            result["status"] = "monitoring"

        elif zone == "YELLOW":
            # Discord通知 + 提案ログ
            msg = (
                f"**[Agent Self-Check] YELLOW ZONE**\n"
                f"エージェント: `{agent_id}`\n"
                f"エラー: `{error_key}` (count={error_info.get('count', 0)})\n"
                f"最終検出: {error_info.get('last_seen', 'N/A')}\n"
                f"対応: 修正提案を確認してください"
            )
            _send_discord(msg, "daily_ceo_report")
            _append_jsonl(EXECUTIONS_LOG_PATH, {
                "timestamp": now_iso,
                "agent": agent_id,
                "error_key": error_key,
                "zone": "YELLOW",
                "action": "notified",
                "description": f"エラー'{error_key}'についてDiscord通知を送信",
            })
            result["status"] = "notified"

        elif zone == "RED":
            # Yuta承認キューに追加
            _append_jsonl(APPROVAL_QUEUE_PATH, {
                "timestamp": now_iso,
                "agent": agent_id,
                "error_key": error_key,
                "zone": "RED",
                "count": error_info.get("count", 0),
                "description": error_info.get("example", ""),
                "fix": error_info.get("fix", "調査が必要"),
                "status": "pending_approval",
            })
            msg = (
                f"**[Agent Self-Check] RED ZONE - 承認必須**\n"
                f"エージェント: `{agent_id}`\n"
                f"エラー: `{error_key}` (count={error_info.get('count', 0)})\n"
                f"内容: {error_info.get('example', '')[:200]}\n"
                f"⚠️ Yuta承認待ち"
            )
            _send_discord(msg, "urgent_errors")
            result["status"] = "queued_for_approval"

        results.append(result)

    return results


def run_all_agents_check(dry_run=False):
    """全エージェントのエラーチェックを実行。"""
    ownership = _load_json(ERROR_OWNERSHIP_PATH)

    # 全ユニークオーナーを抽出
    all_agents = set()
    for error_key, info in ownership.items():
        if error_key.startswith("_") or error_key == "updated_at":
            continue
        if not isinstance(info, dict):
            continue
        owner = info.get("owner", "")
        if isinstance(owner, list):
            all_agents.update(owner)
        elif owner:
            all_agents.add(owner)

    results = {}
    for agent_id in sorted(all_agents):
        agent_results = check_agent_errors(agent_id, dry_run=dry_run)
        if agent_results:
            results[agent_id] = agent_results

    return results


def main():
    parser = argparse.ArgumentParser(description="エージェント自己エラー認識システム")
    parser.add_argument("--agent", type=str, help="チェック対象エージェントID")
    parser.add_argument("--all", action="store_true", help="全エージェントをチェック")
    parser.add_argument("--dry-run", action="store_true", help="ログ記録・通知なしで実行")
    parser.add_argument("--json", action="store_true", help="JSON形式で出力")
    args = parser.parse_args()

    if not args.agent and not args.all:
        parser.print_help()
        sys.exit(1)

    if args.all:
        results = run_all_agents_check(dry_run=args.dry_run)
        if args.json:
            print(json.dumps(results, ensure_ascii=False, indent=2))
        else:
            total_checked = sum(len(v) for v in results.values())
            zones = {"GREEN": 0, "YELLOW": 0, "RED": 0}
            for agent_results in results.values():
                for r in agent_results:
                    zones[r["zone"]] = zones.get(r["zone"], 0) + 1

            print(f"[Agent Self-Check] 全エージェントチェック完了")
            print(f"  対象エージェント数: {len(results)}")
            print(f"  チェック済みエラー数: {total_checked}")
            print(f"  GREEN: {zones['GREEN']} / YELLOW: {zones['YELLOW']} / RED: {zones['RED']}")
            if args.dry_run:
                print("  (dry-run: ログ記録・通知はスキップ)")

            for agent_id, agent_results in sorted(results.items()):
                non_monitoring = [r for r in agent_results if r["action"] != "monitor_continue"]
                if non_monitoring:
                    print(f"\n  [{agent_id}]")
                    for r in non_monitoring:
                        print(f"    {r['zone']} | {r['error_key']} | count={r['count']} | {r['action']}")
    else:
        results = check_agent_errors(args.agent, dry_run=args.dry_run)
        if args.json:
            print(json.dumps(results, ensure_ascii=False, indent=2))
        else:
            print(f"[Agent Self-Check] {args.agent}")
            for r in results:
                print(f"  {r['zone']} | {r['error_key']} | count={r['count']} | {r['action']} -> {r['status']}")


if __name__ == "__main__":
    main()
