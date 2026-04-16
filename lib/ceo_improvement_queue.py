#!/usr/bin/env python3
"""
ceo_improvement_queue.py — CEO改善候補キュー管理 v1.0
CEO: ミュウツー / オーナー: 人間（閲覧専用）

【役割】
  ceo_safe_action_history.jsonl の recommendation_type をもとに
  改善候補を ceo_improvement_queue.jsonl へ積む。

  今回の execute_recommended は false 固定。
  「改善候補を可視化・構造化する」まで。実行はしない。

【対象 recommendation_type】
  prompt_fix       → queue に積む
  timeout_fix      → queue に積む
  monitor_continue → queue に積む（LOW priority）
  manual_restart   → queue に積まない（履歴のみ）
  alert_retry      → queue に積まない（通知系は別管理）
  check_config     → queue に積まない

【status 遷移】
  pending → skipped_duplicate  （重複）
          → promoted           （上位キューへ昇格、将来拡張用）
          → blocked            （安全違反等）
"""

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).parent.parent
IMPROVEMENT_QUEUE_PATH   = BASE / "logs" / "ceo_improvement_queue.jsonl"
IMPROVEMENT_HISTORY_PATH = BASE / "logs" / "ceo_improvement_history.jsonl"
READY_QUEUE_PATH         = BASE / "logs" / "ceo_ready_queue.jsonl"
READY_HISTORY_PATH       = BASE / "logs" / "ceo_ready_history.jsonl"
EXEC_READY_QUEUE_PATH    = BASE / "logs" / "ceo_execution_ready_queue.jsonl"
EXEC_READY_HISTORY_PATH  = BASE / "logs" / "ceo_execution_ready_history.jsonl"
AGENT_METRICS_PATH       = BASE / "agent_metrics.json"

JST = timezone(timedelta(hours=9))

# queue に積む recommendation_type
QUEUEABLE_REC_TYPES = {"prompt_fix", "timeout_fix", "monitor_continue"}

# improvement_type → priority ベース値
BASE_PRIORITY = {
    "prompt_fix":       "MEDIUM",
    "timeout_fix":      "MEDIUM",
    "monitor_continue": "LOW",
}


# ─────────────────────────────────────────────
# ユーティリティ
# ─────────────────────────────────────────────

def _now_jst() -> str:
    return datetime.now(JST).isoformat()


def _today_jst() -> str:
    return datetime.now(JST).strftime("%Y-%m-%d")


def _load_jsonl(path: Path) -> list:
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
    return records


