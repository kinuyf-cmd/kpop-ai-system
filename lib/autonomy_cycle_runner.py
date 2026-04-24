#!/usr/bin/env python3
"""
autonomy_cycle_runner.py — 自律改善サイクルオーケストレーター

全自律改善コンポーネントを順次実行し、結果を集約・通知する。

1. learning_loop.py でパターン検出
2. agent_self_error_check.py で全エージェントチェック
3. auto_executor.py でGREENゾーンアイテムを実行
4. 結果集約・サマリー生成
5. Discord通知
6. logs/autonomy_cycles.jsonl にサイクル記録
7. ダッシュボードデータ更新

Usage:
  python3 lib/autonomy_cycle_runner.py
  python3 lib/autonomy_cycle_runner.py --dry-run
"""

import json
import sys
import argparse
import subprocess
import requests
from datetime import datetime, timezone
from pathlib import Path
from collections import Counter

BASE_DIR = Path(__file__).resolve().parent.parent
LOGS_DIR = BASE_DIR / "logs"
CYCLES_LOG = LOGS_DIR / "autonomy_cycles.jsonl"
EVIDENCE_DIR = LOGS_DIR / "completion_evidence"
DISCORD_WEBHOOKS_PATH = BASE_DIR / "config" / "discord_webhooks.json"

# Import sibling modules
sys.path.insert(0, str(BASE_DIR / "lib"))
sys.path.insert(0, str(BASE_DIR / "autonomy"))


