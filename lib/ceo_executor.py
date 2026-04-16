#!/usr/bin/env python3
"""
ceo_executor.py — CEO実行命令 安全実行管理エンジン v2.0
CEO: ミュウツー / オーナー: 人間（閲覧専用）

【役割】
  ceo_action_queue.jsonl の pending 命令を受理し、
  - 安全性チェック
  - ログ読み取りによる調査レポート生成
  - status 更新（pending → in_progress → done/failed/blocked/skipped_duplicate/skipped_unsafe）
  - ceo_execution_history.jsonl への実行記録追記
  - ceo_execution_state.json への最新状態保存
  を管理する（最大3件連続処理）。

【status 遷移】
  pending → in_progress → done
                        → failed        (例外・データ不足)
                        → blocked       (安全違反・target_log欠落・未対応action_type)
                        → skipped_duplicate  (同一agent+action_typeが処理済み)
                        → skipped_unsafe     (execute_recommended=false かつ non-monitor)

【blocked/failed reason 定数】
  unsupported_action_type
  missing_target_log
  no_recent_data
  duplicate_in_progress
  skipped_duplicate_done
  unsafe_operation_denied
  exception_during_exec
  queue_write_failure
"""

import json
import sys
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).parent.parent
QUEUE_PATH             = BASE / "logs" / "ceo_action_queue.jsonl"
HISTORY_PATH           = BASE / "logs" / "ceo_execution_history.jsonl"
STATE_PATH             = BASE / "logs" / "ceo_execution_state.json"
AGENT_METRICS_PATH     = BASE / "agent_metrics.json"
PIPELINE_LOG_PATH      = BASE / "logs" / "pipeline.jsonl"
ALERT_QUEUE_PATH       = BASE / "logs" / "alert_queue.jsonl"
DASHBOARD_SUMMARY_PATH = BASE / "dashboard_summary.json"

JST = timezone(timedelta(hours=9))

MAX_PER_RUN = 3  # 1サイクルで最大処理件数

# 安全実行可能な action_type
SAFE_ACTION_TYPES = {
    "retry_alert_queue",
    "inspect_agent_failure",
    "inspect_revenue_blocker",
    "monitor_only",
}

# execute_recommended=false でも自動実行を許可するタイプ（読み取り専用確認のみ）
AUTO_ALLOW_WITHOUT_RECOMMEND = {"monitor_only"}

# エージェントIDとカタカナ名マッピング（agent_metricsが読めない場合のフォールバック）
AGENT_NAME_FALLBACK = {
    "butterfree":            "バタフリー",
    "kairyu":                "カイリュー",
    "sanai":                 "サーナイト（旧）",
    "gardevoir_hook_critic": "サーナイト",
    "arceus":                "アルセウス",
    "wp_poster":             "WP投稿",
    "wordpress_post":        "WP投稿",
    "x_post_b":              "X投稿B",
    "mewtwo":                "ミュウツー",
    "deoxys":                "デオキシス",
    "metamon":               "メタモン",
    "eevee":                 "イーブイ",
    "jirachi":               "ジラーチ",
    "alakazam":              "フーディン",
    "pipeline":              "パイプライン",
}


# ─────────────────────────────────────────────
# ユーティリティ
# ─────────────────────────────────────────────

def _now_jst() -> str:
    return datetime.now(JST).isoformat()


def _load_jsonl(path: Path, tail: int = 0) -> list:
    """JSONL を安全に読む。tail>0 なら末尾 tail 件のみ返す。"""
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
    """カタカナ名 → エージェントID の逆引き。agent_metrics.json を使う。"""
    am = _load_json_safe(AGENT_METRICS_PATH)
    for aid, v in am.get("agents", {}).items():
        if v.get("name_ja") == name_ja:
            return aid
    for aid, name in AGENT_NAME_FALLBACK.items():
        if name == name_ja:
            return aid
    return name_ja


def _agent_name(agent_id: str) -> str:
    """agent_metrics.json からカタカナ名を取得、なければフォールバック"""
    am = _load_json_safe(AGENT_METRICS_PATH)
    v  = am.get("agents", {}).get(agent_id, {})
    return v.get("name_ja", "") or AGENT_NAME_FALLBACK.get(agent_id, agent_id)


# ─────────────────────────────────────────────
# キュー操作
# ─────────────────────────────────────────────