def _load_json_safe(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _agent_success_rate(target_agent: str) -> float:
    """agent_metrics.json から success_rate を取得する"""
    am = _load_json_safe(AGENT_METRICS_PATH)
    for aid, v in am.get("agents", {}).items():
        if v.get("name_ja") == target_agent:
            return v.get("success_rate", 1.0)
    return 1.0


def _agent_empty_count(target_agent: str) -> int:
    """agent_metrics.json から empty_output_count を取得する"""
    am = _load_json_safe(AGENT_METRICS_PATH)
    for aid, v in am.get("agents", {}).items():
        if v.get("name_ja") == target_agent:
            return v.get("empty_output_count", 0)
    return 0


def _get_agent_metrics(target_agent: str) -> dict:
    """agent_metrics.json から対象エージェントの主要指標を返す"""
    am = _load_json_safe(AGENT_METRICS_PATH)
    for aid, v in am.get("agents", {}).items():
        if v.get("name_ja") == target_agent:
            return {
                "success_rate":        v.get("success_rate", 1.0),
                "hard_fail_count":     v.get("hard_fail_count", 0),
                "empty_output_count":  v.get("empty_output_count", 0),
                "contamination_count": v.get("contamination_count", 0),
            }
    return {
        "success_rate": 1.0,
        "hard_fail_count": 0,
        "empty_output_count": 0,
        "contamination_count": 0,
    }


# MANUAL系エージェント名（手動介入が必要なもの）
MANUAL_AGENTS = {"manual_restart", "manual"}

_TIMEOUT_KEYWORDS = ("timeout", "time out", "タイムアウト")


def _decide_safety(improvement_type: str, target_agent: str, proposed_change: str) -> dict:
    """
    improvement_type + エージェント指標 から安全昇格判定を行う。

    戻り値:
      {
        "execute_recommended": bool,
        "recommendation_reason": str,
        "safety_class": "SAFE"|"REVIEW"|"BLOCKED",
        "human_review_required": bool,
      }
    """
    if improvement_type == "manual_restart":
        return {
            "execute_recommended":   False,
            "recommendation_reason": "手動再起動は自動実行不可。人間レビュー必須。",
            "safety_class":          "BLOCKED",
            "human_review_required": True,
        }

    if improvement_type not in QUEUEABLE_REC_TYPES:
        return {
            "execute_recommended":   False,
            "recommendation_reason": f"improvement_type '{improvement_type}' は自動実行対象外。",
            "safety_class":          "BLOCKED",
            "human_review_required": True,
        }

    metrics = _get_agent_metrics(target_agent)
    sr      = metrics["success_rate"]
    hf      = metrics["hard_fail_count"]
    ec      = metrics["empty_output_count"]
    cc      = metrics["contamination_count"]

    if improvement_type == "monitor_continue":
        return {
            "execute_recommended":   True,
            "recommendation_reason": f"{target_agent or '全体'}は正常範囲内。継続監視で対応可能。",
            "safety_class":          "SAFE",
            "human_review_required": False,
        }

    elif improvement_type == "prompt_fix":
        is_manual = target_agent.lower() in MANUAL_AGENTS
        if sr < 0.85 and hf == 0 and cc <= 3 and not is_manual:
            reason = (
                f"成功率{sr:.0%}(<85%) / hard_fail=0 / 汚染={cc}件(≤3) → 自動修正安全。"
            )
            return {
                "execute_recommended":   True,
                "recommendation_reason": reason,
                "safety_class":          "SAFE",
                "human_review_required": False,
            }
        else:
            parts = []
            if sr >= 0.85:
                parts.append(f"成功率{sr:.0%}は基準(85%)以上")
            if hf > 0:
                parts.append(f"hard_fail={hf}件あり")
            if cc > 3:
                parts.append(f"汚染={cc}件(>3)")
            if is_manual:
                parts.append("manual系エージェント")
            reason = "自動実行条件未達: " + " / ".join(parts) if parts else "条件未達"
            return {
                "execute_recommended":   False,
                "recommendation_reason": reason,
                "safety_class":          "REVIEW",
                "human_review_required": True,
            }

    elif improvement_type == "timeout_fix":
        has_keyword = any(kw in proposed_change.lower() for kw in _TIMEOUT_KEYWORDS)
        if ec >= 3 and hf == 0 and has_keyword:
            reason = (
                f"空出力={ec}回(≥3) / hard_fail=0 / timeout文言あり → 自動修正安全。"
            )
            return {
                "execute_recommended":   True,
                "recommendation_reason": reason,
                "safety_class":          "SAFE",
                "human_review_required": False,
            }
        else:
            parts = []
            if ec < 3:
                parts.append(f"空出力={ec}回(<3)")
            if hf > 0:
                parts.append(f"hard_fail={hf}件あり")
            if not has_keyword:
                parts.append("proposed_changeにtimeout文言なし")
            reason = "自動実行条件未達: " + " / ".join(parts) if parts else "条件未達"
            return {
                "execute_recommended":   False,
                "recommendation_reason": reason,
                "safety_class":          "REVIEW",
                "human_review_required": True,
            }

    # fallback
    return {
        "execute_recommended":   False,
        "recommendation_reason": "未対応のimprovement_type。",
        "safety_class":          "BLOCKED",
        "human_review_required": True,
    }


# ─────────────────────────────────────────────
# priority 決定
# ─────────────────────────────────────────────

def _decide_priority(improvement_type: str, target_agent: str, proposed_change: str) -> str:
    """
    improvement_type + 実測値 から priority を決定する。
    - prompt_fix:  success_rate < 0.85 → HIGH、それ以外 → MEDIUM
    - timeout_fix: empty_output_count >= 3 or 'タイムアウト' in proposed → HIGH
    - monitor_continue: LOW 固定
    """
    if improvement_type == "prompt_fix":
        rate = _agent_success_rate(target_agent)
        return "HIGH" if rate < 0.85 else "MEDIUM"
    elif improvement_type == "timeout_fix":
        empty = _agent_empty_count(target_agent)
        if empty >= 3 or "タイムアウト" in proposed_change or "timeout" in proposed_change.lower():
            return "HIGH"
        return "MEDIUM"
    else:
        return "LOW"


# ─────────────────────────────────────────────
# 重複防止
# ─────────────────────────────────────────────

def _is_duplicate_pending(target_agent: str, improvement_type: str, proposed_change: str) -> bool:
    """
    同一 target_agent + improvement_type + proposed_change の pending が既にあれば True。
    """
    existing = _load_jsonl(IMPROVEMENT_QUEUE_PATH)
    for r in existing:
        if (r.get("status") == "pending"
                and r.get("target_agent") == target_agent
                and r.get("improvement_type") == improvement_type
                and r.get("proposed_change") == proposed_change):
            return True
    return False


def _is_same_day_done_improvement(target_agent: str, improvement_type: str) -> bool:
    """
    同一 target_agent + improvement_type が本日 history で done/promoted 済みなら True。
    """
    today = _today_jst()
    for h in _load_jsonl(IMPROVEMENT_HISTORY_PATH):
        if (h.get("target_agent") == target_agent
                and h.get("improvement_type") == improvement_type
                and h.get("status") in ("done", "promoted")
                and h.get("generated_at", "").startswith(today)):
            return True
    return False


# ─────────────────────────────────────────────
# キュー操作
# ─────────────────────────────────────────────

def _append_queue(record: dict) -> None:
    IMPROVEMENT_QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with IMPROVEMENT_QUEUE_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _append_history(record: dict) -> None:
    IMPROVEMENT_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with IMPROVEMENT_HISTORY_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


# ─────────────────────────────────────────────
# メイン: safe action 結果 → improvement queue
# ─────────────────────────────────────────────

def enqueue_from_safe_action(safe_entry: dict) -> dict:
    """
    ceo_safe_action_history の1エントリを受け取り、
    improvement_queue に積む（またはスキップ理由を返す）。

    戻り値:
      {"status": "pending"|"skipped_duplicate"|"skipped_not_queueable"|"blocked",
       "improvement_type": str, "priority": str, "reason": str}
    """
    rec_type     = safe_entry.get("recommendation_type", "")
    target_agent = safe_entry.get("target_agent", "")
    proposed     = safe_entry.get("proposed_next_step", "")
    action_type  = safe_entry.get("action_type", "")
    summary      = safe_entry.get("summary", "")
    now          = _now_jst()

    # queue 対象外
    if rec_type not in QUEUEABLE_REC_TYPES:
        return {
            "status":           "skipped_not_queueable",
            "improvement_type": rec_type,
            "priority":         "—",
            "reason":           f"recommendation_type '{rec_type}' はqueue対象外",
        }

    improvement_type = rec_type  # 1:1 対応
    priority         = _decide_priority(improvement_type, target_agent, proposed)

    # 同日 done チェック
    if _is_same_day_done_improvement(target_agent, improvement_type):
        hist_entry = {
            "generated_at":    now,
            "source_action":   action_type,
            "target_agent":    target_agent,
            "improvement_type": improvement_type,
            "status":          "skipped_duplicate",
            "reason":          "同日内に同内容が処理済み",
        }
        _append_history(hist_entry)
        return {
            "status":           "skipped_duplicate",
            "improvement_type": improvement_type,
            "priority":         priority,
            "reason":           "同日内に同内容が処理済み",
        }

    # pending 重複チェック
    if _is_duplicate_pending(target_agent, improvement_type, proposed):
        hist_entry = {
            "generated_at":    now,
            "source_action":   action_type,
            "target_agent":    target_agent,
            "improvement_type": improvement_type,
            "status":          "skipped_duplicate",
            "reason":          "同内容がpendingキューに既に存在",
        }
        _append_history(hist_entry)
        return {
            "status":           "skipped_duplicate",
            "improvement_type": improvement_type,
            "priority":         priority,
            "reason":           "同内容がpendingキューに既に存在",
        }

    # reason 生成
    if improvement_type == "prompt_fix":
        rate = _agent_success_rate(target_agent)
        reason = (
            f"{target_agent}の成功率{rate:.0%}が基準(85%)未満。"
            f"プロンプト修正で改善余地あり。"
            if rate < 0.85 else
            f"{target_agent}で失敗パターンを検出。プロンプト最適化が必要。"
        )
    elif improvement_type == "timeout_fix":
        empty = _agent_empty_count(target_agent)
        reason = (
            f"{target_agent}で空出力{empty}回を検出。タイムアウト設定の見直しが必要。"
            if empty > 0 else
            f"{target_agent}でタイムアウト系エラーを検出。設定の見直しが必要。"
        )
    else:  # monitor_continue
        reason = f"{target_agent or '全体'}が正常範囲内。継続監視を推奨。"

    safety = _decide_safety(improvement_type, target_agent, proposed)

    queue_record = {
        "generated_at":          now,
        "source_action_type":    action_type,
        "target_agent":          target_agent,
        "improvement_type":      improvement_type,
        "priority":              priority,
        "reason":                reason,
        "proposed_change":       proposed,
        "status":                "pending",
        "execute_recommended":   safety["execute_recommended"],
        "recommendation_reason": safety["recommendation_reason"],
        "safety_class":          safety["safety_class"],
        "human_review_required": safety["human_review_required"],
    }
    _append_queue(queue_record)

    hist_entry = {
        "generated_at":          now,
        "source_action":         action_type,
        "target_agent":          target_agent,
        "improvement_type":      improvement_type,
        "priority":              priority,
        "status":                "pending",
        "reason":                reason,
        "execute_recommended":   safety["execute_recommended"],
        "recommendation_reason": safety["recommendation_reason"],
        "safety_class":          safety["safety_class"],
        "human_review_required": safety["human_review_required"],
    }
    _append_history(hist_entry)

    return {
        "status":                "pending",
        "improvement_type":      improvement_type,
        "priority":              priority,
        "reason":                reason,
        "execute_recommended":   safety["execute_recommended"],
        "safety_class":          safety["safety_class"],
    }


def enqueue_batch_from_safe_history(safe_entries: list) -> dict:
    """
    safe action history のリストを受け取り、全件に enqueue_from_safe_action を適用する。
    result=done のもののみ対象。
    戻り値: {"queued": int, "skipped_dup": int, "skipped_na": int}
    """
    counts = {"queued": 0, "skipped_dup": 0, "skipped_na": 0}
    for entry in safe_entries:
        if entry.get("result") != "done":
            continue
        r = enqueue_from_safe_action(entry)
        s = r["status"]
        if s == "pending":
            counts["queued"] += 1
        elif s == "skipped_duplicate":
            counts["skipped_dup"] += 1
        else:
            counts["skipped_na"] += 1
    return counts


def get_queue_stats() -> dict:
    """improvement_queue.jsonl の現在の件数統計を返す"""
    records = _load_jsonl(IMPROVEMENT_QUEUE_PATH)
    pending = [r for r in records if r.get("status") == "pending"]
    high    = sum(1 for r in pending if r.get("priority") == "HIGH")
    medium  = sum(1 for r in pending if r.get("priority") == "MEDIUM")
    low     = sum(1 for r in pending if r.get("priority") == "LOW")
    safe_n  = sum(1 for r in pending if r.get("safety_class") == "SAFE")
    review_n = sum(1 for r in pending if r.get("safety_class") == "REVIEW")
    blocked_n = sum(1 for r in pending if r.get("safety_class") == "BLOCKED")
    exec_true = sum(1 for r in pending if r.get("execute_recommended") is True)
    latest  = records[-1] if records else {}
    return {
        "total":        len(records),
        "pending":      len(pending),
        "high":         high,
        "medium":       medium,
        "low":          low,
        "safe":         safe_n,
        "review":       review_n,
        "blocked":      blocked_n,
        "exec_true":    exec_true,
        "latest_agent":    latest.get("target_agent", ""),
        "latest_type":     latest.get("improvement_type", ""),
        "latest_priority": latest.get("priority", ""),
        "latest_status":   latest.get("status", ""),
    }


# ─────────────────────────────────────────────
# SAFE昇格キュー (ceo_ready_queue.jsonl)
# ─────────────────────────────────────────────

def _make_duplicate_key(target_agent: str, improvement_type: str, proposed_change: str) -> str:
    """重複防止キーを生成する"""
    raw = f"{target_agent}|{improvement_type}|{proposed_change}"
    return raw.strip()


def _is_ready_duplicate(duplicate_key: str) -> bool:
    """同一 duplicate_key が ready_queue に pending/done で存在すれば True"""
    for r in _load_jsonl(READY_QUEUE_PATH):
        if (r.get("duplicate_key") == duplicate_key
                and r.get("status") in ("pending", "done")):
            return True
    return False


def _append_ready_queue(record: dict) -> None:
    READY_QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with READY_QUEUE_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _append_ready_history(record: dict) -> None:
    READY_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with READY_HISTORY_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _append_exec_ready_queue(record: dict) -> None:
    EXEC_READY_QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with EXEC_READY_QUEUE_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _append_exec_ready_history(record: dict) -> None:
    EXEC_READY_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with EXEC_READY_HISTORY_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def promote_safe_candidates() -> dict:
    """
    ceo_improvement_queue.jsonl の pending レコードのうち
    execute_recommended==True かつ safety_class=="SAFE" のものを
    ceo_ready_queue.jsonl へコピーする。

    戻り値: {"promoted": int, "skipped_duplicate": int, "skipped_not_safe": int}
    """
    counts = {"promoted": 0, "skipped_duplicate": 0, "skipped_not_safe": 0}
    now = _now_jst()

    for rec in _load_jsonl(IMPROVEMENT_QUEUE_PATH):
        if rec.get("status") != "pending":
            continue
        if not (rec.get("execute_recommended") is True and rec.get("safety_class") == "SAFE"):
            counts["skipped_not_safe"] += 1
            continue

        target_agent    = rec.get("target_agent", "")
        improvement_type = rec.get("improvement_type", "")
        proposed_change  = rec.get("proposed_change", "")
        dup_key = _make_duplicate_key(target_agent, improvement_type, proposed_change)

        if _is_ready_duplicate(dup_key):
            _append_ready_history({
                "promoted_at":       now,
                "source_generated_at": rec.get("generated_at", ""),
                "target_agent":      target_agent,
                "improvement_type":  improvement_type,
                "priority":          rec.get("priority", ""),
                "status":            "promoted_duplicate",
                "reason":            "同一duplicate_keyがready_queueに既に存在",
                "duplicate_key":     dup_key,
            })
            counts["skipped_duplicate"] += 1
            continue

        ready_record = {
            "promoted_at":           now,
            "source_generated_at":   rec.get("generated_at", ""),
            "source_action_type":    rec.get("source_action_type", ""),
            "target_agent":          target_agent,
            "improvement_type":      improvement_type,
            "priority":              rec.get("priority", ""),
            "reason":                rec.get("reason", ""),
            "proposed_change":       proposed_change,
            "execute_recommended":   True,
            "safety_class":          "SAFE",
            "human_review_required": rec.get("human_review_required", False),
            "status":                "pending",
            "promoted_from":         "ceo_improvement_queue",
            "duplicate_key":         dup_key,
        }
        _append_ready_queue(ready_record)

        _append_ready_history({
            "promoted_at":         now,
            "source_generated_at": rec.get("generated_at", ""),
            "target_agent":        target_agent,
            "improvement_type":    improvement_type,
            "priority":            rec.get("priority", ""),
            "status":              "pending",
            "reason":              "SAFE候補をready_queueへ昇格",
            "duplicate_key":       dup_key,
        })
        counts["promoted"] += 1

    return counts


def get_ready_queue_stats() -> dict:
    """ceo_ready_queue.jsonl / ceo_execution_ready_queue.jsonl の現在の件数統計を返す"""
    records  = _load_jsonl(READY_QUEUE_PATH)
    hist     = _load_jsonl(READY_HISTORY_PATH)
    er_recs  = _load_jsonl(EXEC_READY_QUEUE_PATH)
    er_hist  = _load_jsonl(EXEC_READY_HISTORY_PATH)
    pending  = [r for r in records if r.get("status") == "pending"]
    archived = [r for r in records if r.get("status") == "archived"]
    blocked  = [r for r in records if r.get("status") == "blocked"]
    high     = sum(1 for r in pending if r.get("priority") == "HIGH")
    medium   = sum(1 for r in pending if r.get("priority") == "MEDIUM")
    dup_cnt  = sum(1 for h in hist if h.get("status") == "promoted_duplicate")
    er_pending = [r for r in er_recs if r.get("status") == "pending"]
    er_dup   = sum(1 for h in er_hist if h.get("status") == "exec_ready_duplicate")
    latest   = records[-1] if records else {}
    er_latest = er_recs[-1] if er_recs else {}
    return {
        "total":                   len(records),
        "pending":                 len(pending),
        "archived":                len(archived),
        "blocked":                 len(blocked),
        "high":                    high,
        "medium":                  medium,
        "duplicate_count":         dup_cnt,
        "exec_ready_pending":      len(er_pending),
        "exec_ready_dup":          er_dup,
        "latest_agent":            latest.get("target_agent", ""),
        "latest_type":             latest.get("improvement_type", ""),
        "latest_priority":         latest.get("priority", ""),
        "latest_status":           latest.get("status", ""),
        "latest_er_agent":         er_latest.get("target_agent", ""),
        "latest_er_type":          er_latest.get("improvement_type", ""),
        "latest_er_priority":      er_latest.get("priority", ""),
    }


# ─────────────────────────────────────────────
# EXECUTION_READY昇格（ミュウツーCEO自律判断）
# ─────────────────────────────────────────────

def _is_exec_ready_duplicate(duplicate_key: str) -> bool:
    """同一 duplicate_key が execution_ready_queue に pending で存在すれば True"""
    for r in _load_jsonl(EXEC_READY_QUEUE_PATH):
        if r.get("duplicate_key") == duplicate_key and r.get("status") == "pending":
            return True
    return False


def promote_to_execution_ready() -> dict:
    """
    ceo_ready_queue.jsonl の pending レコードのうち
    safety_class=="SAFE" かつ execute_recommended==True のものを
    ceo_execution_ready_queue.jsonl へ昇格する。
    人間承認不要。ミュウツーCEOの自律判断。

    戻り値: {"promoted": int, "skipped_duplicate": int, "skipped_not_eligible": int}
    """
    counts = {"promoted": 0, "skipped_duplicate": 0, "skipped_not_eligible": 0}
    now = _now_jst()

    for rec in _load_jsonl(READY_QUEUE_PATH):
        if rec.get("status") != "pending":
            continue
        if not (rec.get("safety_class") == "SAFE" and rec.get("execute_recommended") is True):
            counts["skipped_not_eligible"] += 1
            continue

        dup_key = rec.get("duplicate_key") or _make_duplicate_key(
            rec.get("target_agent", ""),
            rec.get("improvement_type", ""),
            rec.get("proposed_change", ""),
        )

        if _is_exec_ready_duplicate(dup_key):
            _append_exec_ready_history({
                "promoted_at":   now,
                "target_agent":  rec.get("target_agent", ""),
                "improvement_type": rec.get("improvement_type", ""),
                "priority":      rec.get("priority", ""),
                "status":        "exec_ready_duplicate",
                "reason":        "同一duplicate_keyがexecution_ready_queueに既に存在",
                "duplicate_key": dup_key,
            })
            counts["skipped_duplicate"] += 1
            continue

        er_record = {
            "promoted_at":         now,
            "source_promoted_at":  rec.get("promoted_at", ""),
            "source_action_type":  rec.get("source_action_type", ""),
            "target_agent":        rec.get("target_agent", ""),
            "improvement_type":    rec.get("improvement_type", ""),
            "priority":            rec.get("priority", ""),
            "reason":              rec.get("reason", ""),
            "proposed_change":     rec.get("proposed_change", ""),
            "execute_recommended": True,
            "safety_class":        "SAFE",
            "human_review_required": False,
            "status":              "pending",
            "promoted_from":       "ceo_ready_queue",
            "ceo_judgment":        "ミュウツーCEO自律判断",
            "duplicate_key":       dup_key,
        }
        _append_exec_ready_queue(er_record)
        _append_exec_ready_history({
            "promoted_at":     now,
            "target_agent":    rec.get("target_agent", ""),
            "improvement_type": rec.get("improvement_type", ""),
            "priority":        rec.get("priority", ""),
            "status":          "pending",
            "reason":          "READYキューからミュウツーCEO判断で実行候補レーンへ昇格",
            "duplicate_key":   dup_key,
        })
        counts["promoted"] += 1

    return counts


# ─────────────────────────────────────────────
# 実行シミュレーション (ceo_execution_simulation.jsonl)
# ─────────────────────────────────────────────

SIM_QUEUE_PATH   = BASE / "logs" / "ceo_execution_simulation.jsonl"
SIM_HISTORY_PATH = BASE / "logs" / "ceo_execution_simulation_history.jsonl"

# エージェント名（カタカナ） → ファイル名マッピング
_AGENT_FILE_MAP = {
    "バタフリー":  ("agents/butterfree.md",),
    "X投稿B":      ("agents/x_post_b.md",),
    "X投稿":       ("agents/x_post.md",),
    "WP投稿":      ("agents/wordpress_post.md",),
    "ミュウツー":  ("agents/mewtwo.md",),
    "デオキシス":  ("agents/deoxys.md",),
    "メタモン":    ("agents/metamon.md",),
    "イーブイ":    ("agents/eevee.md",),
    "ジラーチ":    ("agents/jirachi.md",),
    "サーナイト":  ("agents/gardevoir_hook_critic.md",),
    "アルセウス":  ("agents/arceus.md",),
    "ラプラス":    ("agents/lapras.md",),
    "ミミッキュ":  ("agents/mimikyu.md",),
    "フシギバナ":  ("agents/venusaur.md",),
    "ゲンガー":    ("agents/gengar.md",),
    "カイリュー":  ("agents/kairyu_kpop.md",),
    "サンダー":    ("agents/zapdos.md",),
    "ペルシアン":  ("agents/persian.md",),
    "ソーナンス":  ("agents/wobbuffet.md",),
}

_COMMON_CONFIG = "config/agent_directives.json"
_PIPELINE_LOG  = "logs/pipeline.jsonl"
_STEPS_LOG     = "logs/pipeline_steps.jsonl"


def _sim_target_files(improvement_type: str, target_agent: str) -> list:
    files = []
    if improvement_type in ("prompt_fix", "timeout_fix"):
        files.append(_COMMON_CONFIG)
        for name, fps in _AGENT_FILE_MAP.items():
            if name in target_agent:
                files.extend(fps)
                break
    return files


def _sim_target_logs(improvement_type: str, target_agent: str) -> list:
    if improvement_type == "monitor_continue":
        return ["dashboard_summary.json", "agent_metrics.json"]
    logs = [_PIPELINE_LOG, _STEPS_LOG]
    if "X投稿" in target_agent:
        logs.append("logs/gardevoir_hook.jsonl")
    return logs


_SIM_TYPE_MAP = {
    "prompt_fix":       "prompt_change_simulation",
    "timeout_fix":      "timeout_change_simulation",
    "monitor_continue": "monitor_only_simulation",
}

_PREDICTED_EFFECT_MAP = {
    "prompt_fix":       "出力品質改善により成功率回復が見込まれる",
    "timeout_fix":      "空出力・停止頻度の減少が見込まれる",
    "monitor_continue": "追加変更なしで継続監視する",
}

_RISK_LEVEL_MAP = {
    "prompt_fix":       "medium",
    "timeout_fix":      "medium",
    "monitor_continue": "low",
}


def _is_sim_duplicate(duplicate_key: str) -> bool:
    for r in _load_jsonl(SIM_QUEUE_PATH):
        if r.get("duplicate_key") == duplicate_key and r.get("status") in ("pending", "done"):
            return True
    return False


def _append_sim_queue(record: dict) -> None:
    SIM_QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SIM_QUEUE_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _append_sim_history(record: dict) -> None:
    SIM_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SIM_HISTORY_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def simulate_execution_ready() -> dict:
    """
    ceo_execution_ready_queue.jsonl の pending レコードを
    ceo_execution_simulation.jsonl へコピーし、
    「もし実行するなら何を触るか」を記録する。
    実際の実行は行わない。write_scope は常に "none"。

    戻り値: {"simulated": int, "skipped_duplicate": int}
    """
    counts = {"simulated": 0, "skipped_duplicate": 0}
    now = _now_jst()

    for rec in _load_jsonl(EXEC_READY_QUEUE_PATH):
        if rec.get("status") != "pending":
            continue

        target_agent    = rec.get("target_agent", "")
        improvement_type = rec.get("improvement_type", "")
        proposed_change  = rec.get("proposed_change", "")
        dup_key = rec.get("duplicate_key") or _make_duplicate_key(
            target_agent, improvement_type, proposed_change
        )

        if _is_sim_duplicate(dup_key):
            _append_sim_history({
                "simulated_at":  now,
                "target_agent":  target_agent,
                "improvement_type": improvement_type,
                "status":        "simulated_duplicate",
                "reason":        "同一duplicate_keyがsimulationに既に存在",
                "duplicate_key": dup_key,
            })
            # execution_ready_history にも記録
            _append_exec_ready_history({
                "promoted_at":       now,
                "target_agent":      target_agent,
                "improvement_type":  improvement_type,
                "priority":          rec.get("priority", ""),
                "status":            "simulation_skipped",
                "simulation_promoted": False,
                "simulation_reason": "duplicate_keyが既に存在",
                "duplicate_key":     dup_key,
            })
            counts["skipped_duplicate"] += 1
            continue

        sim_type    = _SIM_TYPE_MAP.get(improvement_type, "generic_simulation")
        risk_level  = _RISK_LEVEL_MAP.get(improvement_type, "high")
        effect      = _PREDICTED_EFFECT_MAP.get(improvement_type, "影響範囲不明")
        tgt_files   = _sim_target_files(improvement_type, target_agent)
        tgt_logs    = _sim_target_logs(improvement_type, target_agent)

        sim_record = {
            "simulated_at":        now,
            "source_promoted_at":  rec.get("promoted_at", ""),
            "source_action_type":  rec.get("source_action_type", ""),
            "target_agent":        target_agent,
            "improvement_type":    improvement_type,
            "priority":            rec.get("priority", ""),
            "reason":              rec.get("reason", ""),
            "proposed_change":     proposed_change,
            "execute_recommended": True,
            "safety_class":        rec.get("safety_class", "SAFE"),
            "status":              "pending",
            "simulated_from":      "ceo_execution_ready_queue",
            "duplicate_key":       dup_key,
            "simulation_type":     sim_type,
            "target_files":        tgt_files,
            "target_logs":         tgt_logs,
            "predicted_effect":    effect,
            "risk_level":          risk_level,
            "write_scope":         "none",
            "execution_blocked":   True,
            "ceo_judgment":        "ミュウツーCEO実行前シミュレーション",
        }
        _append_sim_queue(sim_record)

        _append_sim_history({
            "simulated_at":    now,
            "target_agent":    target_agent,
            "improvement_type": improvement_type,
            "priority":        rec.get("priority", ""),
            "simulation_type": sim_type,
            "risk_level":      risk_level,
            "status":          "pending",
            "reason":          "execution_ready_queueからシミュレーションレーンへ登録",
            "duplicate_key":   dup_key,
        })

        # execution_ready_history にも昇格記録
        _append_exec_ready_history({
            "promoted_at":         now,
            "target_agent":        target_agent,
            "improvement_type":    improvement_type,
            "priority":            rec.get("priority", ""),
            "status":              "simulation_registered",
            "simulation_promoted": True,
            "simulation_reason":   f"{sim_type} / risk={risk_level}",
            "duplicate_key":       dup_key,
        })
        counts["simulated"] += 1

    return counts


def get_simulation_stats() -> dict:
    records = _load_jsonl(SIM_QUEUE_PATH)
    hist    = _load_jsonl(SIM_HISTORY_PATH)
    pending = [r for r in records if r.get("status") == "pending"]
    high_r  = sum(1 for r in pending if r.get("risk_level") == "high")
    med_r   = sum(1 for r in pending if r.get("risk_level") == "medium")
    low_r   = sum(1 for r in pending if r.get("risk_level") == "low")
    dup_cnt = sum(1 for h in hist if h.get("status") == "simulated_duplicate")
    latest  = records[-1] if records else {}
    return {
        "total":        len(records),
        "pending":      len(pending),
        "high_risk":    high_r,
        "medium_risk":  med_r,
        "low_risk":     low_r,
        "dup_count":    dup_cnt,
        "latest_agent": latest.get("target_agent", ""),
        "latest_sim_type": latest.get("simulation_type", ""),
        "latest_risk":  latest.get("risk_level", ""),
        "latest_status": latest.get("status", ""),
    }


# ─────────────────────────────────────────────
# 実行優先順位付け (ceo_execution_ranked_queue.jsonl)
# ─────────────────────────────────────────────

RANKED_QUEUE_PATH   = BASE / "logs" / "ceo_execution_ranked_queue.jsonl"
RANKED_HISTORY_PATH = BASE / "logs" / "ceo_execution_ranked_history.jsonl"

# 売上直結AI（カタカナ名）
_REVENUE_CRITICAL_AGENTS = {
    "バタフリー", "サーナイト", "カイリュー", "WP投稿", "アルセウス", "X投稿B",
}

_IMPACT_BASE = {
    "prompt_fix":       0.70,
    "timeout_fix":      0.78,
    "monitor_continue": 0.20,
}

_RISK_BASE = {
    "low":    0.20,
    "medium": 0.50,
    "high":   0.80,
}


def _calc_impact_score(rec: dict) -> float:
    itype   = rec.get("improvement_type", "")
    prio    = rec.get("priority", "")
    agent   = rec.get("target_agent", "") or ""
    effect  = rec.get("predicted_effect", "") or ""
    score   = _IMPACT_BASE.get(itype, 0.40)
    if prio == "HIGH":
        score += 0.10
    elif prio == "MEDIUM":
        score += 0.05
    if agent in _REVENUE_CRITICAL_AGENTS:
        score += 0.10
    if "成功率回復" in effect or "停止頻度の減少" in effect:
        score += 0.05
    return min(round(score, 3), 1.0)


def _calc_risk_score(rec: dict) -> float:
    risk_level  = rec.get("risk_level", "medium")
    sim_type    = rec.get("simulation_type", "")
    itype       = rec.get("improvement_type", "")
    tfiles      = rec.get("target_files", []) or []
    score       = _RISK_BASE.get(risk_level, 0.50)
    if len(tfiles) >= 2:
        score += 0.05
    if sim_type == "generic_simulation":
        score += 0.10
    if itype == "monitor_continue":
        score -= 0.10
    return min(max(round(score, 3), 0.0), 1.0)


def _calc_estimated_scope(rec: dict) -> str:
    n = len(rec.get("target_files", []) or [])
    if n == 0:
        return "none"
    if n == 1:
        return "small"
    if n == 2:
        return "medium"
    return "large"


def _calc_priority_score(impact: float, risk: float) -> float:
    return round((impact * 0.65) + ((1.0 - risk) * 0.35), 3)


def _is_ranked_duplicate(duplicate_key: str) -> bool:
    for r in _load_jsonl(RANKED_QUEUE_PATH):
        if (r.get("duplicate_key") == duplicate_key
                and r.get("status") in ("pending", "held", "archived")):
            return True
    return False


def _append_ranked_queue(record: dict) -> None:
    RANKED_QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with RANKED_QUEUE_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _append_ranked_history(record: dict) -> None:
    RANKED_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with RANKED_HISTORY_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def rank_execution_simulations() -> dict:
    """
    ceo_execution_simulation.jsonl の pending レコードをスコアリングし、
    ceo_execution_ranked_queue.jsonl へ優先順位付きで登録する。
    実行は行わない。可視化・順位付けのみ。

    戻り値: {"ranked": int, "skipped_duplicate": int}
    """
    counts = {"ranked": 0, "skipped_duplicate": 0}
    now = _now_jst()

    # スコア計算（全 pending）
    candidates = []
    for rec in _load_jsonl(SIM_QUEUE_PATH):
        if rec.get("status") != "pending":
            continue
        dup_key = rec.get("duplicate_key") or _make_duplicate_key(
            rec.get("target_agent", ""),
            rec.get("improvement_type", ""),
            rec.get("proposed_change", ""),
        )
        if _is_ranked_duplicate(dup_key):
            _append_ranked_history({
                "ranked_at":      now,
                "target_agent":   rec.get("target_agent", ""),
                "improvement_type": rec.get("improvement_type", ""),
                "status":         "ranked_duplicate",
                "reason":         "同一duplicate_keyがranked_queueに既に存在",
                "duplicate_key":  dup_key,
            })
            _append_sim_history({
                "simulated_at":    now,
                "target_agent":    rec.get("target_agent", ""),
                "improvement_type": rec.get("improvement_type", ""),
                "status":          "ranking_skipped",
                "ranked_promoted": False,
                "ranked_reason":   "ranked_queue重複のためスキップ",
                "duplicate_key":   dup_key,
            })
            counts["skipped_duplicate"] += 1
            continue

        impact  = _calc_impact_score(rec)
        risk    = _calc_risk_score(rec)
        p_score = _calc_priority_score(impact, risk)
        scope   = _calc_estimated_scope(rec)
        exec_rec = rec.get("execute_recommended", True)
        sc_cls   = rec.get("safety_class", "SAFE")

        send_ok = (exec_rec is True and sc_cls == "SAFE" and p_score >= 0.60)

        if not send_ok:
            if exec_rec is not True:
                hold_reason = "実行推奨が false"
            elif sc_cls != "SAFE":
                hold_reason = "SAFE ではない"
            elif rec.get("risk_level") == "high":
                hold_reason = "リスク高"
            elif p_score < 0.60:
                hold_reason = "優先度スコア不足"
            else:
                hold_reason = "保留"
        else:
            hold_reason = ""

        candidates.append({
            "rec":        rec,
            "dup_key":    dup_key,
            "impact":     impact,
            "risk":       risk,
            "p_score":    p_score,
            "scope":      scope,
            "send_ok":    send_ok,
            "hold_reason": hold_reason,
        })

    # execution_order 付与（send_ok=True のみ）
    send_candidates = sorted(
        [c for c in candidates if c["send_ok"]],
        key=lambda c: (-c["p_score"], -c["impact"], c["rec"].get("target_agent", "")),
    )
    order_map = {id(c): i + 1 for i, c in enumerate(send_candidates)}

    for c in candidates:
        rec       = c["rec"]
        send_ok   = c["send_ok"]
        exe_order = order_map.get(id(c), 0)
        status    = "pending" if send_ok else "held"

        ranked_rec = {
            "ranked_at":          now,
            "source_simulated_at": rec.get("simulated_at", ""),
            "source_action_type": rec.get("source_action_type", ""),
            "target_agent":       rec.get("target_agent", ""),
            "improvement_type":   rec.get("improvement_type", ""),
            "simulation_type":    rec.get("simulation_type", ""),
            "priority":           rec.get("priority", ""),
            "reason":             rec.get("reason", ""),
            "proposed_change":    rec.get("proposed_change", ""),
            "execute_recommended": rec.get("execute_recommended", True),
            "safety_class":       rec.get("safety_class", "SAFE"),
            "predicted_effect":   rec.get("predicted_effect", ""),
            "risk_level":         rec.get("risk_level", "medium"),
            "impact_score":       c["impact"],
            "risk_score":         c["risk"],
            "priority_score":     c["p_score"],
            "estimated_scope":    c["scope"],
            "ceo_send_recommended": send_ok,
            "hold_reason":        c["hold_reason"],
            "execution_order":    exe_order,
            "status":             status,
            "ranked_from":        "ceo_execution_simulation",
            "duplicate_key":      c["dup_key"],
            "ceo_judgment":       "ミュウツーCEO実行候補順位付け",
        }
        _append_ranked_queue(ranked_rec)
        _append_ranked_history({
            "ranked_at":        now,
            "target_agent":     rec.get("target_agent", ""),
            "improvement_type": rec.get("improvement_type", ""),
            "priority_score":   c["p_score"],
            "execution_order":  exe_order,
            "status":           status,
            "reason":           f"priority_score={c['p_score']} / send_ok={send_ok}",
            "duplicate_key":    c["dup_key"],
        })
        _append_sim_history({
            "simulated_at":    now,
            "target_agent":    rec.get("target_agent", ""),
            "improvement_type": rec.get("improvement_type", ""),
            "status":          "ranking_registered",
            "ranked_promoted": True,
            "ranked_reason":   f"execution_order={exe_order} / score={c['p_score']}",
            "duplicate_key":   c["dup_key"],
        })
        counts["ranked"] += 1

    return counts


def get_ranked_queue_stats() -> dict:
    records  = _load_jsonl(RANKED_QUEUE_PATH)
    pending  = [r for r in records if r.get("status") == "pending"]
    held     = [r for r in records if r.get("status") == "held"]
    high_p   = sum(1 for r in records if r.get("priority") == "HIGH")
    med_p    = sum(1 for r in records if r.get("priority") == "MEDIUM")
    low_p    = sum(1 for r in records if r.get("priority") == "LOW")
    top1     = next((r for r in sorted(pending, key=lambda x: x.get("execution_order",999)) if r.get("execution_order",0) > 0), {})
    latest   = records[-1] if records else {}
    return {
        "total":          len(records),
        "pending":        len(pending),
        "held":           len(held),
        "high_priority":  high_p,
        "medium_priority": med_p,
        "low_priority":   low_p,
        "top1_agent":     top1.get("target_agent",""),
        "top1_score":     top1.get("priority_score", 0.0),
        "latest_agent":   latest.get("target_agent",""),
        "latest_p_score": latest.get("priority_score", 0.0),
        "latest_order":   latest.get("execution_order", 0),
        "latest_status":  latest.get("status",""),
    }


PACKET_QUEUE_PATH   = BASE / "logs" / "ceo_execution_packet_queue.jsonl"
PACKET_HISTORY_PATH = BASE / "logs" / "ceo_execution_packet_history.jsonl"


def _is_packet_duplicate(dup_key: str) -> bool:
    for r in _load_jsonl(PACKET_QUEUE_PATH):
        if r.get("duplicate_key") == dup_key and r.get("packet_status") in ("pending", "archived"):
            return True
    return False


def promote_to_execution_packet() -> dict:
    """
    ceo_execution_ranked_queue の status=pending かつ ceo_send_recommended=True かつ
    execution_order>0 のレコードを packet queue にコピーする。
    execution_order 昇順で処理。
    実行は一切行わない。
    """
    now_str = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S JST")
    ranked  = _load_jsonl(RANKED_QUEUE_PATH)

    candidates = sorted(
        [r for r in ranked
         if r.get("status") == "pending"
         and r.get("ceo_send_recommended") is True
         and (r.get("execution_order") or 0) > 0],
        key=lambda x: x.get("execution_order", 999),
    )

    promoted          = 0
    skipped_duplicate = 0

    PACKET_QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PACKET_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)

    for rec in candidates:
        dup_key = rec.get("duplicate_key", "")

        if _is_packet_duplicate(dup_key):
            skipped_duplicate += 1
            hist = {
                "packeted_at":  now_str,
                "duplicate_key": dup_key,
                "status":        "packet_duplicate",
                "reason":        "既にpacket queueに存在",
            }
            with PACKET_HISTORY_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps(hist, ensure_ascii=False) + "\n")
            continue

        packet = {
            "packeted_at":       now_str,
            "source_ranked_at":  rec.get("ranked_at", ""),
            "target_agent":      rec.get("target_agent", ""),
            "improvement_type":  rec.get("improvement_type", ""),
            "priority":          rec.get("priority", "LOW"),
            "priority_score":    rec.get("priority_score", 0.0),
            "execution_order":   rec.get("execution_order", 0),
            "proposed_change":   rec.get("proposed_change", ""),
            "estimated_scope":   rec.get("estimated_scope", "none"),
            "risk_level":        rec.get("risk_level", "low"),
            "packet_status":     "pending",
            "packet_from":       "ceo_execution_ranked_queue",
            "duplicate_key":     dup_key,
            "ceo_judgment":      "ミュウツーCEO実行前パケット化",
        }
        with PACKET_QUEUE_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(packet, ensure_ascii=False) + "\n")
        promoted += 1

    return {"promoted": promoted, "skipped_duplicate": skipped_duplicate}


