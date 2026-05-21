#!/usr/bin/env python3
"""
ceo_safe_actions.py — CEO安全実行アクション v1.0
CEO: ミュウツー / オーナー: 人間（閲覧専用）

【役割】
  ceo_executor.py から呼ばれる「安全実行のみ」のアクション関数群。
  - read-only調査（inspect系）の結果を ceo_safe_action_history.jsonl に保存
  - retry_alert_queue: alert_queue.jsonl の pending を再送フラグ立て（書き込みは既存lib/alert_queue.pyに委譲）
  - monitor_only: dashboard_summary.jsonの全指標確認

【禁止】
  - 既存記事・WP API・pipeline本体への変更
  - Discord通知ロジックの改変
  - ファイル上書き型の自動修正

【recommendation_type 定数】
  prompt_fix        — プロンプト修正が必要
  timeout_fix       — タイムアウト設定の見直し
  retry_config      — リトライ設定の追加
  manual_restart    — 手動再起動が必要
  monitor_continue  — 監視継続（異常なし）
  alert_retry       — アラート再送が必要
  check_config      — 設定確認が必要
"""

import json
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).parent.parent
SAFE_ACTION_HISTORY_PATH = BASE / "logs" / "ceo_safe_action_history.jsonl"
AGENT_METRICS_PATH       = BASE / "agent_metrics.json"
PIPELINE_LOG_PATH        = BASE / "logs" / "pipeline.jsonl"
ALERT_QUEUE_PATH         = BASE / "logs" / "alert_queue.jsonl"
DASHBOARD_SUMMARY_PATH   = BASE / "dashboard_summary.json"
ALERT_QUEUE_SCRIPT       = BASE / "lib" / "alert_queue.py"

JST = timezone(timedelta(hours=9))


# ─────────────────────────────────────────────
# ユーティリティ
# ─────────────────────────────────────────────

def _now_jst() -> str:
    return datetime.now(JST).isoformat()


def _today_jst() -> str:
    return datetime.now(JST).strftime("%Y-%m-%d")


def _load_jsonl(path: Path, tail: int = 0) -> list:
    if not path.exists():
        return []
    records = []
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception:
        pass
    return records[-tail:] if tail > 0 else records