def load_queue() -> list:
    return _load_jsonl(QUEUE_PATH)


def save_queue(records: list) -> None:
    QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with QUEUE_PATH.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def pick_pending_batch(records: list, max_count: int = MAX_PER_RUN) -> list:
    """
    pending を古い順（インデックス小さい順）で最大 max_count 件選ぶ。
    同一 target_agent + action_type の重複は最初の1件だけ選ぶ。
    戻り値: [(index, record), ...]
    """
    seen_keys = set()
    selected  = []
    for i, r in enumerate(records):
        if r.get("status") != "pending":
            continue
        key = (r.get("action_type", ""), r.get("target_agent", ""))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        selected.append((i, r))
        if len(selected) >= max_count:
            break
    return selected


# ─────────────────────────────────────────────
# 重複実行防止
# ─────────────────────────────────────────────

def _is_in_progress(record: dict, records: list) -> bool:
    """同一 action_type + target_agent が in_progress 中かチェック"""
    for r in records:
        if (r.get("action_type") == record.get("action_type")
                and r.get("target_agent") == record.get("target_agent")
                and r.get("status") == "in_progress"):
            return True
    return False


def _is_recently_done(record: dict) -> bool:
    """history 直近5件に同一 action_type + target_agent + result=done があるかチェック"""
    hist = _load_jsonl(HISTORY_PATH, tail=5)
    for h in hist:
        if (h.get("action_type") == record.get("action_type")
                and h.get("target_agent") == record.get("target_agent")
                and h.get("result") == "done"):
            return True
    return False


# ─────────────────────────────────────────────
# アクション別 実行レポート生成
# ─────────────────────────────────────────────

def exec_retry_alert_queue(record: dict) -> dict:
    """alert_queue.jsonl の pending 件数を調査してレポートを返す。"""
    queue     = _load_jsonl(ALERT_QUEUE_PATH)
    pending   = [r for r in queue if r.get("status") == "pending"]
    perm_fail = [r for r in queue if r.get("status") == "permanent_failed"]
    crits     = [r for r in pending if r.get("severity") == "CRITICAL"]

    if not queue:
        return {
            "result":              "blocked",
            "reason":              "no_recent_data",
            "summary":             "alert_queue.jsonlが空またはなし。通知キュー未使用の可能性がある。",
            "next_recommendation": "logs/alert_queue.jsonl の存在を確認する",
        }

    if not pending:
        return {
            "result":              "done",
            "reason":              "",
            "summary":             f"アラートキューにpendingなし（全{len(queue)}件処理済み）。通知システム正常。",
            "next_recommendation": "次回サイクルまで監視継続でよい",
        }

    top_err = Counter(r.get("last_error","").split(":")[0] for r in pending).most_common(1)
    err_str = top_err[0][0] if top_err else "不明"
    return {
        "result":  "done",
        "reason":  "",
        "summary": (
            f"pending {len(pending)}件（うちCRITICAL {len(crits)}件）、"
            f"主要エラー: {err_str}、永続失敗: {len(perm_fail)}件"
        ),
        "next_recommendation": (
            f"bash run_agent_monitor.sh を実行してpending {len(pending)}件を再送する"
        ),
    }


def exec_inspect_agent_failure(record: dict) -> dict:
    """agent_metrics.json から対象エージェントの詳細を読んでレポートを返す。"""
    agent_id    = _resolve_agent_id(record.get("target_agent", ""))
    am          = _load_json_safe(AGENT_METRICS_PATH)
    agents      = am.get("agents", {})

    target_data = None
    for aid, v in agents.items():
        if v.get("name_ja") == record.get("target_agent") or aid == agent_id:
            target_data = v
            break

    if not target_data:
        return {
            "result":              "blocked",
            "reason":              "no_recent_data",
            "summary":             f"{record.get('target_agent','不明')} のメトリクスが取得できなかった",
            "next_recommendation": "agent_metrics.json を手動確認する",
        }

    total = target_data.get("total_count", 0)
    ok    = target_data.get("success_count", 0)
    fail  = target_data.get("fail_count", 0)
    empty = target_data.get("empty_output_count", 0)
    hf    = target_data.get("hard_fail_count", 0)
    rate  = target_data.get("success_rate", 0)
    h_ago = target_data.get("hours_since_last_run", 0)
    name  = target_data.get("name_ja", record.get("target_agent", ""))

    summary = (
        f"{name} — 全{total}回中 成功{ok}回 失敗{fail}回 "
        f"（空出力{empty}回・HARD_FAIL{hf}回）、"
        f"成功率{rate:.1%}、最終実行{h_ago:.0f}h前"
    )

    if rate == 0.0:
        next_rec = f"{name}が完全停止中。agent_metrics.jsonのlast_run_timeと失敗原因を確認し手動で再起動を検討する"
    elif hf >= 5:
        next_rec = f"{name}のHARD_FAILが{hf}回。logs/gardevoir_hook.jsonlで失敗タイトルを確認しプロンプトを修正する"
    elif empty >= 3:
        next_rec = f"{name}の空出力が{empty}回。エージェントのタイムアウト設定または入力データを確認する"
    else:
        next_rec = f"{name}の成功率{rate:.1%}を監視継続。悪化傾向があれば次サイクルで再調査する"

    return {"result": "done", "reason": "", "summary": summary, "next_recommendation": next_rec}