def get_packet_queue_stats() -> dict:
    records = _load_jsonl(PACKET_QUEUE_PATH)
    pending = [r for r in records if r.get("packet_status") == "pending"]
    high_p  = sum(1 for r in pending if r.get("priority") == "HIGH")
    med_p   = sum(1 for r in pending if r.get("priority") == "MEDIUM")
    low_p   = sum(1 for r in pending if r.get("priority") == "LOW")
    top1    = next((r for r in sorted(pending, key=lambda x: x.get("execution_order", 999))
                    if r.get("execution_order", 0) > 0), {})
    latest  = records[-1] if records else {}
    return {
        "pending":     len(pending),
        "high":        high_p,
        "medium":      med_p,
        "low":         low_p,
        "top1_agent":  top1.get("target_agent", ""),
        "top1_score":  top1.get("priority_score", 0.0),
        "top1_order":  top1.get("execution_order", 0),
        "latest_agent": latest.get("target_agent", ""),
        "latest_type":  latest.get("improvement_type", ""),
        "latest_score": latest.get("priority_score", 0.0),
        "latest_order": latest.get("execution_order", 0),
        "latest_status": latest.get("packet_status", ""),
    }


DISPATCH_QUEUE_PATH   = BASE / "logs" / "ceo_execution_dispatch_request_queue.jsonl"
DISPATCH_HISTORY_PATH = BASE / "logs" / "ceo_execution_dispatch_request_history.jsonl"