def _load_json_safe(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _resolve_agent_id(name_ja: str) -> str:
    """カタカナ名 → エージェントID の逆引き"""
    _FALLBACK = {
        "バタフリー": "butterfree", "カイリュー": "kairyu",
        "サーナイト": "gardevoir_hook_critic", "アルセウス": "arceus",
        "WP投稿": "wordpress_post", "X投稿B": "x_post_b",
        "ミュウツー": "mewtwo", "デオキシス": "deoxys",
        "メタモン": "metamon", "イーブイ": "eevee",
        "ジラーチ": "jirachi", "フーディン": "alakazam",
    }
    am = _load_json_safe(AGENT_METRICS_PATH)
    for aid, v in am.get("agents", {}).items():
        if v.get("name_ja") == name_ja:
            return aid
    return _FALLBACK.get(name_ja, name_ja)


def append_safe_history(entry: dict) -> None:
    """ceo_safe_action_history.jsonl に1件追記する"""
    SAFE_ACTION_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SAFE_ACTION_HISTORY_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _try_enqueue_improvement(entry: dict) -> dict:
    """
    safe action 結果を improvement_queue に積む。
    失敗してもsafe action本体の結果には影響しない。
    戻り値: enqueue_from_safe_action の結果 or {}
    """
    try:
        if str(BASE) not in sys.path:
            sys.path.insert(0, str(BASE))
        from lib.ceo_improvement_queue import enqueue_from_safe_action
        return enqueue_from_safe_action(entry)
    except Exception as e:
        import sys as _sys
        print(f"  [ceo_safe_actions] ⚠️ improvement enqueue skip: {e}", file=_sys.stderr)
        return {}


def _is_same_day_done(action_type: str, target_agent: str) -> bool:
    """今日既に同一action_type+target_agentがdoneになっているか"""
    today = _today_jst()
    for h in _load_jsonl(SAFE_ACTION_HISTORY_PATH):
        if (h.get("action_type") == action_type
                and h.get("target_agent") == target_agent
                and h.get("result") == "done"
                and h.get("executed_at", "").startswith(today)):
            return True
    return False


# ─────────────────────────────────────────────
# safe action 関数群
# ─────────────────────────────────────────────

def run_retry_alert_queue(record: dict) -> dict:
    """
    alert_queue.jsonl の pending件数を確認し、
    lib/alert_queue.py --retry を subprocess で安全実行する。
    pending=0 の場合はスキップ。
    """
    action_type  = "retry_alert_queue"
    target_agent = ""

    queue   = _load_jsonl(ALERT_QUEUE_PATH)
    pending = [r for r in queue if r.get("status") == "pending"]

    # pending=0 なら実行不要
    if not pending:
        entry = {
            "executed_at":       _now_jst(),
            "action_type":       action_type,
            "target_agent":      target_agent,
            "result":            "skipped",
            "summary":           "アラートキューにpendingなし。再送不要。",
            "recommendation_type": "monitor_continue",
            "proposed_next_step":  "次回サイクルまで監視継続でよい",
            "source_log":          str(ALERT_QUEUE_PATH.relative_to(BASE)),
        }
        append_safe_history(entry)
        return {"result": "skipped", "reason": "no_pending_alerts", "safe_action_entry": entry}

    # pending > 0 → subprocess で --retry を実行（読み取り+再送のみ、既存の通知ロジックに委譲）
    crits = [r for r in pending if r.get("severity") == "CRITICAL"]
    try:
        proc = subprocess.run(
            [sys.executable, str(ALERT_QUEUE_SCRIPT), "--retry"],
            capture_output=True, text=True, timeout=30,
            cwd=str(BASE),
        )
        stderr_tail = proc.stderr.strip()[-200:] if proc.stderr else ""
        if proc.returncode == 0:
            summary = (
                f"アラートキュー再送実行完了。pending {len(pending)}件（CRITICAL {len(crits)}件）を再送処理。"
                + (f" stderr: {stderr_tail[:100]}" if stderr_tail else "")
            )
            rec_type = "alert_retry"
            result   = "done"
        else:
            summary  = f"再送スクリプト異常終了（rc={proc.returncode}）: {stderr_tail[:120]}"
            rec_type = "check_config"
            result   = "failed"
    except subprocess.TimeoutExpired:
        summary  = "再送スクリプトがタイムアウト（30秒）"
        rec_type = "check_config"
        result   = "failed"
    except Exception as e:
        summary  = f"再送スクリプト起動失敗: {str(e)[:80]}"
        rec_type = "check_config"
        result   = "failed"

    entry = {
        "executed_at":       _now_jst(),
        "action_type":       action_type,
        "target_agent":      target_agent,
        "result":            result,
        "summary":           summary,
        "recommendation_type": rec_type,
        "proposed_next_step":  (
            "Discord で通知受信を確認する" if result == "done"
            else "lib/alert_queue.py を手動実行してエラーを確認する"
        ),
        "source_log": str(ALERT_QUEUE_PATH.relative_to(BASE)),
    }
    append_safe_history(entry)
    return {"result": result, "reason": "" if result == "done" else "subprocess_failed", "safe_action_entry": entry}


def run_monitor_only(record: dict) -> dict:
    """
    dashboard_summary.json の全指標を確認し、異常がなければ done を返す。
    1runにつき1回のみ実行（同日同タイプをskip）。
    """
    action_type  = "monitor_only"
    target_agent = ""

    if _is_same_day_done(action_type, target_agent):
        entry = {
            "executed_at":       _now_jst(),
            "action_type":       action_type,
            "target_agent":      target_agent,
            "result":            "skipped",
            "summary":           "本日既にmonitor_only済み。重複スキップ。",
            "recommendation_type": "monitor_continue",
            "proposed_next_step":  "次回サイクルまで監視継続でよい",
            "source_log":          "dashboard_summary.json",
        }
        append_safe_history(entry)
        return {"result": "skipped", "reason": "same_day_done", "safe_action_entry": entry}

    sm      = _load_json_safe(DASHBOARD_SUMMARY_PATH)
    rate    = sm.get("overall_success_rate", 0)
    posts   = sm.get("today_posts", 0)
    unres_c = sm.get("unresolved_critical_count", 0)
    pending = sm.get("notification_pending_count", 0)
    blockers = sm.get("revenue_blocker_top3", [])
    blocker_str = "、".join(
        f"{b.get('name','')}({b.get('rate',0):.0%})" for b in blockers[:2]
    ) if blockers else "なし"

    summary = (
        f"全体成功率{rate:.1%}・今日の投稿{posts}本・"
        f"未解決CRITICAL{unres_c}件・通知pending{pending}件・"
        f"売上阻害TOP: {blocker_str}。"
    )
    if unres_c > 0:
        proposed = f"CRITICAL {unres_c}件が未解決。retry_alert_queueを優先実行する"
        rec_type = "check_config"
    elif rate < 0.7:
        proposed = f"全体成功率{rate:.1%}が低下。inspect_agent_failureで原因特定を優先する"
        rec_type = "check_config"
    else:
        proposed = "全指標正常範囲内。次回サイクルまで監視継続でよい"
        rec_type = "monitor_continue"

    entry = {
        "executed_at":       _now_jst(),
        "action_type":       action_type,
        "target_agent":      target_agent,
        "result":            "done",
        "summary":           summary,
        "recommendation_type": rec_type,
        "proposed_next_step":  proposed,
        "source_log":          "dashboard_summary.json",
    }
    append_safe_history(entry)
    imp = _try_enqueue_improvement(entry)
    return {"result": "done", "reason": "", "safe_action_entry": entry, "improvement_enqueue": imp}


def save_agent_failure_inspection(record: dict, exec_summary: str, next_rec: str) -> dict:
    """
    inspect_agent_failure の調査結果を ceo_safe_action_history.jsonl に保存する。
    改善提案JSONを生成するところまで。コード修正は行わない。
    """
    action_type  = "inspect_agent_failure"
    target_agent = record.get("target_agent", "")

    if _is_same_day_done(action_type, target_agent):
        entry = {
            "executed_at":       _now_jst(),
            "action_type":       action_type,
            "target_agent":      target_agent,
            "result":            "skipped",
            "summary":           f"{target_agent}のinspection本日済み。重複スキップ。",
            "recommendation_type": "monitor_continue",
            "proposed_next_step":  "本日分は処理済み。明日以降に再調査する",
            "source_log":          "agent_metrics.json",
        }
        append_safe_history(entry)
        return {"result": "skipped", "reason": "same_day_done", "safe_action_entry": entry}

    # recommendation_type を summary から判定
    if "HARD_FAIL" in exec_summary and "回" in exec_summary:
        rec_type = "prompt_fix"
        proposed = f"{target_agent}のHARD_FAILパターンを解析し、プロンプトの品質ゲート条件を緩和または修正する"
    elif "空出力" in exec_summary:
        rec_type = "timeout_fix"
        proposed = f"{target_agent}のタイムアウト設定を延長（例: 60→120秒）またはリトライ回数を2→3に増やす"
    elif "完全停止" in exec_summary or "0%" in exec_summary or "0.0%" in exec_summary:
        rec_type = "manual_restart"
        proposed = f"{target_agent}が停止中。agent_metrics.jsonのlast_run_timeと失敗ログを確認し手動再起動を検討する"
    else:
        rec_type = "retry_config"
        proposed = next_rec

    entry = {
        "executed_at":       _now_jst(),
        "action_type":       action_type,
        "target_agent":      target_agent,
        "result":            "done",
        "summary":           exec_summary,
        "recommendation_type": rec_type,
        "proposed_next_step":  proposed,
        "source_log":          "agent_metrics.json",
    }
    append_safe_history(entry)
    imp = _try_enqueue_improvement(entry)
    return {"result": "done", "reason": "", "safe_action_entry": entry, "improvement_enqueue": imp}


def save_revenue_blocker_inspection(record: dict, exec_summary: str, next_rec: str) -> dict:
    """
    inspect_revenue_blocker の調査結果を ceo_safe_action_history.jsonl に保存する。
    改善提案JSONを生成するところまで。コード修正は行わない。
    """
    action_type  = "inspect_revenue_blocker"
    target_agent = record.get("target_agent", "")

    if _is_same_day_done(action_type, target_agent):
        entry = {
            "executed_at":       _now_jst(),
            "action_type":       action_type,
            "target_agent":      target_agent,
            "result":            "skipped",
            "summary":           f"{target_agent}の売上阻害inspection本日済み。重複スキップ。",
            "recommendation_type": "monitor_continue",
            "proposed_next_step":  "本日分は処理済み。明日以降に再調査する",
            "source_log":          "logs/pipeline.jsonl",
        }
        append_safe_history(entry)
        return {"result": "skipped", "reason": "same_day_done", "safe_action_entry": entry}

    # recommendation_type を summary から判定
    if "エラー:" in exec_summary or "失敗" in exec_summary:
        rec_type = "prompt_fix"
        proposed = f"{target_agent}の失敗パターンをpipeline.jsonlで特定し、config/agent_directives.jsonのプロンプトまたはAPI設定を修正する"
    elif "空出力" in exec_summary or "空0回" not in exec_summary:
        rec_type = "timeout_fix"
        proposed = f"{target_agent}の空出力を解消するため、タイムアウト延長またはリトライ設定を追加する"
    else:
        rec_type = "retry_config"
        proposed = next_rec

    entry = {
        "executed_at":       _now_jst(),
        "action_type":       action_type,
        "target_agent":      target_agent,
        "result":            "done",
        "summary":           exec_summary,
        "recommendation_type": rec_type,
        "proposed_next_step":  proposed,
        "source_log":          "logs/pipeline.jsonl",
    }
    append_safe_history(entry)
    imp = _try_enqueue_improvement(entry)
    return {"result": "done", "reason": "", "safe_action_entry": entry, "improvement_enqueue": imp}