def _load_json(path, default=None):
    """JSON読み込み。"""
    if default is None:
        default = {}
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def _append_jsonl(path, entry):
    """JSONLに追記。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _send_discord(message, webhook_key="daily_ceo_report"):
    """Discord通知。"""
    webhooks = _load_json(DISCORD_WEBHOOKS_PATH)
    url = webhooks.get(webhook_key, "")
    if not url:
        print(f"  [WARN] Discord webhook '{webhook_key}' not found", file=sys.stderr)
        return False
    try:
        resp = requests.post(url, json={
            "content": message[:2000],
            "username": "Autonomy Cycle",
        }, timeout=10)
        return resp.status_code in (200, 204)
    except requests.RequestException as e:
        print(f"  [WARN] Discord通知失敗: {e}", file=sys.stderr)
        return False


def run_learning_loop(dry_run=False):
    """Step 1: learning_loop.py を実行してパターン検出。"""
    print("[Step 1] Learning Loop: パターン検出...")
    cmd = [
        sys.executable,
        str(BASE_DIR / "autonomy" / "learning_loop.py"),
        "--days", "7",
        "--min-count", "2",
    ]
    if dry_run:
        cmd.append("--dry-run")

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120,
            cwd=str(BASE_DIR),
        )
        output = result.stdout
        patterns_detected = 0
        for line in output.split("\n"):
            if "Detected" in line and "recurring" in line:
                try:
                    patterns_detected = int(line.split("Detected")[1].split("recurring")[0].strip())
                except (ValueError, IndexError):
                    pass
            if "Loaded" in line and "error" in line:
                print(f"  {line.strip()}")
            if "Detected" in line:
                print(f"  {line.strip()}")

        return {
            "status": "ok" if result.returncode == 0 else "error",
            "patterns_detected": patterns_detected,
            "returncode": result.returncode,
            "stderr": result.stderr[:500] if result.stderr else "",
        }
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "patterns_detected": 0, "returncode": -1, "stderr": "timeout"}
    except Exception as e:
        return {"status": "error", "patterns_detected": 0, "returncode": -1, "stderr": str(e)}


def run_agent_self_check(dry_run=False):
    """Step 2: agent_self_error_check.py で全エージェントチェック。"""
    print("[Step 2] Agent Self-Check: 全エージェントエラーチェック...")
    try:
        # Import directly for better result capture
        from agent_self_error_check import run_all_agents_check
        results = run_all_agents_check(dry_run=dry_run)

        # 集計
        total_errors = sum(len(v) for v in results.values())
        zone_counts = Counter()
        action_counts = Counter()
        for agent_results in results.values():
            for r in agent_results:
                zone_counts[r["zone"]] += 1
                action_counts[r["action"]] += 1

        print(f"  対象エージェント: {len(results)}")
        print(f"  チェック済みエラー: {total_errors}")
        print(f"  GREEN: {zone_counts['GREEN']} / YELLOW: {zone_counts['YELLOW']} / RED: {zone_counts['RED']}")

        return {
            "status": "ok",
            "agents_checked": len(results),
            "total_errors": total_errors,
            "zone_counts": dict(zone_counts),
            "action_counts": dict(action_counts),
            "details": {k: v for k, v in results.items() if any(r["zone"] != "GREEN" or r["action"] != "monitor_continue" for r in v)},
        }
    except Exception as e:
        print(f"  [ERROR] {e}", file=sys.stderr)
        return {
            "status": "error",
            "agents_checked": 0,
            "total_errors": 0,
            "zone_counts": {},
            "action_counts": {},
            "error": str(e),
        }


def run_auto_executor(dry_run=False):
    """Step 3: auto_executor.py でGREENゾーンアイテムを実行。"""
    print("[Step 3] Auto Executor: GREENゾーン自動実行...")
    queue_path = BASE_DIR / "logs" / "ceo_improvement_queue.jsonl"
    if not queue_path.exists():
        print("  CEO improvement queue が見つかりません。スキップ。")
        return {
            "status": "skipped",
            "green_applied": 0,
            "yellow_notified": 0,
            "red_queued": 0,
        }

    cmd = [
        sys.executable,
        str(BASE_DIR / "autonomy" / "auto_executor.py"),
    ]
    if dry_run:
        cmd.append("--dry-run")

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120,
            cwd=str(BASE_DIR),
        )
        output = result.stdout

        green_count = 0
        yellow_count = 0
        red_count = 0
        for line in output.split("\n"):
            if "GREEN" in line and "auto-execute" in line:
                try:
                    green_count = int(line.split(":")[1].strip())
                except (ValueError, IndexError):
                    pass
            elif "YELLOW" in line and "async notify" in line:
                try:
                    yellow_count = int(line.split(":")[1].strip())
                except (ValueError, IndexError):
                    pass
            elif "RED" in line and "owner approval" in line:
                try:
                    red_count = int(line.split(":")[1].strip())
                except (ValueError, IndexError):
                    pass

        return {
            "status": "ok" if result.returncode == 0 else "error",
            "green_applied": green_count,
            "yellow_notified": yellow_count,
            "red_queued": red_count,
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "green_applied": 0, "yellow_notified": 0, "red_queued": 0}
    except Exception as e:
        return {"status": "error", "green_applied": 0, "yellow_notified": 0, "red_queued": 0, "error": str(e)}


def generate_summary(learning_result, selfcheck_result, executor_result, dry_run=False):
    """Step 4: 結果を集約してサマリーを生成。"""
    now = datetime.now(timezone.utc).isoformat()
    zone_counts = selfcheck_result.get("zone_counts", {})

    summary = {
        "timestamp": now,
        "dry_run": dry_run,
        "learning_loop": {
            "status": learning_result.get("status", "unknown"),
            "patterns_detected": learning_result.get("patterns_detected", 0),
        },
        "agent_self_check": {
            "status": selfcheck_result.get("status", "unknown"),
            "agents_checked": selfcheck_result.get("agents_checked", 0),
            "total_errors_checked": selfcheck_result.get("total_errors", 0),
            "green_count": zone_counts.get("GREEN", 0),
            "yellow_count": zone_counts.get("YELLOW", 0),
            "red_count": zone_counts.get("RED", 0),
        },
        "auto_executor": {
            "status": executor_result.get("status", "unknown"),
            "green_applied": executor_result.get("green_applied", 0),
            "yellow_notified": executor_result.get("yellow_notified", 0),
            "red_queued": executor_result.get("red_queued", 0),
        },
        "overall_status": "ok",
    }

    # ステータス判定
    statuses = [
        learning_result.get("status"),
        selfcheck_result.get("status"),
        executor_result.get("status"),
    ]
    if any(s == "error" for s in statuses):
        summary["overall_status"] = "partial_error"
    elif all(s in ("ok", "skipped") for s in statuses):
        summary["overall_status"] = "ok"

    return summary


def send_discord_summary(summary, dry_run=False):
    """Step 5: Discord通知。"""
    if dry_run:
        print("[Step 5] Discord通知: dry-runのためスキップ")
        return True

    print("[Step 5] Discord通知: サマリー送信...")
    sc = summary["agent_self_check"]
    ae = summary["auto_executor"]
    ll = summary["learning_loop"]

    msg = (
        f"**[自律改善サイクル] {summary['timestamp'][:19]}**\n"
        f"ステータス: {summary['overall_status']}\n\n"
        f"**Learning Loop**: パターン {ll['patterns_detected']}件検出\n"
        f"**Agent Self-Check**: {sc['agents_checked']}エージェント / "
        f"GREEN={sc['green_count']} YELLOW={sc['yellow_count']} RED={sc['red_count']}\n"
        f"**Auto Executor**: 自動適用={ae['green_applied']} 通知={ae['yellow_notified']} 承認待ち={ae['red_queued']}"
    )

    return _send_discord(msg, "daily_ceo_report")


def log_cycle(summary):
    """Step 6: autonomy_cycles.jsonl にサイクル記録。"""
    print("[Step 6] サイクル記録...")
    _append_jsonl(CYCLES_LOG, summary)
    print(f"  記録完了: {CYCLES_LOG}")


def update_dashboard(summary):
    """Step 7: ダッシュボードデータ更新。"""
    print("[Step 7] ダッシュボード更新...")
    dashboard_path = BASE_DIR / "logs" / "autonomy_dashboard.json"
    existing = _load_json(dashboard_path, {"cycles": [], "last_updated": ""})

    existing["last_updated"] = summary["timestamp"]
    existing["latest_cycle"] = summary

    # 直近10サイクルを保持
    cycles = existing.get("cycles", [])
    cycles.append({
        "timestamp": summary["timestamp"],
        "overall_status": summary["overall_status"],
        "patterns_detected": summary["learning_loop"]["patterns_detected"],
        "green": summary["agent_self_check"]["green_count"],
        "yellow": summary["agent_self_check"]["yellow_count"],
        "red": summary["agent_self_check"]["red_count"],
    })
    existing["cycles"] = cycles[-10:]

    dashboard_path.write_text(
        json.dumps(existing, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"  更新完了: {dashboard_path}")


def main():
    parser = argparse.ArgumentParser(description="自律改善サイクルオーケストレーター")
    parser.add_argument("--dry-run", action="store_true", help="ログ記録・通知なしで実行")
    args = parser.parse_args()

    print(f"{'='*60}")
    print(f"  自律改善サイクル {'[DRY-RUN]' if args.dry_run else ''}")
    print(f"  {datetime.now(timezone.utc).isoformat()}")
    print(f"{'='*60}\n")

    # Step 1: Learning Loop
    learning_result = run_learning_loop(dry_run=args.dry_run)

    # Step 2: Agent Self-Check
    selfcheck_result = run_agent_self_check(dry_run=args.dry_run)

    # Step 3: Auto Executor
    executor_result = run_auto_executor(dry_run=args.dry_run)

    # Step 4: Generate Summary
    print("\n[Step 4] サマリー生成...")
    summary = generate_summary(learning_result, selfcheck_result, executor_result, dry_run=args.dry_run)

    print(f"\n  全体ステータス: {summary['overall_status']}")
    print(f"  パターン検出: {summary['learning_loop']['patterns_detected']}")
    sc = summary['agent_self_check']
    print(f"  エージェントチェック: {sc['agents_checked']}エージェント")
    print(f"    GREEN={sc['green_count']} YELLOW={sc['yellow_count']} RED={sc['red_count']}")

    # Step 5: Discord Summary
    send_discord_summary(summary, dry_run=args.dry_run)

    # Step 6: Log Cycle
    if not args.dry_run:
        log_cycle(summary)
    else:
        print("[Step 6] サイクル記録: dry-runのためスキップ")

    # Step 7: Update Dashboard
    if not args.dry_run:
        update_dashboard(summary)
    else:
        print("[Step 7] ダッシュボード更新: dry-runのためスキップ")

    print(f"\n{'='*60}")
    print(f"  サイクル完了: {summary['overall_status']}")
    print(f"{'='*60}")

    return summary


if __name__ == "__main__":
    main()