def _is_dispatch_duplicate(dup_key: str) -> bool:
    for r in _load_jsonl(DISPATCH_QUEUE_PATH):
        if r.get("duplicate_key") == dup_key and r.get("dispatch_status") in ("pending", "archived"):
            return True
    return False


def promote_to_dispatch_request() -> dict:
    """
    ceo_execution_packet_queue の packet_status=pending かつ execution_order>0 の
    レコードを dispatch_request queue にコピーする。
    execution_order 昇順で処理。実行は一切行わない。
    """
    now_str = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S JST")
    packets = _load_jsonl(PACKET_QUEUE_PATH)

    candidates = sorted(
        [r for r in packets
         if r.get("packet_status") == "pending"
         and (r.get("execution_order") or 0) > 0],
        key=lambda x: x.get("execution_order", 999),
    )

    promoted          = 0
    skipped_duplicate = 0

    DISPATCH_QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    DISPATCH_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)

    for rec in candidates:
        dup_key = rec.get("duplicate_key", "")

        if _is_dispatch_duplicate(dup_key):
            skipped_duplicate += 1
            hist = {
                "requested_at":  now_str,
                "duplicate_key": dup_key,
                "status":        "dispatch_duplicate",
                "reason":        "既にdispatch_request queueに存在",
            }
            with DISPATCH_HISTORY_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps(hist, ensure_ascii=False) + "\n")
            continue

        dispatch = {
            "requested_at":      now_str,
            "source_packeted_at": rec.get("packeted_at", ""),
            "target_agent":      rec.get("target_agent", ""),
            "improvement_type":  rec.get("improvement_type", ""),
            "priority":          rec.get("priority", "LOW"),
            "priority_score":    rec.get("priority_score", 0.0),
            "execution_order":   rec.get("execution_order", 0),
            "proposed_change":   rec.get("proposed_change", ""),
            "estimated_scope":   rec.get("estimated_scope", "none"),
            "risk_level":        rec.get("risk_level", "low"),
            "dispatch_status":   "pending",
            "dispatch_from":     "ceo_execution_packet_queue",
            "duplicate_key":     dup_key,
            "dispatch_ready":    True,
            "execution_blocked": True,
            "write_scope":       "none",
            "ceo_judgment":      "ミュウツーCEO実行要求パケット",
        }
        with DISPATCH_QUEUE_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(dispatch, ensure_ascii=False) + "\n")
        promoted += 1

    return {"promoted": promoted, "skipped_duplicate": skipped_duplicate}