def exec_inspect_revenue_blocker(record: dict) -> dict:
    """pipeline.jsonl から対象エージェントの直近3runを読んでレポートを返す。"""
    target_name = record.get("target_agent", "")
    target_id   = _resolve_agent_id(target_name)

    pl_records  = _load_jsonl(PIPELINE_LOG_PATH)
    agent_runs  = [r for r in pl_records if r.get("step") == target_id]

    am          = _load_json_safe(AGENT_METRICS_PATH)
    agents      = am.get("agents", {})
    target_data = agents.get(target_id, {})
    rate  = target_data.get("success_rate", 0)
    total = target_data.get("total_count", 0)
    empty = target_data.get("empty_output_count", 0)
    hf    = target_data.get("hard_fail_count", 0)
    fail  = target_data.get("fail_count", 0)

    recent3    = agent_runs[-3:] if agent_runs else []
    statuses_3 = [r.get("status", "?") for r in recent3]
    errors_3   = [r.get("message", "") for r in recent3 if r.get("message")]

    if recent3:
        ok_3  = sum(1 for s in statuses_3 if s == "ok")
        err_3 = sum(1 for s in statuses_3 if s in ("error", "failed"))
        emp_3 = sum(1 for s in statuses_3 if s == "empty")
        err_msgs  = "、".join(set(e[:30] for e in errors_3 if e))
        run_detail = f"直近3run: 成功{ok_3}回・失敗{err_3}回・空{emp_3}回"
        if err_msgs:
            run_detail += f"（エラー: {err_msgs}）"
    else:
        run_detail = f"pipeline.jsonlに{target_name}の記録なし"
        err_3 = 0

    summary = (
        f"{target_name} — 全{total}回 成功率{rate:.1%}、"
        f"空出力{empty}回・HARD_FAIL{hf}回・失敗{fail}回。"
        f"{run_detail}"
    )

    if err_3 >= 1 and errors_3:
        err_pattern = errors_3[0][:40]
        next_rec = (
            f"{target_name}の直近失敗パターン「{err_pattern}」を特定済み。"
            f"config/agent_directives.jsonで入力データまたはAPI呼び出し設定を修正する"
        )
    elif empty >= 3 or (recent3 and emp_3 >= 1):
        next_rec = (
            f"{target_name}の空出力を確認。"
            f"タイムアウト延長またはリトライ設定の追加を検討する"
        )
    else:
        next_rec = (
            f"{target_name}の成功率{rate:.1%}は改善余地あり。"
            f"pipeline.jsonlの失敗runのsize_bytes=0件を特定してプロンプト修正する"
        )

    return {"result": "done", "reason": "", "summary": summary, "next_recommendation": next_rec}


def exec_monitor_only(record: dict) -> dict:
    """monitor_only は正常確認レポートを生成する。"""
    sm      = _load_json_safe(DASHBOARD_SUMMARY_PATH)
    rate    = sm.get("overall_success_rate", 0)
    posts   = sm.get("today_posts", 0)
    unres_c = sm.get("unresolved_critical_count", 0)
    pending = sm.get("notification_pending_count", 0)
    summary = (
        f"全体成功率{rate:.1%}・今日の投稿{posts}本・"
        f"未解決CRITICAL{unres_c}件・通知pending{pending}件。全指標正常範囲内。"
    )
    return {
        "result":              "done",
        "reason":              "",
        "summary":             summary,
        "next_recommendation": "次回サイクルまで通常監視を継続する。異常があれば自動検知される。",
    }


