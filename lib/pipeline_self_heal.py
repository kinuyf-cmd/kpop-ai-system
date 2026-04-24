#!/usr/bin/env python3
"""
pipeline_self_heal.py — パイプライン自己修復エンジン v1.0

【責務】
  1. パイプライン実行結果をリアルタイム監視（pipeline.jsonl/kpi_errors.jsonl）
  2. 3連続失敗を検知したら即時にauto_repairを起動
  3. 修復後に失敗したパイプラインを自動再試行
  4. 修復結果をDiscord通知+ログ記録

【呼び出し方】
  A. パイプライン末尾から呼ばれる（失敗時のtrap handler内）
     → python3 lib/pipeline_self_heal.py check-and-heal
  B. watchdog（毎時）から呼ばれる
     → python3 lib/pipeline_self_heal.py monitor
  C. 手動実行
     → python3 lib/pipeline_self_heal.py --stats

【安全制約】
  - 1日最大3回の自動修復（暴走防止）
  - 同一パイプラインの連続再試行は最大1回（無限ループ防止）
  - 修復中は他のパイプラインをロックしない
  - 全操作をlogs/self_heal.jsonlに記録

Usage:
  python3 lib/pipeline_self_heal.py check-and-heal [--pipeline breaking]
  python3 lib/pipeline_self_heal.py monitor
  python3 lib/pipeline_self_heal.py --stats
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta, date
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)

HEAL_LOG = LOGS / "self_heal.jsonl"
PIPELINE_LOG = LOGS / "pipeline.jsonl"
KPI_ERROR_LOG = LOGS / "kpi_errors.jsonl"

MAX_HEAL_PER_DAY = 3
MAX_RETRY_PER_PIPELINE = 1
CONSECUTIVE_FAIL_THRESHOLD = 3

PIPELINE_SCRIPTS = {
    "breaking": "kpop_pipeline.sh",
    "strategy": "kpop_strategy_pipeline.sh",
    "chart": "kpop_chart_pipeline.sh",
    "chart_midweek": "kpop_chart_midweek_pipeline.sh",
    "birthday": "kpop_birthday_pipeline.sh",
    "artist_page": "kpop_artist_page_pipeline.sh",
}


def _load_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    records = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip():
            try:
                records.append(json.loads(line))
            except Exception:
                pass
    return records


def _append_log(entry: dict):
    LOGS.mkdir(parents=True, exist_ok=True)
    with HEAL_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _today_heal_count() -> int:
    today = date.today().isoformat()
    return sum(1 for r in _load_jsonl(HEAL_LOG)
               if r.get("timestamp", "").startswith(today)
               and r.get("action") == "auto_repair")


def _today_retry_count(pipeline: str) -> int:
    today = date.today().isoformat()
    return sum(1 for r in _load_jsonl(HEAL_LOG)
               if r.get("timestamp", "").startswith(today)
               and r.get("action") == "retry"
               and r.get("pipeline") == pipeline)


# ═══════════════════════════════════════════════════════════════
# 連続失敗検出
# ═══════════════════════════════════════════════════════════════

def detect_consecutive_failures(pipeline: str = "") -> dict | None:
    """直近のパイプライン実行結果から連続失敗を検出する。"""
    records = _load_jsonl(PIPELINE_LOG)
    if not records:
        # pipeline.jsonlが空ならkpi_errorsを確認
        errors = _load_jsonl(KPI_ERROR_LOG)
        today = date.today().isoformat()
        today_errors = [e for e in errors
                        if e.get("date") == today and not e.get("recoverable", True)]
        if len(today_errors) >= CONSECUTIVE_FAIL_THRESHOLD:
            return {
                "detected": True,
                "count": len(today_errors),
                "pipeline": pipeline or "unknown",
                "last_errors": [e.get("message", "")[:100] for e in today_errors[-3:]],
            }
        return None

    # パイプライン別にフィルタ
    if pipeline:
        records = [r for r in records if r.get("pipeline", "") == pipeline
                   or pipeline in r.get("script", "")]

    # 直近N件の連続失敗を検出
    consecutive = 0
    fail_details = []
    for rec in reversed(records[-20:]):
        status = rec.get("status", rec.get("result", ""))
        if status in ("failed", "error", "timeout", "BLOCK", "HARD_FAIL"):
            consecutive += 1
            fail_details.append({
                "step": rec.get("step", rec.get("agent", "unknown")),
                "error": str(rec.get("error", rec.get("message", "")))[:100],
                "timestamp": rec.get("timestamp", rec.get("ts", "")),
                "pipeline": rec.get("pipeline", ""),
            })
        else:
            break

    if consecutive >= CONSECUTIVE_FAIL_THRESHOLD:
        detected_pipeline = pipeline
        if not detected_pipeline and fail_details:
            detected_pipeline = fail_details[0].get("pipeline", "breaking")
        return {
            "detected": True,
            "count": consecutive,
            "pipeline": detected_pipeline or "breaking",
            "details": fail_details[:5],
        }

    return None


# ═══════════════════════════════════════════════════════════════
# 自動修復
# ═══════════════════════════════════════════════════════════════

def run_auto_repair() -> dict:
    """auto_repair.shを起動する。"""
    heal_count = _today_heal_count()
    if heal_count >= MAX_HEAL_PER_DAY:
        msg = f"本日の修復上限到達 ({heal_count}/{MAX_HEAL_PER_DAY})"
        _append_log({
            "timestamp": NOW.isoformat(),
            "action": "auto_repair",
            "result": "blocked",
            "reason": msg,
        })
        return {"repaired": False, "reason": msg}

    repair_script = BASE / "ai_company" / "auto_repair.sh"
    if not repair_script.exists():
        return {"repaired": False, "reason": "auto_repair.sh not found"}

    print(f"[self_heal] auto_repair.sh を起動中...", file=sys.stderr)

    try:
        result = subprocess.run(
            ["bash", str(repair_script)],
            capture_output=True, text=True,
            timeout=300,
            cwd=str(BASE),
        )
        success = result.returncode == 0
        _append_log({
            "timestamp": NOW.isoformat(),
            "action": "auto_repair",
            "result": "success" if success else "failed",
            "returncode": result.returncode,
            "stdout_tail": result.stdout[-300:] if result.stdout else "",
            "stderr_tail": result.stderr[-300:] if result.stderr else "",
        })
        return {"repaired": success, "returncode": result.returncode}

    except subprocess.TimeoutExpired:
        _append_log({
            "timestamp": NOW.isoformat(),
            "action": "auto_repair",
            "result": "timeout",
        })
        return {"repaired": False, "reason": "timeout"}
    except Exception as e:
        _append_log({
            "timestamp": NOW.isoformat(),
            "action": "auto_repair",
            "result": "error",
            "error": str(e)[:200],
        })
        return {"repaired": False, "reason": str(e)}


# ═══════════════════════════════════════════════════════════════
# 自動再試行
# ═══════════════════════════════════════════════════════════════

def retry_pipeline(pipeline: str) -> dict:
    """修復後にパイプラインを再試行する。"""
    retry_count = _today_retry_count(pipeline)
    if retry_count >= MAX_RETRY_PER_PIPELINE:
        msg = f"{pipeline}の本日リトライ上限到達 ({retry_count}/{MAX_RETRY_PER_PIPELINE})"
        _append_log({
            "timestamp": NOW.isoformat(),
            "action": "retry",
            "pipeline": pipeline,
            "result": "blocked",
            "reason": msg,
        })
        return {"retried": False, "reason": msg}

    script_name = PIPELINE_SCRIPTS.get(pipeline, f"kpop_{pipeline}_pipeline.sh")
    script_path = BASE / script_name
    if not script_path.exists():
        # fallback: kpop_pipeline.sh
        script_path = BASE / "kpop_pipeline.sh"
        if not script_path.exists():
            return {"retried": False, "reason": f"{script_name} not found"}

    print(f"[self_heal] {script_name} を再試行中...", file=sys.stderr)

    try:
        # バックグラウンドで起動（親プロセスをブロックしない）
        proc = subprocess.Popen(
            ["bash", str(script_path)],
            stdout=open(LOGS / "self_heal_retry.log", "a"),
            stderr=subprocess.STDOUT,
            cwd=str(BASE),
        )

        _append_log({
            "timestamp": NOW.isoformat(),
            "action": "retry",
            "pipeline": pipeline,
            "script": script_name,
            "result": "started",
            "pid": proc.pid,
        })

        return {"retried": True, "pid": proc.pid, "script": script_name}

    except Exception as e:
        _append_log({
            "timestamp": NOW.isoformat(),
            "action": "retry",
            "pipeline": pipeline,
            "result": "error",
            "error": str(e)[:200],
        })
        return {"retried": False, "reason": str(e)}


# ═══════════════════════════════════════════════════════════════
# Discord通知
# ═══════════════════════════════════════════════════════════════

def notify_heal_action(failure: dict, repair_result: dict, retry_result: dict | None):
    """修復アクションをDiscordに通知する。"""
    try:
        sys.path.insert(0, str(BASE))
        from lib.discord_channel_router import notify_alert

        title = f"🔧 パイプライン自己修復: {failure.get('pipeline', '?')}"
        body_parts = [
            f"**{failure['count']}連続失敗を検知 → 自動修復を実行**",
            "",
            f"修復結果: {'✅ 成功' if repair_result.get('repaired') else '❌ 失敗'}",
        ]
        if retry_result:
            body_parts.append(
                f"再試行: {'✅ 起動済み (PID: {retry_result.get(\"pid\", \"?\")})' if retry_result.get('retried') else '❌ ' + retry_result.get('reason', '')}"
            )
        body_parts.append(f"\n**確認**: `logs/self_heal.jsonl`")

        notify_alert(title, "\n".join(body_parts), severity="CRITICAL")
    except Exception as e:
        print(f"[self_heal] Discord通知エラー: {e}", file=sys.stderr)


# ═══════════════════════════════════════════════════════════════
# メインコマンド
# ═══════════════════════════════════════════════════════════════

def check_and_heal(pipeline: str = "") -> dict:
    """連続失敗を検知して修復+再試行を行う。"""
    print(f"[self_heal] check-and-heal 開始 pipeline={pipeline or 'auto'}", file=sys.stderr)

    failure = detect_consecutive_failures(pipeline)
    if not failure or not failure.get("detected"):
        print(f"[self_heal] 連続失敗なし — スキップ", file=sys.stderr)
        return {"healed": False, "reason": "no consecutive failures"}

    print(f"[self_heal] {failure['count']}連続失敗検知! pipeline={failure['pipeline']}", file=sys.stderr)

    # 自動修復
    repair_result = run_auto_repair()
    print(f"[self_heal] 修復結果: {repair_result}", file=sys.stderr)

    # 修復成功なら再試行
    retry_result = None
    if repair_result.get("repaired"):
        retry_result = retry_pipeline(failure["pipeline"])
        print(f"[self_heal] 再試行結果: {retry_result}", file=sys.stderr)

    # Discord通知
    notify_heal_action(failure, repair_result, retry_result)

    return {
        "healed": True,
        "failure": failure,
        "repair": repair_result,
        "retry": retry_result,
    }


def monitor() -> dict:
    """定期監視モード。全パイプラインの連続失敗をチェック。"""
    print(f"[self_heal] monitor 開始", file=sys.stderr)

    results = {}
    for pipeline in ["breaking", "strategy", "chart"]:
        failure = detect_consecutive_failures(pipeline)
        if failure and failure.get("detected"):
            results[pipeline] = check_and_heal(pipeline)
        else:
            results[pipeline] = {"healed": False, "reason": "no failures"}

    # パイプライン名なしでも全体チェック
    if not any(r.get("healed") for r in results.values()):
        global_failure = detect_consecutive_failures("")
        if global_failure and global_failure.get("detected"):
            results["global"] = check_and_heal("")

    return results


def print_stats():
    records = _load_jsonl(HEAL_LOG)
    if not records:
        print("自己修復ログなし")
        return

    from collections import Counter
    actions = Counter(r.get("action", "") for r in records)
    results_c = Counter(r.get("result", "") for r in records)

    print(f"\n=== パイプライン自己修復統計 ===")
    print(f"  総記録数: {len(records)}")
    print(f"  アクション別: {dict(actions)}")
    print(f"  結果別: {dict(results_c)}")

    today = date.today().isoformat()
    today_records = [r for r in records if r.get("timestamp", "").startswith(today)]
    print(f"  本日: {len(today_records)}件")


def main():
    parser = argparse.ArgumentParser(description="パイプライン自己修復エンジン v1.0")
    parser.add_argument("command", nargs="?", default="monitor",
                        choices=["check-and-heal", "monitor"])
    parser.add_argument("--pipeline", default="", help="対象パイプライン名")
    parser.add_argument("--stats", action="store_true")
    args = parser.parse_args()

    if args.stats:
        print_stats()
        return

    if args.command == "check-and-heal":
        result = check_and_heal(args.pipeline)
    else:
        result = monitor()

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