def get_dispatch_queue_stats() -> dict:
    records = _load_jsonl(DISPATCH_QUEUE_PATH)
    pending = [r for r in records if r.get("dispatch_status") == "pending"]
    high_p  = sum(1 for r in pending if r.get("priority") == "HIGH")
    med_p   = sum(1 for r in pending if r.get("priority") == "MEDIUM")
    low_p   = sum(1 for r in pending if r.get("priority") == "LOW")
    top1    = next((r for r in sorted(pending, key=lambda x: x.get("execution_order", 999))
                    if r.get("execution_order", 0) > 0), {})
    latest  = records[-1] if records else {}
    return {
        "pending":      len(pending),
        "high":         high_p,
        "medium":       med_p,
        "low":          low_p,
        "top1_agent":   top1.get("target_agent", ""),
        "top1_score":   top1.get("priority_score", 0.0),
        "top1_order":   top1.get("execution_order", 0),
        "latest_agent": latest.get("target_agent", ""),
        "latest_type":  latest.get("improvement_type", ""),
        "latest_score": latest.get("priority_score", 0.0),
        "latest_order": latest.get("execution_order", 0),
        "latest_status": latest.get("dispatch_status", ""),
    }


# ─────────────────────────────────────────────────────────────
# フェーズ1: dispatch_request → executor_stub
# ─────────────────────────────────────────────────────────────

STUB_QUEUE_PATH   = BASE / "logs" / "ceo_execution_executor_stub_queue.jsonl"
STUB_HISTORY_PATH = BASE / "logs" / "ceo_execution_executor_stub_history.jsonl"

# 改善タイプ別 target_logs/target_files/expected_effect 決定論マップ
_STUB_META = {
    "prompt_fix": {
        "target_logs":  ["logs/pipeline.jsonl", "logs/pipeline_steps.jsonl"],
        "target_files": ["config/agent_directives.json"],
        "expected_effect": "出力品質改善により成功率回復が見込まれる",
    },
    "timeout_fix": {
        "target_logs":  ["logs/pipeline.jsonl", "logs/watchdog_alerts.jsonl"],
        "target_files": ["config/agent_directives.json"],
        "expected_effect": "空出力・停止頻度の減少が見込まれる",
    },
    "monitor_continue": {
        "target_logs":  ["dashboard_summary.json", "agent_metrics.json"],
        "target_files": [],
        "expected_effect": "追加変更なしで継続監視する",
    },
}
_STUB_META_DEFAULT = {
    "target_logs":  ["logs/pipeline.jsonl"],
    "target_files": [],
    "expected_effect": "影響範囲不明",
}


def _is_stub_duplicate(dup_key: str) -> bool:
    for r in _load_jsonl(STUB_QUEUE_PATH):
        if r.get("duplicate_key") == dup_key and r.get("stub_status") in ("pending", "archived"):
            return True
    return False


def promote_to_executor_stub() -> dict:
    """
    dispatch_request queue の dispatch_status=pending かつ dispatch_ready=True かつ
    execution_order>0 のレコードを executor_stub queue にコピー。実行しない。
    """
    now_str    = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S JST")
    dispatches = _load_jsonl(DISPATCH_QUEUE_PATH)

    candidates = sorted(
        [r for r in dispatches
         if r.get("dispatch_status") == "pending"
         and r.get("dispatch_ready") is True
         and (r.get("execution_order") or 0) > 0],
        key=lambda x: x.get("execution_order", 999),
    )

    promoted          = 0
    skipped_duplicate = 0

    STUB_QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STUB_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)

    for rec in candidates:
        dup_key = rec.get("duplicate_key", "")
        if _is_stub_duplicate(dup_key):
            skipped_duplicate += 1
            with STUB_HISTORY_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "stubbed_at":    now_str,
                    "duplicate_key": dup_key,
                    "status":        "stub_duplicate",
                    "reason":        "既にexecutor_stub queueに存在",
                }, ensure_ascii=False) + "\n")
            continue

        itype = rec.get("improvement_type", "")
        meta  = _STUB_META.get(itype, _STUB_META_DEFAULT)

        stub = {
            "stubbed_at":          now_str,
            "source_requested_at": rec.get("requested_at", ""),
            "target_agent":        rec.get("target_agent", ""),
            "improvement_type":    itype,
            "priority":            rec.get("priority", "LOW"),
            "priority_score":      rec.get("priority_score", 0.0),
            "execution_order":     rec.get("execution_order", 0),
            "proposed_change":     rec.get("proposed_change", ""),
            "estimated_scope":     rec.get("estimated_scope", "none"),
            "risk_level":          rec.get("risk_level", "low"),
            "target_logs":         meta["target_logs"],
            "target_files":        meta["target_files"],
            "expected_effect":     meta["expected_effect"],
            "stub_status":         "pending",
            "stub_from":           "ceo_execution_dispatch_request_queue",
            "duplicate_key":       dup_key,
            "dispatch_ready":      True,
            "execution_blocked":   True,
            "write_scope":         "none",
            "dry_run_only":        True,
            "ceo_judgment":        "ミュウツーCEO実行前スタブ化",
        }
        with STUB_QUEUE_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(stub, ensure_ascii=False) + "\n")
        promoted += 1

    return {"promoted": promoted, "skipped_duplicate": skipped_duplicate}


def get_stub_queue_stats() -> dict:
    records = _load_jsonl(STUB_QUEUE_PATH)
    pending = [r for r in records if r.get("stub_status") == "pending"]
    high_p  = sum(1 for r in pending if r.get("priority") == "HIGH")
    med_p   = sum(1 for r in pending if r.get("priority") == "MEDIUM")
    low_p   = sum(1 for r in pending if r.get("priority") == "LOW")
    top1    = next((r for r in sorted(pending, key=lambda x: x.get("execution_order", 999))
                    if r.get("execution_order", 0) > 0), {})
    latest  = records[-1] if records else {}
    return {
        "pending":       len(pending),
        "high":          high_p,
        "medium":        med_p,
        "low":           low_p,
        "top1_agent":    top1.get("target_agent", ""),
        "top1_score":    top1.get("priority_score", 0.0),
        "top1_order":    top1.get("execution_order", 0),
        "latest_agent":  latest.get("target_agent", ""),
        "latest_type":   latest.get("improvement_type", ""),
        "latest_score":  latest.get("priority_score", 0.0),
        "latest_order":  latest.get("execution_order", 0),
        "latest_status": latest.get("stub_status", ""),
    }


# ─────────────────────────────────────────────────────────────
# フェーズ2: executor_stub → dry_run_result
# ─────────────────────────────────────────────────────────────

DRY_RUN_QUEUE_PATH   = BASE / "logs" / "ceo_execution_dry_run_result_queue.jsonl"
DRY_RUN_HISTORY_PATH = BASE / "logs" / "ceo_execution_dry_run_result_history.jsonl"