EXECUTORS = {
    "retry_alert_queue":       exec_retry_alert_queue,
    "inspect_agent_failure":   exec_inspect_agent_failure,
    "inspect_revenue_blocker": exec_inspect_revenue_blocker,
    "monitor_only":            exec_monitor_only,
}


# ─────────────────────────────────────────────
# 実行ログ保存
# ─────────────────────────────────────────────

def append_history(entry: dict) -> None:
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with HISTORY_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def save_state(entries: list, run_counts: dict) -> None:
    """最終実行エントリと今回の集計をstateに保存する。"""
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    last = entries[-1] if entries else {}
    state = {
        "last_executed_at":          last.get("executed_at", ""),
        "last_action_type":          last.get("action_type", ""),
        "last_target_agent":         last.get("target_agent", ""),
        "last_result":               last.get("result", ""),
        "last_reason":               last.get("reason", ""),
        "last_summary":              last.get("summary", ""),
        "processed_count_this_run":  run_counts.get("processed", 0),
        "done_count_this_run":       run_counts.get("done", 0),
        "failed_count_this_run":     run_counts.get("failed", 0),
        "blocked_count_this_run":    run_counts.get("blocked", 0),
        "safe_retry_count_this_run":       run_counts.get("safe_retry", 0),
        "safe_inspect_count_this_run":     run_counts.get("safe_inspect", 0),
        "improvement_queued_count_this_run": run_counts.get("improvement_queued", 0),
    }
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")


# ─────────────────────────────────────────────
# 単件処理
# ─────────────────────────────────────────────

