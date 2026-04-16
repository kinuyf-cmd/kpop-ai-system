#!/usr/bin/env python3
"""
ceo_apply_hardening.py — unlock/apply 保護層 v1.0
CEO: ミュウツー / オーナー: 人間（閲覧専用）

【役割】
  unlock/apply フローの事故防止保護層。
  - unlock 有効期限管理（30分）
  - apply 前最終整合チェック
  - post-apply 再ロック候補
  - rollback request queue
  - stale operation 検出

【制約】
  - config/agent_directives.json への書き込みは apply 成功時のみ
  - unlock/apply 自動連鎖禁止
  - rollback / post-apply lock は候補生成のみ（実行しない）
  - append-only
  - LLM 判断なし
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"
JST  = timezone(timedelta(hours=9))

UNLOCK_EXECUTE_QUEUE_PATH   = LOGS / "ceo_unlock_execute_queue.jsonl"
APPLY_EXECUTE_QUEUE_PATH    = LOGS / "ceo_apply_execute_queue.jsonl"
APPLY_EXECUTE_RESULT_PATH   = LOGS / "ceo_apply_execute_result_queue.jsonl"

UNLOCK_EXPIRY_QUEUE_PATH    = LOGS / "ceo_unlock_expiry_queue.jsonl"
UNLOCK_EXPIRY_HISTORY_PATH  = LOGS / "ceo_unlock_expiry_history.jsonl"
POST_APPLY_LOCK_QUEUE_PATH  = LOGS / "ceo_post_apply_lock_queue.jsonl"
POST_APPLY_LOCK_HISTORY_PATH= LOGS / "ceo_post_apply_lock_history.jsonl"
ROLLBACK_REQUEST_QUEUE_PATH = LOGS / "ceo_rollback_request_queue.jsonl"
ROLLBACK_REQUEST_HIST_PATH  = LOGS / "ceo_rollback_request_history.jsonl"
STALE_OP_QUEUE_PATH         = LOGS / "ceo_stale_operation_queue.jsonl"
STALE_OP_HISTORY_PATH       = LOGS / "ceo_stale_operation_history.jsonl"

UNLOCK_EXPIRY_MINUTES = 30  # unlock 有効期限（分）
STALE_UNLOCK_MINUTES  = 60  # unlock pending 放置検出閾値
STALE_APPLY_MINUTES   = 120 # apply pending 放置検出閾値
STALE_ROLLBACK_MINUTES= 60  # rollback pending 放置検出閾値


# ── ユーティリティ ────────────────────────────────────────────────────

def _now_jst() -> datetime:
    return datetime.now(JST)


def _now_jst_str() -> str:
    return _now_jst().strftime("%Y-%m-%d %H:%M:%S JST")


def _parse_jst(s: str) -> datetime | None:
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S JST", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(s.replace(" JST", ""), fmt.replace(" JST", ""))
            return dt.replace(tzinfo=JST)
        except ValueError:
            pass
    return None


def _minutes_since(ts_str: str) -> float:
    dt = _parse_jst(ts_str)
    if dt is None:
        return 0.0
    delta = _now_jst() - dt
    return delta.total_seconds() / 60.0


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


# ════════════════════════════════════════════════════════════════════
# 1. unlock 有効期限管理
# ════════════════════════════════════════════════════════════════════

def compute_unlock_expires_at(unlocked_at_str: str) -> str:
    """unlocked_at から unlock_expires_at（+30分）を計算して文字列で返す"""
    dt = _parse_jst(unlocked_at_str)
    if dt is None:
        dt = _now_jst()
    expires = dt + timedelta(minutes=UNLOCK_EXPIRY_MINUTES)
    return expires.strftime("%Y-%m-%d %H:%M:%S JST")


def is_unlock_expired(unlock_expires_at_str: str) -> bool:
    """現在時刻が unlock_expires_at を過ぎていれば True"""
    expires = _parse_jst(unlock_expires_at_str)
    if expires is None:
        return False
    return _now_jst() > expires


def remaining_unlock_minutes(unlock_expires_at_str: str) -> float:
    """残り有効時間（分）。負数なら期限切れ"""
    expires = _parse_jst(unlock_expires_at_str)
    if expires is None:
        return 0.0
    delta = expires - _now_jst()
    return delta.total_seconds() / 60.0


def scan_unlock_expiry() -> dict:
    """
    unlock_execute_queue の unlocked レコードのうち期限切れを検出し
    unlock_expiry_queue に記録する。
    """
    unlock_recs = _load_jsonl(UNLOCK_EXECUTE_QUEUE_PATH)
    existing_exp = _load_jsonl(UNLOCK_EXPIRY_QUEUE_PATH)
    existing_keys: set[str] = {
        r.get("duplicate_key", "")
        for r in existing_exp
        if r.get("expiry_status") in ("expired", "archived")
    }

    expired_count = 0
    for rec in unlock_recs:
        if rec.get("unlock_status") != "unlocked":
            continue
        dup_key     = rec.get("duplicate_key", "")
        expires_at  = rec.get("unlock_expires_at", "")
        if not expires_at:
            continue
        if not is_unlock_expired(expires_at):
            continue
        if dup_key in existing_keys:
            continue

        ta = rec.get("target_agent", "—")
        existing_keys.add(dup_key)
        exp_rec = {
            "detected_at":      _now_jst_str(),
            "target_agent":     ta,
            "duplicate_key":    dup_key,
            "unlocked_at":      rec.get("unlocked_at", ""),
            "unlock_expires_at": expires_at,
            "expiry_status":    "expired",
            "recommended_action": "unlock を再実行するか候補を見直す",
            "source_queue":     "ceo_unlock_execute_queue",
            "ceo_judgment":     "ミュウツーCEO unlock期限切れ",
        }
        _append_jsonl(UNLOCK_EXPIRY_QUEUE_PATH, exp_rec)
        _append_jsonl(UNLOCK_EXPIRY_HISTORY_PATH, {
            "processed_at":  _now_jst_str(),
            "target_agent":  ta,
            "duplicate_key": dup_key,
            "status":        "unlock_expired",
            "reason":        f"unlock_expires_at={expires_at} を過ぎた",
            "source_queue":  "ceo_unlock_execute_queue",
            "ceo_judgment":  "ミュウツーCEO unlock期限切れ",
        })
        expired_count += 1

    pending_total = sum(
        1 for r in _load_jsonl(UNLOCK_EXPIRY_QUEUE_PATH)
        if r.get("expiry_status") == "expired"
    )
    return {"expired": expired_count, "pending": pending_total}


# ════════════════════════════════════════════════════════════════════
# 2. apply 前最終整合チェック
# ════════════════════════════════════════════════════════════════════

def check_apply_preconditions(rec: dict) -> tuple[bool, str]:
    """
    apply 実行前の最終整合チェック。
    戻り値: (ok: bool, reason: str)
    """
    # unlock_status
    if rec.get("unlock_status") != "unlocked" and rec.get("apply_execute_status") == "pending":
        # apply_execute_queue のレコードは unlock_status を持たない場合がある
        # → source_unlocked_at が存在すれば OK とする
        pass

    # actual_unlocked は apply_execute_queue では直接持たないため
    # unlock_execute_queue との突合で確認する
    # ここでは apply_execute_queue レコードの必須フィールドを確認
    if rec.get("write_scope") != "config_single_key":
        return False, f"write_scope={rec.get('write_scope')} (config_single_key 以外)"
    if rec.get("target_config") != "config/agent_directives.json":
        return False, f"target_config={rec.get('target_config')} (不正)"
    ppath = (rec.get("patch_path") or "")
    if not ppath.startswith("agent_directives."):
        return False, f"patch_path={ppath} (agent_directives. で始まらない)"
    if not (rec.get("after_value") or "").strip():
        return False, "after_value が空"
    if not (rec.get("agent_key") or "").strip():
        return False, "agent_key が空"
    if rec.get("patch_mode") != "upsert_agent_directive":
        return False, f"patch_mode={rec.get('patch_mode')} (upsert_agent_directive 以外)"

    # unlock 有効期限チェック（unlock_execute_queue から逆引き）
    dup_key     = rec.get("duplicate_key", "")
    unlock_recs = _load_jsonl(UNLOCK_EXECUTE_QUEUE_PATH)
    unlock_rec  = None
    for ur in reversed(unlock_recs):
        if ur.get("duplicate_key") == dup_key and ur.get("unlock_status") == "unlocked":
            unlock_rec = ur
            break

    if unlock_rec is None:
        return False, f"unlock_execute_queue に対応する unlocked レコードが見つからない: {dup_key}"

    if unlock_rec.get("actual_unlocked") is not True:
        return False, "actual_unlocked が true でない"

    expires_at = unlock_rec.get("unlock_expires_at", "")
    if expires_at and is_unlock_expired(expires_at):
        return False, f"unlock 有効期限切れ: {expires_at}"

    return True, ""


# ════════════════════════════════════════════════════════════════════
# 3. post-apply 再ロック候補
# ════════════════════════════════════════════════════════════════════

def register_post_apply_lock(result_rec: dict) -> None:
    """
    apply 成功後に呼ぶ。post_apply_lock_queue に候補を1件 append する。
    実際の再ロックは実行しない。
    """
    dup_key = result_rec.get("duplicate_key", "")
    ta      = result_rec.get("target_agent", "—")

    existing = _load_jsonl(POST_APPLY_LOCK_QUEUE_PATH)
    if any(r.get("duplicate_key") == dup_key and r.get("status") == "pending"
           for r in existing):
        return  # 既に pending あり

    lock_rec = {
        "registered_at":               _now_jst_str(),
        "source_applied_at":           result_rec.get("applied_at", ""),
        "target_agent":                ta,
        "duplicate_key":               dup_key,
        "patch_path":                  result_rec.get("patch_path", ""),
        "agent_key":                   result_rec.get("agent_key", ""),
        "backup_path":                 result_rec.get("backup_path", ""),
        "lock_action":                 "restore_execution_blocked_true",
        "recommended_after":           "observation_window",
        "execution_blocked_restore_ready": True,
        "status":                      "pending",
        "source_queue":                "ceo_apply_execute_result_queue",
        "ceo_judgment":                "ミュウツーCEO適用後再ロック候補",
    }
    _append_jsonl(POST_APPLY_LOCK_QUEUE_PATH, lock_rec)
    _append_jsonl(POST_APPLY_LOCK_HISTORY_PATH, {
        "processed_at": _now_jst_str(),
        "target_agent": ta,
        "duplicate_key": dup_key,
        "status": "registered",
        "reason": "apply 成功後の再ロック候補として登録",
        "source_queue": "ceo_apply_execute_result_queue",
        "ceo_judgment": "ミュウツーCEO適用後再ロック候補",
    })


def sync_post_apply_lock_from_results() -> dict:
    """
    apply_execute_result_queue の applied レコードをスキャンし
    post_apply_lock_queue への未登録分を追加する。
    """
    results  = _load_jsonl(APPLY_EXECUTE_RESULT_PATH)
    applied  = [r for r in results if r.get("result_status") == "applied"]
    existing = _load_jsonl(POST_APPLY_LOCK_QUEUE_PATH)
    existing_keys = {r.get("duplicate_key", "") for r in existing}

    added = 0
    for r in applied:
        if r.get("duplicate_key", "") not in existing_keys:
            register_post_apply_lock(r)
            added += 1

    pending_total = sum(
        1 for r in _load_jsonl(POST_APPLY_LOCK_QUEUE_PATH)
        if r.get("status") == "pending"
    )
    return {"added": added, "pending": pending_total}


# ════════════════════════════════════════════════════════════════════
# 4. rollback request queue
# ════════════════════════════════════════════════════════════════════

def request_rollback(target_agent: str, reason: str = "manual_request") -> dict:
    """
    rollback 候補を1件 append する。実行はしない。
    apply_execute_result_queue から最新の backup_path / diff_path を取得。
    """
    results  = _load_jsonl(APPLY_EXECUTE_RESULT_PATH)
    relevant = [
        r for r in results
        if r.get("target_agent") == target_agent
        and r.get("result_status") in ("applied", "failed")
    ]
    latest   = relevant[-1] if relevant else {}

    dup_key  = latest.get("duplicate_key", f"{target_agent}|rollback|{_now_jst_str()}")

    existing = _load_jsonl(ROLLBACK_REQUEST_QUEUE_PATH)
    if any(r.get("duplicate_key") == dup_key and r.get("rollback_status") == "pending"
           for r in existing):
        return {"status": "already_pending", "target_agent": target_agent}

    rb_rec = {
        "requested_at":    _now_jst_str(),
        "target_agent":    target_agent,
        "duplicate_key":   dup_key,
        "backup_path":     latest.get("backup_path", ""),
        "diff_path":       latest.get("diff_path", ""),
        "config_hash":     latest.get("config_hash", ""),
        "reason":          reason,
        "rollback_ready":  True,
        "rollback_status": "pending",
        "source_queue":    "ceo_apply_execute_result_queue",
        "ceo_judgment":    "ミュウツーCEOロールバック候補",
    }
    _append_jsonl(ROLLBACK_REQUEST_QUEUE_PATH, rb_rec)
    _append_jsonl(ROLLBACK_REQUEST_HIST_PATH, {
        "processed_at":  _now_jst_str(),
        "target_agent":  target_agent,
        "duplicate_key": dup_key,
        "status":        "registered",
        "reason":        reason,
        "source_queue":  "ceo_apply_execute_result_queue",
        "ceo_judgment":  "ミュウツーCEOロールバック候補",
    })
    return {"status": "registered", "target_agent": target_agent, "backup_path": latest.get("backup_path", "")}


def sync_rollback_from_failed_results() -> dict:
    """
    apply_execute_result_queue の failed レコードから未登録分を rollback_request_queue に追加。
    """
    results  = _load_jsonl(APPLY_EXECUTE_RESULT_PATH)
    failed   = [r for r in results if r.get("result_status") == "failed"]
    existing = _load_jsonl(ROLLBACK_REQUEST_QUEUE_PATH)
    existing_keys = {r.get("duplicate_key", "") for r in existing}

    added = 0
    for r in failed:
        dup_key = r.get("duplicate_key", "")
        if dup_key not in existing_keys:
            ta = r.get("target_agent", "—")
            rb_rec = {
                "requested_at":    _now_jst_str(),
                "target_agent":    ta,
                "duplicate_key":   dup_key,
                "backup_path":     r.get("backup_path", ""),
                "diff_path":       r.get("diff_path", ""),
                "config_hash":     r.get("config_hash", ""),
                "reason":          f"apply 失敗のため自動登録: {r.get('result_reason','')}",
                "rollback_ready":  True,
                "rollback_status": "pending",
                "source_queue":    "ceo_apply_execute_result_queue",
                "ceo_judgment":    "ミュウツーCEOロールバック候補",
            }
            _append_jsonl(ROLLBACK_REQUEST_QUEUE_PATH, rb_rec)
            existing_keys.add(dup_key)
            added += 1

    pending_total = sum(
        1 for r in _load_jsonl(ROLLBACK_REQUEST_QUEUE_PATH)
        if r.get("rollback_status") == "pending"
    )
    return {"added": added, "pending": pending_total}


# ════════════════════════════════════════════════════════════════════
# 5. stale operation 検出
# ════════════════════════════════════════════════════════════════════

def scan_stale_operations() -> dict:
    """
    放置レコードを検出して stale_operation_queue に記録する。
    対象:
      - unlock pending のまま STALE_UNLOCK_MINUTES 以上
      - unlocked だが apply 未実行で期限切れ
      - apply_execute pending が STALE_APPLY_MINUTES 以上
      - rollback pending が STALE_ROLLBACK_MINUTES 以上
    """
    existing_stale = _load_jsonl(STALE_OP_QUEUE_PATH)
    existing_keys: set[str] = {
        r.get("stale_key", "") for r in existing_stale
        if r.get("status") == "pending"
    }

    added = 0

    def _add_stale(stale_key: str, op_type: str, ta: str, dup_key: str,
                   stale_min: float, recommended: str) -> None:
        nonlocal added
        if stale_key in existing_keys:
            return
        existing_keys.add(stale_key)
        rec = {
            "detected_at":        _now_jst_str(),
            "stale_key":          stale_key,
            "operation_type":     op_type,
            "target_agent":       ta,
            "duplicate_key":      dup_key,
            "stale_minutes":      round(stale_min, 1),
            "recommended_action": recommended,
            "status":             "pending",
            "source_queue":       f"ceo_{op_type.replace('_stale','').replace('unlock_','unlock_execute')}_queue.jsonl",
            "ceo_judgment":       "ミュウツーCEO stale検出",
        }
        _append_jsonl(STALE_OP_QUEUE_PATH, rec)
        _append_jsonl(STALE_OP_HISTORY_PATH, {
            "processed_at": _now_jst_str(),
            "stale_key":    stale_key,
            "status":       "detected",
            "reason":       f"{op_type}: {stale_min:.1f}分放置",
            "ceo_judgment": "ミュウツーCEO stale検出",
        })
        added += 1

    # unlock pending 放置
    for r in _load_jsonl(UNLOCK_EXECUTE_QUEUE_PATH):
        if r.get("unlock_status") != "pending":
            continue
        enqueued = r.get("enqueued_at", "")
        mins     = _minutes_since(enqueued)
        if mins >= STALE_UNLOCK_MINUTES:
            dup_key   = r.get("duplicate_key", "")
            stale_key = f"{r.get('target_agent','')}|unlock_pending_stale|{dup_key}"
            _add_stale(stale_key, "unlock_pending_stale", r.get("target_agent","—"),
                       dup_key, mins, "unlock を実行するか候補を見直す")

    # unlocked だが apply 未実行で期限切れ
    for r in _load_jsonl(UNLOCK_EXECUTE_QUEUE_PATH):
        if r.get("unlock_status") != "unlocked":
            continue
        expires_at = r.get("unlock_expires_at", "")
        if not expires_at or not is_unlock_expired(expires_at):
            continue
        dup_key   = r.get("duplicate_key", "")
        stale_key = f"{r.get('target_agent','')}|unlock_expired|{dup_key}"
        mins      = _minutes_since(r.get("unlocked_at", ""))
        _add_stale(stale_key, "unlock_expired", r.get("target_agent","—"),
                   dup_key, mins, "unlock を再実行するか再ジャッジを依頼する")

    # apply_execute pending 放置
    for r in _load_jsonl(APPLY_EXECUTE_QUEUE_PATH):
        if r.get("apply_execute_status") != "pending":
            continue
        queued = r.get("queued_at", "")
        mins   = _minutes_since(queued)
        if mins >= STALE_APPLY_MINUTES:
            dup_key   = r.get("duplicate_key", "")
            stale_key = f"{r.get('target_agent','')}|apply_stale|{dup_key}"
            _add_stale(stale_key, "apply_stale", r.get("target_agent","—"),
                       dup_key, mins, "python3 lib/ceo_unlock_executor.py apply を実行する")

    # rollback pending 放置
    for r in _load_jsonl(ROLLBACK_REQUEST_QUEUE_PATH):
        if r.get("rollback_status") != "pending":
            continue
        req_at = r.get("requested_at", "")
        mins   = _minutes_since(req_at)
        if mins >= STALE_ROLLBACK_MINUTES:
            dup_key   = r.get("duplicate_key", "")
            stale_key = f"{r.get('target_agent','')}|rollback_stale|{dup_key}"
            _add_stale(stale_key, "rollback_stale", r.get("target_agent","—"),
                       dup_key, mins, "python3 lib/ceo_config_executor.py rollback を実行する")

    pending_total = sum(
        1 for r in _load_jsonl(STALE_OP_QUEUE_PATH)
        if r.get("status") == "pending"
    )
    return {"added": added, "pending": pending_total}


# ════════════════════════════════════════════════════════════════════
# 統計
# ════════════════════════════════════════════════════════════════════

def get_hardening_stats() -> dict:
    unlock_exp    = _load_jsonl(UNLOCK_EXPIRY_QUEUE_PATH)
    post_lock     = _load_jsonl(POST_APPLY_LOCK_QUEUE_PATH)
    rollback_req  = _load_jsonl(ROLLBACK_REQUEST_QUEUE_PATH)
    stale_ops     = _load_jsonl(STALE_OP_QUEUE_PATH)
    apply_results = _load_jsonl(APPLY_EXECUTE_RESULT_PATH)

    expired_count = sum(1 for r in unlock_exp if r.get("expiry_status") == "expired")
    postlock_pend = sum(1 for r in post_lock  if r.get("status") == "pending")
    rb_pend       = sum(1 for r in rollback_req if r.get("rollback_status") == "pending")
    stale_pend    = sum(1 for r in stale_ops  if r.get("status") == "pending")
    ap_applied    = sum(1 for r in apply_results if r.get("result_status") == "applied")
    ap_blocked    = sum(1 for r in apply_results if r.get("result_status") == "blocked")

    latest_rb   = rollback_req[-1] if rollback_req else {}
    stale_latest = stale_ops[-1]   if stale_ops    else {}

    return {
        "unlock_expired_count":          expired_count,
        "apply_blocked_count":           ap_blocked,
        "apply_applied_count":           ap_applied,
        "post_apply_lock_pending_count": postlock_pend,
        "rollback_request_pending_count": rb_pend,
        "stale_operation_pending_count": stale_pend,
        "latest_rollback_agent":         latest_rb.get("target_agent", "—"),
        "latest_stale_agent":            stale_latest.get("target_agent", "—"),
    }


# ════════════════════════════════════════════════════════════════════
# 統合サイクル（自動起動用）
# ════════════════════════════════════════════════════════════════════

def run_hardening_cycle() -> dict:
    """
    expiry 検出 / post-apply lock 同期 / rollback from failed / stale 検出 を一括実行。
    実際の unlock/apply/rollback は実行しない。
    """
    expiry_result     = scan_unlock_expiry()
    postlock_result   = sync_post_apply_lock_from_results()
    rollback_result   = sync_rollback_from_failed_results()
    stale_result      = scan_stale_operations()
    return {
        "expiry":    expiry_result,
        "post_lock": postlock_result,
        "rollback":  rollback_result,
        "stale":     stale_result,
    }