# 改善タイプ別 ドライラン予測決定論マップ
_DRY_RUN_META = {
    "prompt_fix": {
        "predicted_changes": ["プロンプト定義の調整候補を適用", "出力フォーマット安定化"],
        "predicted_risk":    "medium",
        "benefit_delta":     0.0,   # priority_score そのまま
    },
    "timeout_fix": {
        "predicted_changes": ["タイムアウト閾値または再試行設定の見直し候補", "空出力回避"],
        "predicted_risk":    "medium",
        "benefit_delta":     0.02,
    },
    "monitor_continue": {
        "predicted_changes": ["設定変更なし", "監視継続"],
        "predicted_risk":    "low",
        "benefit_fixed":     0.25,
    },
}
_DRY_RUN_META_DEFAULT = {
    "predicted_changes": ["影響範囲確認が必要"],
    "predicted_risk":    "high",
    "benefit_fixed":     0.15,
}


def _is_dry_run_duplicate(dup_key: str) -> bool:
    for r in _load_jsonl(DRY_RUN_QUEUE_PATH):
        if r.get("duplicate_key") == dup_key and r.get("dry_run_status") in ("pending", "archived"):
            return True
    return False


def simulate_executor_stub() -> dict:
    """
    executor_stub queue の stub_status=pending かつ dry_run_only=True かつ
    execution_blocked=True のレコードを dry_run_result queue に生成。実行しない。
    """
    now_str = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S JST")
    stubs   = _load_jsonl(STUB_QUEUE_PATH)

    candidates = [r for r in stubs
                  if r.get("stub_status") == "pending"
                  and r.get("dry_run_only") is True
                  and r.get("execution_blocked") is True]

    simulated         = 0
    skipped_duplicate = 0

    DRY_RUN_QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    DRY_RUN_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)

    for rec in candidates:
        dup_key = rec.get("duplicate_key", "")
        if _is_dry_run_duplicate(dup_key):
            skipped_duplicate += 1
            with DRY_RUN_HISTORY_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "dry_run_at":    now_str,
                    "duplicate_key": dup_key,
                    "status":        "dry_run_duplicate",
                    "reason":        "既にdry_run_result queueに存在",
                }, ensure_ascii=False) + "\n")
            continue

        itype  = rec.get("improvement_type", "")
        meta   = _DRY_RUN_META.get(itype, _DRY_RUN_META_DEFAULT)
        p_score = rec.get("priority_score", 0.0)

        if "benefit_fixed" in meta:
            benefit = meta["benefit_fixed"]
        else:
            benefit = min(1.0, p_score + meta.get("benefit_delta", 0.0))

        dry_run = {
            "dry_run_at":             now_str,
            "source_stubbed_at":      rec.get("stubbed_at", ""),
            "target_agent":           rec.get("target_agent", ""),
            "improvement_type":       itype,
            "priority":               rec.get("priority", "LOW"),
            "priority_score":         p_score,
            "execution_order":        rec.get("execution_order", 0),
            "target_logs":            rec.get("target_logs", []),
            "target_files":           rec.get("target_files", []),
            "expected_effect":        rec.get("expected_effect", ""),
            "predicted_changes":      meta["predicted_changes"],
            "predicted_risk":         meta["predicted_risk"],
            "predicted_benefit_score": round(benefit, 3),
            "dry_run_status":         "pending",
            "dry_run_from":           "ceo_execution_executor_stub_queue",
            "duplicate_key":          dup_key,
            "execution_blocked":      True,
            "write_scope":            "none",
            "dry_run_only":           True,
            "ceo_judgment":           "ミュウツーCEO実行前ドライラン",
        }
        with DRY_RUN_QUEUE_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(dry_run, ensure_ascii=False) + "\n")
        simulated += 1

    return {"simulated": simulated, "skipped_duplicate": skipped_duplicate}


def get_dry_run_queue_stats() -> dict:
    records  = _load_jsonl(DRY_RUN_QUEUE_PATH)
    pending  = [r for r in records if r.get("dry_run_status") == "pending"]
    high_r   = sum(1 for r in pending if r.get("predicted_risk") == "high")
    med_r    = sum(1 for r in pending if r.get("predicted_risk") == "medium")
    low_r    = sum(1 for r in pending if r.get("predicted_risk") == "low")
    top1     = next((r for r in sorted(pending, key=lambda x: x.get("execution_order", 999))
                     if r.get("execution_order", 0) > 0), {})
    latest   = records[-1] if records else {}
    return {
        "pending":        len(pending),
        "high_risk":      high_r,
        "medium_risk":    med_r,
        "low_risk":       low_r,
        "top1_agent":     top1.get("target_agent", ""),
        "top1_benefit":   top1.get("predicted_benefit_score", 0.0),
        "top1_order":     top1.get("execution_order", 0),
        "latest_agent":   latest.get("target_agent", ""),
        "latest_type":    latest.get("improvement_type", ""),
        "latest_benefit": latest.get("predicted_benefit_score", 0.0),
        "latest_order":   latest.get("execution_order", 0),
        "latest_status":  latest.get("dry_run_status", ""),
    }


# ─────────────────────────────────────────────────────────────
# フェーズ3: dry_run_result → execution_candidate
# ─────────────────────────────────────────────────────────────

CANDIDATE_QUEUE_PATH   = BASE / "logs" / "ceo_execution_candidate_queue.jsonl"
CANDIDATE_HISTORY_PATH = BASE / "logs" / "ceo_execution_candidate_history.jsonl"


def _is_candidate_duplicate(dup_key: str) -> bool:
    for r in _load_jsonl(CANDIDATE_QUEUE_PATH):
        if r.get("duplicate_key") == dup_key and r.get("candidate_status") in ("pending", "archived"):
            return True
    return False


def promote_to_execution_candidate() -> dict:
    """
    dry_run_result queue の pending かつ execution_blocked=True かつ write_scope=none かつ
    dry_run_only=True かつ predicted_risk in (low,medium) かつ predicted_benefit_score>=0.60
    を execution_candidate queue にコピー。実行しない。
    """
    now_str   = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S JST")
    dry_runs  = _load_jsonl(DRY_RUN_QUEUE_PATH)

    all_eligible = [r for r in dry_runs
                    if r.get("dry_run_status") == "pending"
                    and r.get("execution_blocked") is True
                    and r.get("write_scope") == "none"
                    and r.get("dry_run_only") is True]

    promoted          = 0
    held              = 0
    skipped_duplicate = 0

    CANDIDATE_QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CANDIDATE_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)

    candidates = sorted(all_eligible, key=lambda x: x.get("execution_order", 999))

    for rec in candidates:
        dup_key = rec.get("duplicate_key", "")
        risk    = rec.get("predicted_risk", "high")
        benefit = rec.get("predicted_benefit_score", 0.0)

        # 条件を満たさないものは held としてカウントのみ
        if risk not in ("low", "medium") or benefit < 0.60:
            held += 1
            continue

        if _is_candidate_duplicate(dup_key):
            skipped_duplicate += 1
            with CANDIDATE_HISTORY_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "candidate_at":  now_str,
                    "duplicate_key": dup_key,
                    "status":        "candidate_duplicate",
                    "reason":        "既にexecution_candidate queueに存在",
                }, ensure_ascii=False) + "\n")
            continue

        candidate = {
            "candidate_at":           now_str,
            "source_dry_run_at":      rec.get("dry_run_at", ""),
            "target_agent":           rec.get("target_agent", ""),
            "improvement_type":       rec.get("improvement_type", ""),
            "priority":               rec.get("priority", "LOW"),
            "priority_score":         rec.get("priority_score", 0.0),
            "execution_order":        rec.get("execution_order", 0),
            "target_logs":            rec.get("target_logs", []),
            "target_files":           rec.get("target_files", []),
            "expected_effect":        rec.get("expected_effect", ""),
            "predicted_changes":      rec.get("predicted_changes", []),
            "predicted_risk":         risk,
            "predicted_benefit_score": benefit,
            "candidate_status":       "pending",
            "candidate_from":         "ceo_execution_dry_run_result_queue",
            "duplicate_key":          dup_key,
            "execution_blocked":      True,
            "write_scope":            "none",
            "dry_run_only":           True,
            "candidate_ready":        True,
            "ceo_judgment":           "ミュウツーCEO最終実行候補",
        }
        with CANDIDATE_QUEUE_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(candidate, ensure_ascii=False) + "\n")
        promoted += 1

    return {"promoted": promoted, "held": held, "skipped_duplicate": skipped_duplicate}


def get_candidate_queue_stats() -> dict:
    records = _load_jsonl(CANDIDATE_QUEUE_PATH)
    pending = [r for r in records if r.get("candidate_status") == "pending"]
    high_p  = sum(1 for r in pending if r.get("priority") == "HIGH")
    med_p   = sum(1 for r in pending if r.get("priority") == "MEDIUM")
    low_p   = sum(1 for r in pending if r.get("priority") == "LOW")
    top1    = next((r for r in sorted(pending, key=lambda x: x.get("execution_order", 999))
                    if r.get("execution_order", 0) > 0), {})
    latest  = records[-1] if records else {}
    return {
        "pending":       len(pending),
        "high":          high_p,
        "medium":        med_p,
        "low":           low_p,
        "top1_agent":    top1.get("target_agent", ""),
        "top1_score":    top1.get("priority_score", 0.0),
        "top1_order":    top1.get("execution_order", 0),
        "latest_agent":  latest.get("target_agent", ""),
        "latest_type":   latest.get("improvement_type", ""),
        "latest_score":  latest.get("priority_score", 0.0),
        "latest_order":  latest.get("execution_order", 0),
        "latest_status": latest.get("candidate_status", ""),
    }


# ─────────────────────────────────────────────────────────────
# フェーズ4: execution_candidate → limited_execution_queue
# ─────────────────────────────────────────────────────────────

LIMITED_EXEC_QUEUE_PATH   = BASE / "logs" / "ceo_limited_execution_queue.jsonl"
LIMITED_EXEC_HISTORY_PATH = BASE / "logs" / "ceo_limited_execution_history.jsonl"

_ALLOWED_TARGET_FILES = {"config/agent_directives.json"}
_FORBIDDEN_TARGETS    = {"wordpress", "wp_api", "posts", "articles", "logs", "pipeline_core"}


def _is_limited_duplicate(dup_key: str) -> bool:
    for r in _load_jsonl(LIMITED_EXEC_QUEUE_PATH):
        if r.get("duplicate_key") == dup_key and r.get("limited_status") in ("pending", "archived"):
            return True
    return False


def _target_files_allowed(target_files: list) -> bool:
    """target_files が空 or 許可対象のみなら True。"""
    if not target_files:
        return True
    return all(tf in _ALLOWED_TARGET_FILES for tf in target_files)