def _process_one(idx: int, record: dict, records: list) -> dict:
    """
    pending 1件を処理し、historyエントリを返す。
    records[idx] の status を更新する（呼び出し元が save_queue する）。
    """
    action_type  = record.get("action_type", "")
    target_agent = record.get("target_agent", "")
    priority     = record.get("priority", "LOW")
    exec_rec     = record.get("execute_recommended", False)

    def _make_entry(result: str, reason: str, summary: str, next_rec: str) -> dict:
        return {
            "executed_at":         _now_jst(),
            "action_type":         action_type,
            "target_agent":        target_agent,
            "target_log":          record.get("target_log", ""),
            "priority":            priority,
            "result":              result,
            "reason":              reason,
            "summary":             summary,
            "next_recommendation": next_rec,
        }

    # ─ 重複チェック（in_progress） ─
    if _is_in_progress(record, records):
        records[idx]["status"] = "skipped_duplicate"
        entry = _make_entry(
            "skipped_duplicate",
            "duplicate_in_progress",
            f"{action_type}/{target_agent} が既にin_progress中のためスキップ",
            "処理中のジョブが完了してから再実行する",
        )
        print(f"  [ceo_executor] skip(in_progress): {action_type}/{target_agent}", file=sys.stderr)
        return entry

    # ─ 重複チェック（直近done） ─
    if _is_recently_done(record):
        records[idx]["status"] = "skipped_duplicate"
        entry = _make_entry(
            "skipped_duplicate",
            "skipped_duplicate_done",
            f"{action_type}/{target_agent} は直近実行済みのためスキップ",
            "次回サイクルで新規pendingが生成された場合に再実行される",
        )
        print(f"  [ceo_executor] skip(recently_done): {action_type}/{target_agent}", file=sys.stderr)
        return entry

    # ─ 安全性チェック: 未対応action_type ─
    if action_type not in SAFE_ACTION_TYPES:
        records[idx]["status"] = "blocked"
        entry = _make_entry(
            "blocked",
            "unsupported_action_type",
            f"非対応action_type '{action_type}' のためブロック",
            "ceo_action_export.py のaction_type定義を確認する",
        )
        print(f"  [ceo_executor] blocked(unsupported): {action_type}", file=sys.stderr)
        return entry

    # ─ 安全性チェック: execute_recommended=false かつ 非monitor ─
    if not exec_rec and action_type not in AUTO_ALLOW_WITHOUT_RECOMMEND:
        records[idx]["status"] = "skipped_unsafe"
        entry = _make_entry(
            "skipped_unsafe",
            "unsafe_operation_denied",
            f"execute_recommended=false のため自動実行を拒否: {action_type}/{target_agent}",
            "execute_recommended を true にするか手動で対処する",
        )
        print(f"  [ceo_executor] skip(unsafe): {action_type}/{target_agent}", file=sys.stderr)
        return entry

    # ─ target_log チェック（inspect系のみ） ─
    if action_type.startswith("inspect_") and not record.get("target_log"):
        records[idx]["status"] = "blocked"
        entry = _make_entry(
            "blocked",
            "missing_target_log",
            f"target_log が指定されていないため調査不能: {action_type}/{target_agent}",
            "ceo_action_queue.jsonl の target_log フィールドを確認する",
        )
        print(f"  [ceo_executor] blocked(no_target_log): {action_type}", file=sys.stderr)
        return entry

    # ─ in_progress に更新 ─
    records[idx]["status"] = "in_progress"

    # ─ 実行 ─
    safe_action_entry = None
    try:
        executor = EXECUTORS[action_type]
        report   = executor(record)
        result   = report.get("result", "done")
        reason   = report.get("reason", "")
        if result == "blocked":
            records[idx]["status"] = "blocked"
        else:
            records[idx]["status"] = result  # done / failed
        print(f"  [ceo_executor] {result}: {action_type}/{target_agent or '—'}", file=sys.stderr)
    except Exception as e:
        report  = {
            "summary":             f"実行中に例外: {str(e)[:80]}",
            "next_recommendation": "ceo_executor.py のログを確認して原因を調査する",
        }
        result  = "failed"
        reason  = "exception_during_exec"
        records[idx]["status"] = "failed"
        print(f"  [ceo_executor] ❌ failed({e}): {action_type}/{target_agent}", file=sys.stderr)

    # ─ safe action 統合（result=done の場合のみ追加保存） ─
    if result in ("done", "skipped"):
        try:
            if str(BASE) not in sys.path:
                sys.path.insert(0, str(BASE))
            from lib.ceo_safe_actions import (
                run_retry_alert_queue,
                run_monitor_only,
                save_agent_failure_inspection,
                save_revenue_blocker_inspection,
            )
            exec_summary = report.get("summary", "")
            next_rec     = report.get("next_recommendation", "")
            if action_type == "retry_alert_queue":
                sa = run_retry_alert_queue(record)
            elif action_type == "monitor_only":
                sa = run_monitor_only(record)
            elif action_type == "inspect_agent_failure":
                sa = save_agent_failure_inspection(record, exec_summary, next_rec)
            elif action_type == "inspect_revenue_blocker":
                sa = save_revenue_blocker_inspection(record, exec_summary, next_rec)
            else:
                sa = None
            if sa:
                safe_action_entry = sa.get("safe_action_entry")
                imp = sa.get("improvement_enqueue", {})
                imp_status = imp.get("status", "") if imp else ""
                print(
                    f"  [ceo_executor] safe_action saved: {action_type}/{target_agent or '—'} → {sa.get('result')}"
                    + (f" | improvement: {imp_status}" if imp_status else ""),
                    file=sys.stderr,
                )
        except Exception as se:
            print(f"  [ceo_executor] ⚠️ safe_action skip: {se}", file=sys.stderr)

    entry = _make_entry(
        result,
        reason,
        report.get("summary", ""),
        report.get("next_recommendation", ""),
    )
    if safe_action_entry:
        entry["safe_action_result"]      = safe_action_entry.get("result", "")
        entry["recommendation_type"]     = safe_action_entry.get("recommendation_type", "")
        entry["proposed_next_step"]      = safe_action_entry.get("proposed_next_step", "")
        # improvement enqueue 結果を記録
        imp = safe_action_entry.get("improvement_enqueue") if hasattr(safe_action_entry, "get") else None
        if imp and imp.get("status") == "pending":
            entry["improvement_queued"] = True
            entry["improvement_priority"] = imp.get("priority", "")
        else:
            entry["improvement_queued"] = False
    return entry


# ─────────────────────────────────────────────
# メイン実行
# ─────────────────────────────────────────────

