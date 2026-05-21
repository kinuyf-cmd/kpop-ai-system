#!/usr/bin/env python3
"""
ceo_auto_executor.py — 自動実行レイヤー v1.0
CEO: ミュウツー / オーナー: 人間（閲覧専用）

【役割】
  runtime_mode.json の設定に従って unlock / apply / rollback を自動実行する。
  agent_monitor とは分離した「実行専用レイヤー」。

【モード定義】
  MANUAL:    全て手動（自動実行0件）
  SAFE_AUTO: auto_unlock=true（HIGH以上のみ） / auto_apply=false / auto_rollback=true（rollback_dispatchのみ）
  FULL_AUTO: auto_unlock=true / auto_apply=true / auto_rollback=true

【安全制約（絶対）】
  - MANUALモードでは何も自動実行しない
  - SAFE_AUTOでも apply は絶対しない
  - FULL_AUTOでも rollback を最優先
  - config書き込みは1キーのみ（apply_execute_queue 内部制約）
  - backup_required=false なら絶対ブロック
  - invariant_violation pending があれば apply ブロック
  - hardening_alerts が ESCALATED なら apply ブロック
  - stale状態なら apply ブロック
  - append-only
  - LLM 判断なし
  - WordPress / Discord / pipeline 本体 変更禁止
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"
JST  = timezone(timedelta(hours=9))

# ── パス定義 ──────────────────────────────────────────────────────────
RUNTIME_MODE_PATH            = BASE / "config" / "runtime_mode.json"
UNLOCK_EXECUTE_QUEUE_PATH    = LOGS / "ceo_unlock_execute_queue.jsonl"
APPLY_EXECUTE_QUEUE_PATH     = LOGS / "ceo_apply_execute_queue.jsonl"
ROLLBACK_DISPATCH_QUEUE_PATH = LOGS / "ceo_rollback_dispatch_queue.jsonl"
INVARIANT_VIOLATION_QUEUE    = LOGS / "ceo_invariant_violation_queue.jsonl"
STALE_OP_QUEUE_PATH          = LOGS / "ceo_stale_operation_queue.jsonl"
HARDENING_ALERTS_PATH        = BASE / "dashboard_summary.json"

AUTO_EXEC_LOG_QUEUE   = LOGS / "ceo_auto_exec_log_queue.jsonl"
AUTO_EXEC_LOG_HISTORY = LOGS / "ceo_auto_exec_log_history.jsonl"
AUTO_ROLLBACK_RESULT  = LOGS / "ceo_auto_rollback_result_queue.jsonl"

# 自動apply 1回あたりの最大件数（安全上限）
MAX_AUTO_APPLY_PER_RUN = 1

# SAFE_AUTO で自動unlock可能な最低priority
SAFE_AUTO_MIN_PRIORITY = {"HIGH", "CRITICAL"}


def _now_jst() -> str:
    return datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S JST")


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    recs = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    recs.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return recs


def _append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


# ═══════════════════════════════════════════════════════════════════
# モード管理
# ═══════════════════════════════════════════════════════════════════

def load_runtime_mode() -> dict:
    """
    runtime_mode.json を読み込む。
    破損 / 不在時は MANUAL を返す（フェイルセーフ）。
    """
    if not RUNTIME_MODE_PATH.exists():
        return {"mode": "MANUAL", "auto_unlock": False, "auto_apply": False, "auto_rollback": False}
    try:
        raw = json.loads(RUNTIME_MODE_PATH.read_text(encoding="utf-8"))
        mode = raw.get("mode", "MANUAL")
        if mode not in ("MANUAL", "SAFE_AUTO", "FULL_AUTO"):
            mode = "MANUAL"
        # モードに応じて auto_* フラグを強制補正
        if mode == "MANUAL":
            raw["auto_unlock"] = False
            raw["auto_apply"]  = False
            raw["auto_rollback"] = False
        elif mode == "SAFE_AUTO":
            raw["auto_unlock"]   = True
            raw["auto_apply"]    = False   # SAFE_AUTO は apply 絶対禁止
            raw["auto_rollback"] = True
        elif mode == "FULL_AUTO":
            raw["auto_unlock"]   = True
            raw["auto_apply"]    = raw.get("auto_apply", True)
            raw["auto_rollback"] = True
        raw["mode"] = mode
        return raw
    except Exception:
        return {"mode": "MANUAL", "auto_unlock": False, "auto_apply": False, "auto_rollback": False}


def get_runtime_mode_stats() -> dict:
    m = load_runtime_mode()
    return {
        "runtime_mode":          m.get("mode", "MANUAL"),
        "auto_unlock_enabled":   m.get("auto_unlock", False),
        "auto_apply_enabled":    m.get("auto_apply", False),
        "auto_rollback_enabled": m.get("auto_rollback", False),
    }


# ═══════════════════════════════════════════════════════════════════
# 安全ガード
# ═══════════════════════════════════════════════════════════════════

def _has_invariant_violation() -> bool:
    pending = [r for r in _load_jsonl(INVARIANT_VIOLATION_QUEUE)
               if r.get("violation_status") == "pending"]
    return len(pending) > 0


def _is_hardening_escalated() -> bool:
    """dashboard_summary から hardening_is_escalated を読む。"""
    try:
        summary = json.loads(HARDENING_ALERTS_PATH.read_text(encoding="utf-8"))
        return bool(summary.get("hardening_is_escalated", False))
    except Exception:
        return False  # 読めなければ非エスカレーション扱い（apply判断は他ガードが補完）


def _is_stale(target_agent: str) -> bool:
    stale_agents = {r.get("target_agent", "")
                    for r in _load_jsonl(STALE_OP_QUEUE_PATH)
                    if r.get("status") == "pending"
                    and r.get("operation_type") in ("unlock_pending_stale", "apply_stale")}
    return target_agent in stale_agents


def _log_auto_exec(action_type: str, target_agent: str, dup_key: str,
                   status: str, reason: str, mode: str, cmd: str = "") -> None:
    rec = {
        "logged_at":     _now_jst(),
        "action_type":   action_type,
        "target_agent":  target_agent,
        "duplicate_key": dup_key,
        "exec_status":   status,
        "exec_reason":   reason,
        "runtime_mode":  mode,
        "command":       cmd,
        "execution_blocked": True,   # ログ自体は常にブロック状態記録
        "write_scope":   "queue_only",
        "ceo_judgment":  "ミュウツーCEO自動実行ログ",
    }
    _append_jsonl(AUTO_EXEC_LOG_QUEUE, rec)
    _append_jsonl(AUTO_EXEC_LOG_HISTORY, {
        "processed_at":  _now_jst(),
        "action_type":   action_type,
        "target_agent":  target_agent,
        "exec_status":   status,
        "runtime_mode":  mode,
        "ceo_judgment":  "ミュウツーCEO自動実行ログ",
    })


# ═══════════════════════════════════════════════════════════════════
# 自動 unlock
# ═══════════════════════════════════════════════════════════════════

def run_auto_unlock(mode_config: dict) -> dict:
    """
    unlock_execute_queue の pending を条件付きで自動 unlock する。
    """
    executed = 0
    skipped  = 0
    blocked  = 0

    if not mode_config.get("auto_unlock", False):
        return {"executed": 0, "skipped": 0, "blocked": 0, "reason": "auto_unlock disabled"}

    mode = mode_config.get("mode", "MANUAL")

    unlock_recs = [r for r in _load_jsonl(UNLOCK_EXECUTE_QUEUE_PATH)
                   if r.get("unlock_status") == "pending"
                   and r.get("actual_unlocked") is not True]

    # 既 unlock 済みの duplicate_key セット
    already_unlocked = {r.get("duplicate_key", "")
                        for r in _load_jsonl(UNLOCK_EXECUTE_QUEUE_PATH)
                        if r.get("unlock_status") == "unlocked"
                        and r.get("actual_unlocked") is True}

    for rec in unlock_recs:
        dup_key = rec.get("duplicate_key", "")
        ta      = rec.get("target_agent", "—")
        prio    = rec.get("priority", "LOW")

        if dup_key in already_unlocked:
            skipped += 1
            continue

        # SAFE_AUTO: HIGH以上のみ
        if mode == "SAFE_AUTO" and prio not in SAFE_AUTO_MIN_PRIORITY:
            _log_auto_exec("auto_unlock", ta, dup_key, "skipped",
                           f"SAFE_AUTO: priority={prio} (HIGH未満)", mode)
            skipped += 1
            continue

        # invariant violation があれば unlock もブロック
        if _has_invariant_violation():
            _log_auto_exec("auto_unlock", ta, dup_key, "blocked",
                           "invariant_violation pending あり", mode)
            blocked += 1
            continue

        # stale チェック
        if _is_stale(ta):
            _log_auto_exec("auto_unlock", ta, dup_key, "blocked",
                           f"{ta} が stale 状態", mode)
            blocked += 1
            continue

        # 実行
        try:
            from lib.ceo_unlock_executor import execute_unlock_candidate
            result = execute_unlock_candidate(dup_key)
            status = result.get("status", "unknown")
            already_unlocked.add(dup_key)
            _log_auto_exec("auto_unlock", ta, dup_key,
                           f"executed:{status}", result.get("reason", ""), mode,
                           cmd=f'python3 lib/ceo_unlock_executor.py unlock "{dup_key}"')
            if status == "unlocked":
                executed += 1
            else:
                skipped += 1
        except Exception as e:
            _log_auto_exec("auto_unlock", ta, dup_key, "error", str(e), mode)
            blocked += 1

    return {"executed": executed, "skipped": skipped, "blocked": blocked}


# ═══════════════════════════════════════════════════════════════════
# 自動 apply
# ═══════════════════════════════════════════════════════════════════

def run_auto_apply(mode_config: dict) -> dict:
    """
    apply_execute_queue の pending を条件付きで自動 apply する。
    SAFE_AUTO では絶対実行しない。
    FULL_AUTO でも全安全ガードを通過した場合のみ。
    """
    executed = 0
    skipped  = 0
    blocked  = 0

    mode = mode_config.get("mode", "MANUAL")

    # MANUAL / SAFE_AUTO は絶対ブロック
    if not mode_config.get("auto_apply", False) or mode in ("MANUAL", "SAFE_AUTO"):
        reason = "SAFE_AUTO: auto_apply 永久禁止" if mode == "SAFE_AUTO" else "auto_apply disabled"
        return {"executed": 0, "skipped": 0, "blocked": 0, "reason": reason}

    # FULL_AUTO 用ガード
    if _has_invariant_violation():
        return {"executed": 0, "skipped": 0, "blocked": 1,
                "reason": "invariant_violation pending あり — apply全件ブロック"}

    if _is_hardening_escalated():
        return {"executed": 0, "skipped": 0, "blocked": 1,
                "reason": "hardening ESCALATED — apply全件ブロック"}

    apply_recs = [r for r in _load_jsonl(APPLY_EXECUTE_QUEUE_PATH)
                  if r.get("apply_execute_status") == "pending"
                  and r.get("apply_execute_ready") is True]

    if not apply_recs:
        return {"executed": 0, "skipped": 0, "blocked": 0, "reason": "apply pending なし"}

    # rollback dispatch pending があればapplyを止める（rollback優先）
    rb_pending = [r for r in _load_jsonl(ROLLBACK_DISPATCH_QUEUE_PATH)
                  if r.get("router_status") == "pending"]
    if rb_pending:
        return {"executed": 0, "skipped": len(apply_recs), "blocked": 0,
                "reason": f"rollback_dispatch pending {len(rb_pending)}件 — apply停止中"}

    # 1回最大MAX_AUTO_APPLY_PER_RUN 件まで
    targets = apply_recs[:MAX_AUTO_APPLY_PER_RUN]

    for rec in targets:
        dup_key = rec.get("duplicate_key", "")
        ta      = rec.get("target_agent", "—")

        # backup_required チェック（絶対制約）
        if not rec.get("backup_required", False):
            _log_auto_exec("auto_apply", ta, dup_key, "blocked",
                           "backup_required=false — apply絶対ブロック", mode)
            blocked += 1
            continue

        # write_scope チェック
        if rec.get("write_scope") not in ("config_single_key", "none"):
            _log_auto_exec("auto_apply", ta, dup_key, "blocked",
                           f"write_scope={rec.get('write_scope')} 不正", mode)
            blocked += 1
            continue

        # after_value 空チェック
        if not (rec.get("after_value") or "").strip():
            _log_auto_exec("auto_apply", ta, dup_key, "blocked",
                           "after_value 空", mode)
            blocked += 1
            continue

        # stale チェック
        if _is_stale(ta):
            _log_auto_exec("auto_apply", ta, dup_key, "blocked",
                           f"{ta} が stale 状態", mode)
            blocked += 1
            continue

        # 実行
        try:
            from lib.ceo_unlock_executor import apply_execute_queue
            result = apply_execute_queue()
            _log_auto_exec("auto_apply", ta, dup_key,
                           f"executed:applied={result.get('applied',0)}",
                           f"applied={result.get('applied',0)} blocked={result.get('blocked',0)}",
                           mode,
                           cmd="python3 lib/ceo_unlock_executor.py apply")
            executed += result.get("applied", 0)
            skipped  += result.get("skipped_duplicate", 0)
            blocked  += result.get("blocked", 0)
        except Exception as e:
            _log_auto_exec("auto_apply", ta, dup_key, "error", str(e), mode)
            blocked += 1

    return {"executed": executed, "skipped": skipped, "blocked": blocked}


# ═══════════════════════════════════════════════════════════════════
# 自動 rollback
# ═══════════════════════════════════════════════════════════════════

def run_auto_rollback(mode_config: dict) -> dict:
    """
    rollback_dispatch_queue の pending を自動 rollback する。
    rollback は SAFE_AUTO でも実行可能（安全方向のため）。
    """
    executed = 0
    skipped  = 0
    blocked  = 0

    if not mode_config.get("auto_rollback", False):
        return {"executed": 0, "skipped": 0, "blocked": 0, "reason": "auto_rollback disabled"}

    mode = mode_config.get("mode", "MANUAL")

    rb_recs = [r for r in _load_jsonl(ROLLBACK_DISPATCH_QUEUE_PATH)
               if r.get("router_status") == "pending"]

    # 既実行済みセット
    existing_rb = {r.get("duplicate_key", "")
                   for r in _load_jsonl(AUTO_ROLLBACK_RESULT)
                   if r.get("rb_result_status") in ("executed", "failed")}

    for rec in rb_recs:
        dup_key = rec.get("duplicate_key", "")
        ta      = rec.get("target_agent", "—")
        agent_key = rec.get("agent_key", "")

        if dup_key in existing_rb:
            skipped += 1
            continue

        existing_rb.add(dup_key)

        # rollback 実行（ceo_config_executor.rollback_last_config_change）
        try:
            from lib.ceo_config_executor import rollback_last_config_change
            result = rollback_last_config_change(ta)
            rb_status = result.get("status", "unknown")
            reason    = result.get("reason", "")

            rb_result = {
                "rolled_back_at":  _now_jst(),
                "duplicate_key":   dup_key,
                "target_agent":    ta,
                "agent_key":       agent_key,
                "rb_result_status": "executed" if rb_status == "ok" else "failed",
                "rb_result_reason": reason,
                "backup_used":     result.get("backup_path", ""),
                "runtime_mode":    mode,
                "source_queue":    "ceo_rollback_dispatch_queue",
                "ceo_judgment":    "ミュウツーCEO自動rollback実行",
            }
            _append_jsonl(AUTO_ROLLBACK_RESULT, rb_result)
            _log_auto_exec("auto_rollback", ta, dup_key,
                           f"executed:{rb_status}", reason, mode,
                           cmd=f"python3 lib/ceo_config_executor.py rollback {ta}")

            if rb_status == "ok":
                executed += 1
            else:
                blocked += 1
        except Exception as e:
            _append_jsonl(AUTO_ROLLBACK_RESULT, {
                "rolled_back_at":   _now_jst(),
                "duplicate_key":    dup_key,
                "target_agent":     ta,
                "rb_result_status": "error",
                "rb_result_reason": str(e),
                "runtime_mode":     mode,
                "ceo_judgment":     "ミュウツーCEO自動rollback実行",
            })
            _log_auto_exec("auto_rollback", ta, dup_key, "error", str(e), mode)
            blocked += 1

    return {"executed": executed, "skipped": skipped, "blocked": blocked}


# ═══════════════════════════════════════════════════════════════════
# stats 関数
# ═══════════════════════════════════════════════════════════════════

def get_auto_exec_stats() -> dict:
    logs    = _load_jsonl(AUTO_EXEC_LOG_QUEUE)
    unlocks = [r for r in logs if r.get("action_type") == "auto_unlock"
               and "executed" in (r.get("exec_status") or "")]
    applies = [r for r in logs if r.get("action_type") == "auto_apply"
               and "executed" in (r.get("exec_status") or "")]
    rb_recs = _load_jsonl(AUTO_ROLLBACK_RESULT)
    rollbacks = [r for r in rb_recs if r.get("rb_result_status") == "executed"]
    latest_log = logs[-1] if logs else {}
    return {
        "auto_exec_unlock_count":   len(unlocks),
        "auto_exec_apply_count":    len(applies),
        "auto_exec_rollback_count": len(rollbacks),
        "auto_exec_log_total":      len(logs),
        "auto_exec_latest_action":  latest_log.get("action_type", "—"),
        "auto_exec_latest_agent":   latest_log.get("target_agent", "—"),
        "auto_exec_latest_status":  latest_log.get("exec_status", "—"),
    }


# ═══════════════════════════════════════════════════════════════════
# メイン実行サイクル
# ═══════════════════════════════════════════════════════════════════

def run_auto_cycle() -> dict:
    """
    runtime_mode に従って auto_rollback → auto_unlock → auto_apply の順で実行する。
    rollback が最優先（安全方向）。
    """
    mode_config = load_runtime_mode()
    mode        = mode_config.get("mode", "MANUAL")

    result = {
        "runtime_mode": mode,
        "rollback": {},
        "unlock":   {},
        "apply":    {},
    }

    if mode == "MANUAL":
        result["rollback"] = {"executed": 0, "reason": "MANUAL mode — 自動実行なし"}
        result["unlock"]   = {"executed": 0, "reason": "MANUAL mode — 自動実行なし"}
        result["apply"]    = {"executed": 0, "reason": "MANUAL mode — 自動実行なし"}
        return result

    # 1. rollback 最優先
    result["rollback"] = run_auto_rollback(mode_config)

    # rollback が実行された場合、unlock / apply は今サイクルスキップ（安全）
    rb_executed = result["rollback"].get("executed", 0)
    if rb_executed > 0:
        result["unlock"] = {"executed": 0, "skipped": 0,
                            "reason": f"rollback {rb_executed}件実行後 — unlock今サイクルスキップ"}
        result["apply"]  = {"executed": 0, "skipped": 0,
                            "reason": f"rollback {rb_executed}件実行後 — apply今サイクルスキップ"}
        return result

    # 2. unlock
    result["unlock"] = run_auto_unlock(mode_config)

    # 3. apply（FULL_AUTO のみ）
    result["apply"] = run_auto_apply(mode_config)

    return result


# ═══════════════════════════════════════════════════════════════════
# エントリポイント
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import json as _json

    result = run_auto_cycle()
    print(_json.dumps(result, ensure_ascii=False, indent=2))
    print("--- stats ---")
    print(_json.dumps(get_auto_exec_stats(), ensure_ascii=False, indent=2))
    print(_json.dumps(get_runtime_mode_stats(), ensure_ascii=False, indent=2))