def promote_to_limited_execution() -> dict:
    """
    execution_candidate queue の pending かつ SAFE 条件を満たすものだけを
    limited_execution_queue にコピー。実行はしない。
    対象: prompt_fix / predicted_risk low|medium / benefit>=0.60 / 許可ファイルのみ
    """
    now_str    = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S JST")
    candidates = _load_jsonl(CANDIDATE_QUEUE_PATH)

    eligible = [r for r in candidates
                if r.get("candidate_status") == "pending"
                and r.get("candidate_ready") is True
                and r.get("execution_blocked") is True
                and r.get("write_scope") == "none"
                and r.get("improvement_type") == "prompt_fix"
                and r.get("target_agent", "") != ""]

    promoted          = 0
    held              = 0
    skipped_duplicate = 0

    LIMITED_EXEC_QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    LIMITED_EXEC_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)

    for rec in sorted(eligible, key=lambda x: x.get("execution_order", 999)):
        risk    = rec.get("predicted_risk", "high")
        benefit = rec.get("predicted_benefit_score", 0.0)
        tf      = rec.get("target_files", [])
        dup_key = rec.get("duplicate_key", "")

        if risk not in ("low", "medium") or benefit < 0.60 or not _target_files_allowed(tf):
            held += 1
            continue

        if _is_limited_duplicate(dup_key):
            skipped_duplicate += 1
            with LIMITED_EXEC_HISTORY_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "limited_at":   now_str,
                    "duplicate_key": dup_key,
                    "status":        "limited_duplicate",
                    "reason":        "既にlimited_execution_queueに存在",
                }, ensure_ascii=False) + "\n")
            continue

        allowed_tf = list(_ALLOWED_TARGET_FILES) if not tf else [t for t in tf if t in _ALLOWED_TARGET_FILES]
        limited = {
            "limited_at":             now_str,
            "source_candidate_at":    rec.get("candidate_at", ""),
            "target_agent":           rec.get("target_agent", ""),
            "improvement_type":       "prompt_fix",
            "priority":               rec.get("priority", "LOW"),
            "priority_score":         rec.get("priority_score", 0.0),
            "execution_order":        rec.get("execution_order", 0),
            "target_logs":            rec.get("target_logs", []),
            "target_files":           allowed_tf if allowed_tf else ["config/agent_directives.json"],
            "expected_effect":        rec.get("expected_effect", ""),
            "predicted_changes":      rec.get("predicted_changes", []),
            "predicted_risk":         risk,
            "predicted_benefit_score": benefit,
            "limited_status":         "pending",
            "limited_from":           "ceo_execution_candidate_queue",
            "duplicate_key":          dup_key,
            "execution_mode":         "limited_config_only",
            "execution_allowed":      False,
            "execution_blocked":      True,
            "write_scope":            "config_only",
            "allowed_targets":        ["config/agent_directives.json"],
            "forbidden_targets":      sorted(_FORBIDDEN_TARGETS),
            "ceo_judgment":           "ミュウツーCEO限定実行候補",
        }
        with LIMITED_EXEC_QUEUE_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(limited, ensure_ascii=False) + "\n")
        promoted += 1

    return {"promoted": promoted, "held": held, "skipped_duplicate": skipped_duplicate}


def get_limited_execution_stats() -> dict:
    records = _load_jsonl(LIMITED_EXEC_QUEUE_PATH)
    pending = [r for r in records if r.get("limited_status") == "pending"]
    high_p  = sum(1 for r in pending if r.get("priority") == "HIGH")
    med_p   = sum(1 for r in pending if r.get("priority") == "MEDIUM")
    low_p   = sum(1 for r in pending if r.get("priority") == "LOW")
    top1    = next((r for r in sorted(pending, key=lambda x: x.get("execution_order", 999))
                    if r.get("execution_order", 0) > 0), {})
    latest  = records[-1] if records else {}
    return {
        "pending":       len(pending),
        "high":          high_p,
        "medium":        med_p,
        "low":           low_p,
        "top1_agent":    top1.get("target_agent", ""),
        "top1_score":    top1.get("priority_score", 0.0),
        "top1_order":    top1.get("execution_order", 0),
        "latest_agent":  latest.get("target_agent", ""),
        "latest_type":   latest.get("improvement_type", ""),
        "latest_score":  latest.get("priority_score", 0.0),
        "latest_order":  latest.get("execution_order", 0),
        "latest_status": latest.get("limited_status", ""),
    }


# ─────────────────────────────────────────────────────────────
# フェーズ5: limited_execution_queue → execution_guard_result
# ─────────────────────────────────────────────────────────────

GUARD_RESULT_QUEUE_PATH   = BASE / "logs" / "ceo_execution_guard_result_queue.jsonl"
GUARD_RESULT_HISTORY_PATH = BASE / "logs" / "ceo_execution_guard_result_history.jsonl"

_GUARD_REASON_ALLOWED      = "prompt_fix かつ config_only のため限定実行候補"
_GUARD_REASON_HIGH_RISK    = "predicted_risk が high のため blocked"
_GUARD_REASON_LOW_BENEFIT  = "predicted_benefit_score が閾値未満のため blocked"
_GUARD_REASON_BAD_FILES    = "target_files に許可外ファイルを含むため blocked"
_GUARD_REASON_EMPTY_AGENT  = "対象AIが空のため blocked"
_GUARD_REASON_WRONG_TYPE   = "改善タイプが prompt_fix 以外のため blocked"
_GUARD_REASON_BAD_SCOPE    = "write_scope が config_only 以外のため blocked"
_GUARD_REASON_FORBIDDEN    = "forbidden_targets に禁止対象を含むため blocked"


def _is_guard_duplicate(dup_key: str) -> bool:
    for r in _load_jsonl(GUARD_RESULT_QUEUE_PATH):
        if r.get("duplicate_key") == dup_key and r.get("guard_status") in ("allowed", "blocked", "pending"):
            return True
    return False


def _check_forbidden_in_files(target_files: list) -> bool:
    """target_files に forbidden ターゲットが含まれるか判定。"""
    joined = " ".join(target_files).lower()
    return any(fb in joined for fb in _FORBIDDEN_TARGETS)


def evaluate_execution_guard() -> dict:
    """
    limited_execution_queue の pending レコードを完全決定論で guard 判定。
    実行はしない。allowed / blocked を execution_guard_result_queue に書き出す。
    """
    now_str  = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S JST")
    limiteds = _load_jsonl(LIMITED_EXEC_QUEUE_PATH)

    pending_recs = [r for r in limiteds if r.get("limited_status") == "pending"]

    evaluated         = 0
    allowed_count     = 0
    blocked_count     = 0
    skipped_duplicate = 0

    GUARD_RESULT_QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    GUARD_RESULT_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)

    for rec in sorted(pending_recs, key=lambda x: x.get("execution_order", 999)):
        dup_key = rec.get("duplicate_key", "")

        if _is_guard_duplicate(dup_key):
            skipped_duplicate += 1
            with GUARD_RESULT_HISTORY_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "guarded_at":    now_str,
                    "duplicate_key": dup_key,
                    "status":        "guard_duplicate",
                    "reason":        "既にexecution_guard_result_queueに存在",
                }, ensure_ascii=False) + "\n")
            continue

        itype   = rec.get("improvement_type", "")
        risk    = rec.get("predicted_risk", "high")
        benefit = rec.get("predicted_benefit_score", 0.0)
        tf      = rec.get("target_files", [])
        agent   = rec.get("target_agent", "")
        scope   = rec.get("write_scope", "")
        forb    = rec.get("forbidden_targets", [])
        order   = rec.get("execution_order", 0)

        # guard 判定（完全決定論）
        guard_status = "allowed"
        guard_reason = _GUARD_REASON_ALLOWED

        if not agent:
            guard_status = "blocked"
            guard_reason = _GUARD_REASON_EMPTY_AGENT
        elif itype != "prompt_fix":
            guard_status = "blocked"
            guard_reason = _GUARD_REASON_WRONG_TYPE
        elif risk == "high":
            guard_status = "blocked"
            guard_reason = _GUARD_REASON_HIGH_RISK
        elif benefit < 0.60:
            guard_status = "blocked"
            guard_reason = _GUARD_REASON_LOW_BENEFIT
        elif not _target_files_allowed(tf):
            guard_status = "blocked"
            guard_reason = _GUARD_REASON_BAD_FILES
        elif scope != "config_only":
            guard_status = "blocked"
            guard_reason = _GUARD_REASON_BAD_SCOPE
        elif _check_forbidden_in_files(tf):
            guard_status = "blocked"
            guard_reason = _GUARD_REASON_BAD_FILES
        elif order <= 0:
            guard_status = "blocked"
            guard_reason = "execution_order が 0 以下のため blocked"

        execution_allowed = (guard_status == "allowed")

        guard_rec = {
            "guarded_at":                now_str,
            "source_limited_at":         rec.get("limited_at", ""),
            "target_agent":              agent,
            "improvement_type":          itype,
            "priority":                  rec.get("priority", "LOW"),
            "priority_score":            rec.get("priority_score", 0.0),
            "execution_order":           order,
            "target_logs":               rec.get("target_logs", []),
            "target_files":              tf,
            "predicted_risk":            risk,
            "predicted_benefit_score":   benefit,
            "guard_status":              guard_status,
            "guard_reason":              guard_reason,
            "guard_from":                "ceo_limited_execution_queue",
            "duplicate_key":             dup_key,
            "execution_mode":            rec.get("execution_mode", "limited_config_only"),
            "execution_allowed":         execution_allowed,
            "execution_blocked":         not execution_allowed,
            "write_scope":               scope,
            "candidate_for_real_execution": execution_allowed,
            "ceo_judgment":              "ミュウツーCEO実行ガード判定",
        }
        with GUARD_RESULT_QUEUE_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(guard_rec, ensure_ascii=False) + "\n")

        evaluated += 1
        if execution_allowed:
            allowed_count += 1
        else:
            blocked_count += 1

    return {
        "evaluated":         evaluated,
        "allowed":           allowed_count,
        "blocked":           blocked_count,
        "skipped_duplicate": skipped_duplicate,
    }


def get_guard_result_stats() -> dict:
    records  = _load_jsonl(GUARD_RESULT_QUEUE_PATH)
    allowed  = [r for r in records if r.get("guard_status") == "allowed"]
    blocked  = [r for r in records if r.get("guard_status") == "blocked"]
    top1     = next((r for r in sorted(allowed, key=lambda x: x.get("execution_order", 999))
                     if r.get("execution_order", 0) > 0), {})
    latest   = records[-1] if records else {}
    return {
        "allowed":      len(allowed),
        "blocked":      len(blocked),
        "top1_agent":   top1.get("target_agent", ""),
        "top1_score":   top1.get("priority_score", 0.0),
        "top1_order":   top1.get("execution_order", 0),
        "latest_agent":  latest.get("target_agent", ""),
        "latest_status": latest.get("guard_status", ""),
        "latest_score":  latest.get("priority_score", 0.0),
        "latest_order":  latest.get("execution_order", 0),
    }


# ─────────────────────────────────────────────────────────────
# フェーズ6: execution_guard_result(allowed) → config_patch_plan
# ─────────────────────────────────────────────────────────────

PATCH_PLAN_QUEUE_PATH   = BASE / "logs" / "ceo_config_patch_plan_queue.jsonl"
PATCH_PLAN_HISTORY_PATH = BASE / "logs" / "ceo_config_patch_plan_history.jsonl"
CONFIG_TARGET_PATH      = BASE / "config" / "agent_directives.json"