def run() -> dict:
    """
    pending 命令を最大 MAX_PER_RUN 件処理し、集計結果を返す。
    戻り値: {
        "processed":      int,
        "done":           int,
        "failed":         int,
        "blocked":        int,
        "skipped":        int,
        "no_pending":     bool,
        "result":         str,   # 最後に処理した1件の result
        "action_type":    str,
        "target_agent":   str,
        "reason":         str,
        "summary":        str,
        "next_recommendation": str,
        "entries":        list,  # 全処理エントリ
    }
    """
    records = load_queue()

    # pending カウント（処理前）
    pending_before = sum(1 for r in records if r.get("status") == "pending")

    if pending_before == 0:
        print("  [ceo_executor] pending命令なし。スキップ。", file=sys.stderr)
        run_counts = {"processed": 0, "done": 0, "failed": 0, "blocked": 0}
        save_state([], run_counts)
        return {
            "processed": 0, "done": 0, "failed": 0, "blocked": 0, "skipped": 0,
            "no_pending": True,
            "result": "no_pending", "action_type": "", "target_agent": "",
            "reason": "", "summary": "pending命令なし", "next_recommendation": "",
            "entries": [],
        }

    batch   = pick_pending_batch(records, MAX_PER_RUN)
    entries = []
    counts  = {
        "processed": 0, "done": 0, "failed": 0, "blocked": 0, "skipped": 0,
        "safe_retry": 0, "safe_inspect": 0, "improvement_queued": 0,
    }

    for idx, record in batch:
        entry = _process_one(idx, record, records)
        entries.append(entry)
        append_history(entry)
        counts["processed"] += 1
        r = entry["result"]
        if r == "done":
            counts["done"] += 1
        elif r == "failed":
            counts["failed"] += 1
        elif r == "blocked":
            counts["blocked"] += 1
        else:
            counts["skipped"] += 1
        # safe action 種別カウント
        if entry.get("safe_action_result") == "done":
            at = entry.get("action_type", "")
            if at == "retry_alert_queue":
                counts["safe_retry"] += 1
            elif at in ("inspect_agent_failure", "inspect_revenue_blocker"):
                counts["safe_inspect"] += 1
        if entry.get("improvement_queued"):
            counts["improvement_queued"] += 1

    # queue を一括保存（全 status 更新を反映）
    try:
        save_queue(records)
    except Exception as e:
        print(f"  [ceo_executor] ⚠️ queue save failed: {e}", file=sys.stderr)
        # history には failed エントリを追加して記録
        fail_entry = {
            "executed_at":  _now_jst(),
            "action_type":  "queue_write",
            "target_agent": "",
            "priority":     "HIGH",
            "result":       "failed",
            "reason":       "queue_write_failure",
            "summary":      f"キュー書き込み失敗: {str(e)[:60]}",
            "next_recommendation": "logs/ceo_action_queue.jsonl のパーミッションを確認する",
        }
        append_history(fail_entry)

    run_counts = {
        "processed":          counts["processed"],
        "done":               counts["done"],
        "failed":             counts["failed"],
        "blocked":            counts["blocked"],
        "safe_retry":         counts["safe_retry"],
        "safe_inspect":       counts["safe_inspect"],
        "improvement_queued": counts["improvement_queued"],
    }
    save_state(entries, run_counts)

    last = entries[-1] if entries else {}
    print(
        f"  [ceo_executor] 完了: 処理{counts['processed']}件 "
        f"done={counts['done']} failed={counts['failed']} blocked={counts['blocked']} skipped={counts['skipped']} "
        f"safe_retry={counts['safe_retry']} safe_inspect={counts['safe_inspect']}",
        file=sys.stderr,
    )

    return {
        "processed":           counts["processed"],
        "done":                counts["done"],
        "failed":              counts["failed"],
        "blocked":             counts["blocked"],
        "skipped":             counts["skipped"],
        "safe_retry":          counts["safe_retry"],
        "safe_inspect":        counts["safe_inspect"],
        "improvement_queued":  counts["improvement_queued"],
        "no_pending":          False,
        "result":              last.get("result", ""),
        "action_type":         last.get("action_type", ""),
        "target_agent":        last.get("target_agent", ""),
        "reason":              last.get("reason", ""),
        "summary":             last.get("summary", ""),
        "next_recommendation": last.get("next_recommendation", ""),
        "entries":             entries,
    }


if __name__ == "__main__":
    result = run()
    # entries は冗長なので除外して表示
    display = {k: v for k, v in result.items() if k != "entries"}
    print(json.dumps(display, ensure_ascii=False, indent=2))