# カタカナ名 → config agent_directives キー マップ
_AGENT_KEY_MAP: dict = {
    "バタフリー":           "butterfree",
    "X投稿B":              "x_post_b",
    "X投稿":               "x_post",
    "サーナイト":           "gardevoir_hook_critic",
    "カイリュー":           "kairyu",
    "アルセウス":           "arceus",
    "WP投稿":              "wp_poster",
    "デオキシス":           "deoxys",
    "メタモン":             "metamon",
    "イーブイ":             "eevee",
    "ジラーチ":             "jirachi",
    "ミュウツー":           "mewtwo",
    "ラプラス":             "lapras",
    "ミミッキュ":           "mimikyu",
    "ソーナンス":           "wobbuffet",
    "フシギバナ":           "venusaur",
    "フーディン":           "alakazam",
    "ゲンガー":             "gengar",
    "ペルシアン":           "persian",
    "サンダー":             "zapdos",
    "ポリゴン":             "porygon",
    "ポリゴンZ":            "porygon_z",
    "ルギア":               "lugia",
    "ニャース":             "meowth",
    "フリーザー":           "articuno",
    "コスメライター":       "beautywriter",
    "カビゴン":             "snorlax",
    "ポップアップライター": "popupwriter",
}

# patch_path の対象構造: config/agent_directives.json の agent_directives.<key>.action
_CONFIG_DIRECTIVE_FIELD = "action"
_MAX_AFTER_LEN = 500


def _normalize_agent_key(target_agent: str) -> str | None:
    """カタカナ名 → agent_directives キーに変換。不明なら None。"""
    return _AGENT_KEY_MAP.get(target_agent)


def _load_config_directives() -> dict:
    """config/agent_directives.json を読む。存在しない場合は空構造を返す。"""
    if not CONFIG_TARGET_PATH.exists():
        return {"agent_directives": {}}
    try:
        raw = json.loads(CONFIG_TARGET_PATH.read_text(encoding="utf-8"))
        if "agent_directives" not in raw:
            raw["agent_directives"] = {}
        return raw
    except Exception:
        return {"agent_directives": {}}


def _build_after_value(proposed_change: str, existing_action: str) -> str:
    """
    proposed_change から after_value を生成する。
    - 既存の action 文字列を参照し、proposed_change を末尾付記した新文字列を生成
    - 空文字禁止、500字上限、改行を \\n に正規化
    """
    base = proposed_change.strip().replace("\r\n", "\n").replace("\r", "\n")
    if not base:
        base = existing_action.strip() if existing_action else "（prompt_fix 適用済み）"
    if len(base) > _MAX_AFTER_LEN:
        base = base[:_MAX_AFTER_LEN]
    return base


def _is_patch_plan_duplicate(dup_key: str) -> bool:
    for r in _load_jsonl(PATCH_PLAN_QUEUE_PATH):
        if r.get("duplicate_key") == dup_key and r.get("plan_status") in ("pending", "applied", "archived"):
            return True
    return False


def promote_to_config_patch_plan() -> dict:
    """
    execution_guard_result の allowed 候補から config_patch_plan を生成。
    config/agent_directives.json を読んで before/after/diff_preview を確定する。
    まだ config への書き込みはしない。
    """
    now_str  = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S JST")
    guards   = _load_jsonl(GUARD_RESULT_QUEUE_PATH)

    allowed = [r for r in guards
               if r.get("guard_status") == "allowed"
               and r.get("candidate_for_real_execution") is True
               and r.get("improvement_type") == "prompt_fix"
               and r.get("execution_allowed") is True
               and r.get("write_scope") == "config_only"
               and r.get("target_agent", "") != ""]

    promoted          = 0
    held              = 0
    skipped_duplicate = 0

    PATCH_PLAN_QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PATCH_PLAN_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)

    config_data = _load_config_directives()
    ad          = config_data.get("agent_directives", {})

    for rec in sorted(allowed, key=lambda x: x.get("execution_order", 999)):
        target_agent = rec.get("target_agent", "")
        agent_key    = _normalize_agent_key(target_agent)
        dup_key_src  = rec.get("duplicate_key", "")

        if not agent_key:
            held += 1
            with PATCH_PLAN_HISTORY_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "planned_at":   now_str,
                    "target_agent": target_agent,
                    "status":       "held",
                    "reason":       f"agent_key 不明: '{target_agent}'",
                }, ensure_ascii=False) + "\n")
            continue

        # proposed_change は duplicate_key の2フィールド目以降から復元
        parts = dup_key_src.split("|", 2)
        proposed_change = parts[2] if len(parts) == 3 else ""

        # before_value 取得
        existing_entry  = ad.get(agent_key, {})
        if isinstance(existing_entry, dict):
            before_value = existing_entry.get(_CONFIG_DIRECTIVE_FIELD, "")
        elif isinstance(existing_entry, str):
            before_value = existing_entry
        else:
            before_value = ""

        # after_value 生成
        after_value = _build_after_value(proposed_change, before_value)
        if not after_value:
            held += 1
            with PATCH_PLAN_HISTORY_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "planned_at":   now_str,
                    "target_agent": target_agent,
                    "status":       "held",
                    "reason":       "after_value 生成不可",
                }, ensure_ascii=False) + "\n")
            continue

        # diff_preview（先頭120字比較）
        bv120 = before_value[:120].replace("\n", "↵")
        av120 = after_value[:120].replace("\n", "↵")
        diff_preview = f"BEFORE: {bv120}\nAFTER:  {av120}"

        # duplicate_key for plan (target_agent|improvement_type|after_value)
        plan_dup_key = f"{target_agent}|prompt_fix|{after_value[:100]}"

        if _is_patch_plan_duplicate(plan_dup_key):
            skipped_duplicate += 1
            with PATCH_PLAN_HISTORY_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "planned_at":    now_str,
                    "duplicate_key": plan_dup_key,
                    "status":        "plan_duplicate",
                    "reason":        "既にconfig_patch_plan queueに存在",
                }, ensure_ascii=False) + "\n")
            continue

        patch_path = f"agent_directives.{agent_key}.{_CONFIG_DIRECTIVE_FIELD}"

        plan = {
            "planned_at":        now_str,
            "source_guarded_at": rec.get("guarded_at", ""),
            "target_agent":      target_agent,
            "improvement_type":  "prompt_fix",
            "priority":          rec.get("priority", "HIGH"),
            "priority_score":    rec.get("priority_score", 0.0),
            "execution_order":   rec.get("execution_order", 0),
            "duplicate_key":     plan_dup_key,
            "plan_status":       "pending",
            "plan_from":         "ceo_execution_guard_result_queue",
            "target_config":     "config/agent_directives.json",
            "patch_mode":        "upsert_agent_directive",
            "patch_path":        patch_path,
            "agent_key":         agent_key,
            "before_value":      before_value,
            "after_value":       after_value,
            "diff_preview":      diff_preview,
            "backup_required":   True,
            "apply_ready":       True,
            "execution_scope":   "single_config_single_key",
            "ceo_judgment":      "ミュウツーCEO設定変更計画",
        }
        with PATCH_PLAN_QUEUE_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(plan, ensure_ascii=False) + "\n")
        promoted += 1

    return {"promoted": promoted, "held": held, "skipped_duplicate": skipped_duplicate}


def get_patch_plan_stats() -> dict:
    records = _load_jsonl(PATCH_PLAN_QUEUE_PATH)
    pending = [r for r in records if r.get("plan_status") == "pending"]
    held    = [r for r in records if r.get("plan_status") == "held"]
    top1    = next((r for r in sorted(pending, key=lambda x: x.get("execution_order", 999))
                    if r.get("execution_order", 0) > 0), {})
    latest  = records[-1] if records else {}
    return {
        "pending":      len(pending),
        "held":         len(held),
        "top1_agent":   top1.get("target_agent", ""),
        "top1_score":   top1.get("priority_score", 0.0),
        "top1_path":    top1.get("patch_path", ""),
        "latest_agent": latest.get("target_agent", ""),
        "latest_score": latest.get("priority_score", 0.0),
        "latest_status": latest.get("plan_status", ""),
    }


# ─────────────────────────────────────────────────────────────
# フェーズ7: config_patch_plan → config_apply_queue
# ─────────────────────────────────────────────────────────────

APPLY_QUEUE_PATH   = BASE / "logs" / "ceo_config_apply_queue.jsonl"
APPLY_HISTORY_PATH = BASE / "logs" / "ceo_config_apply_history.jsonl"


def _is_apply_queue_duplicate(dup_key: str) -> bool:
    for r in _load_jsonl(APPLY_QUEUE_PATH):
        if r.get("duplicate_key") == dup_key and r.get("apply_status") in ("pending", "applied", "archived"):
            return True
    return False


def promote_to_config_apply_queue() -> dict:
    """
    config_patch_plan queue の pending かつ apply_ready のものを apply_queue にコピー。
    まだ config への書き込みはしない。
    """
    now_str = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S JST")
    plans   = _load_jsonl(PATCH_PLAN_QUEUE_PATH)

    eligible = [r for r in plans
                if r.get("plan_status") == "pending"
                and r.get("apply_ready") is True
                and r.get("target_config") == "config/agent_directives.json"
                and r.get("patch_mode") == "upsert_agent_directive"]

    promoted          = 0
    skipped_duplicate = 0

    APPLY_QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    APPLY_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)

    for rec in sorted(eligible, key=lambda x: x.get("execution_order", 999)):
        dup_key = rec.get("duplicate_key", "")

        if _is_apply_queue_duplicate(dup_key):
            skipped_duplicate += 1
            with APPLY_HISTORY_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "queued_at":     now_str,
                    "duplicate_key": dup_key,
                    "status":        "apply_duplicate",
                    "reason":        "既にconfig_apply_queueに存在",
                }, ensure_ascii=False) + "\n")
            continue

        apply_rec = {
            "queued_at":        now_str,
            "source_planned_at": rec.get("planned_at", ""),
            "target_agent":     rec.get("target_agent", ""),
            "duplicate_key":    dup_key,
            "apply_status":     "pending",
            "apply_from":       "ceo_config_patch_plan_queue",
            "target_config":    "config/agent_directives.json",
            "patch_mode":       "upsert_agent_directive",
            "patch_path":       rec.get("patch_path", ""),
            "agent_key":        rec.get("agent_key", ""),
            "before_value":     rec.get("before_value", ""),
            "after_value":      rec.get("after_value", ""),
            "backup_required":  True,
            "execution_scope":  "single_config_single_key",
            "write_scope":      "config_only",
            "ceo_judgment":     "ミュウツーCEO設定変更適用待ち",
        }
        with APPLY_QUEUE_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(apply_rec, ensure_ascii=False) + "\n")
        promoted += 1

    return {"promoted": promoted, "skipped_duplicate": skipped_duplicate}


def get_apply_queue_stats() -> dict:
    records = _load_jsonl(APPLY_QUEUE_PATH)
    pending = [r for r in records if r.get("apply_status") == "pending"]
    top1    = next((r for r in pending), {})
    latest  = records[-1] if records else {}
    return {
        "pending":      len(pending),
        "top1_agent":   top1.get("target_agent", ""),
        "top1_path":    top1.get("patch_path", ""),
        "latest_agent": latest.get("target_agent", ""),
        "latest_status": latest.get("apply_status", ""),
    }


if __name__ == "__main__":
    import sys as _sys
    _sys.path.insert(0, str(BASE))
    # テスト: 直近 safe_history から enqueue
    safe_hist_path = BASE / "logs" / "ceo_safe_action_history.jsonl"
    entries = _load_jsonl(safe_hist_path)
    result  = enqueue_batch_from_safe_history(entries)
    print(f"queued={result['queued']} skipped_dup={result['skipped_dup']} skipped_na={result['skipped_na']}")
    stats = get_queue_stats()
    print(f"stats: {stats}")
