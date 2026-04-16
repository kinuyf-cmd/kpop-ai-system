#!/usr/bin/env python3
"""
ceo_unlock_executor.py — 解放実行・apply実行エンジン v1.0
CEO: ミュウツー / オーナー: 人間（閲覧専用）

【フロー】
  AR（unlock_judge_queue）→ unlock_execute_queue → [明示実行] → apply_execute_queue → apply実行 → apply_execute_result_queue

【制約】
  - unlock と apply は自動連鎖しない
  - unlock は execute_unlock_candidate(duplicate_key) を明示呼び出しした時のみ actual_unlocked=true になる
  - apply は actual_unlocked==true の候補のみ対象
  - config/agent_directives.json への書き込みは apply_execute_queue からのみ
  - 1レコード = 1キー = action フィールドのみ
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

# ── パス定義 ─────────────────────────────────────────────────────────
UNLOCK_JUDGE_QUEUE_PATH      = LOGS / "ceo_reinject_unlock_judge_queue.jsonl"
UNLOCK_EXECUTE_QUEUE_PATH    = LOGS / "ceo_unlock_execute_queue.jsonl"
UNLOCK_EXECUTE_HISTORY_PATH  = LOGS / "ceo_unlock_execute_history.jsonl"
APPLY_EXECUTE_QUEUE_PATH     = LOGS / "ceo_apply_execute_queue.jsonl"
APPLY_EXECUTE_HISTORY_PATH   = LOGS / "ceo_apply_execute_history.jsonl"
APPLY_EXECUTE_RESULT_PATH    = LOGS / "ceo_apply_execute_result_queue.jsonl"
STALE_OPERATION_QUEUE_PATH   = LOGS / "ceo_stale_operation_queue.jsonl"


# ── ユーティリティ ────────────────────────────────────────────────────

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


def _make_unlock_dup_key(rec: dict) -> str:
    agent  = rec.get("target_agent", "")
    ftype  = rec.get("feedback_type", "")
    hint   = (rec.get("next_improvement_hint", "") or "").strip()
    if hint:
        return f"{agent}|{ftype}|{hint[:80]}"
    action = (rec.get("proposed_reinject_action", "") or "").strip()
    if action:
        return f"{agent}|{ftype}|{action[:80]}"
    after  = (rec.get("after_value", "") or "").strip()
    return f"{agent}|{ftype}|{after[:80]}"


def _agent_key_from_patch_path(patch_path: str) -> str:
    """agent_directives.{agent_key}.action → {agent_key}"""
    parts = patch_path.split(".")
    if len(parts) >= 2:
        return parts[1]
    return ""


# ════════════════════════════════════════════════════════════════════
# フェーズ1: unlock_judge_queue → unlock_execute_queue
# ════════════════════════════════════════════════════════════════════

def build_unlock_execute_queue() -> dict:
    """
    unlock_judge_queue の pending レコードを unlock_execute_queue に昇格する。
    actual_unlocked=false のまま（unlock 実行前）。
    """
    judge_recs      = _load_jsonl(UNLOCK_JUDGE_QUEUE_PATH)
    existing_unlock = _load_jsonl(UNLOCK_EXECUTE_QUEUE_PATH)

    existing_dup_keys: set[str] = {
        r.get("duplicate_key", "")
        for r in existing_unlock
        if r.get("unlock_status") in ("pending", "unlocked", "archived")
    }

    candidates = [
        r for r in judge_recs
        if r.get("judge_status") == "pending"
        and r.get("judge_result") == "unlockable_if_unblocked"
        and r.get("execution_blocked") is True
        and r.get("write_scope") == "queue_only"
        and r.get("unlock_target") == "execution_blocked_toggle_only"
        and (r.get("target_agent") or "").strip()
        and (r.get("patch_path") or "").startswith("agent_directives.")
    ]
    candidates.sort(key=lambda r: (-float(r.get("priority_score", 0)), r.get("target_agent", "")))

    promoted  = 0
    skipped   = 0
    dup_count = 0

    for rec in candidates:
        dup_key = rec.get("duplicate_key", "") or _make_unlock_dup_key(rec)
        ta      = (rec.get("target_agent") or "").strip()

        hist_base = {
            "processed_at": _now_jst(),
            "target_agent": ta,
            "duplicate_key": dup_key,
            "source_queue": "ceo_reinject_unlock_judge_queue",
            "ceo_judgment": "ミュウツーCEO解放実行待ち",
        }

        if dup_key in existing_dup_keys:
            dup_count += 1
            _append_jsonl(UNLOCK_EXECUTE_HISTORY_PATH, {
                **hist_base,
                "status": "unlock_execute_duplicate",
                "reason": f"同一 duplicate_key が unlock_execute_queue に存在: {dup_key}",
            })
            continue

        existing_dup_keys.add(dup_key)
        ppath   = (rec.get("patch_path") or "").strip()
        akey    = _agent_key_from_patch_path(ppath)
        after_v = (rec.get("after_value") or "").strip()
        nexec   = (rec.get("next_executor") or "ceo_config_executor.py").strip()

        unlock_rec = {
            "enqueued_at":        _now_jst(),
            "source_judged_at":   rec.get("judged_at", ""),
            "target_agent":       ta,
            "feedback_type":      rec.get("feedback_type", ""),
            "priority":           rec.get("priority", ""),
            "priority_score":     rec.get("priority_score", 0.0),
            "patch_path":         ppath,
            "agent_key":          akey,
            "after_value":        after_v,
            "next_executor":      nexec,
            "unlock_action":      "set_execution_blocked_false_candidate",
            "actual_unlocked":    False,
            "unlock_status":      "pending",
            "execution_blocked":  True,
            "write_scope":        "queue_only",
            "unlock_target":      "execution_blocked_toggle_only",
            "duplicate_key":      dup_key,
            "source_queue":       "ceo_reinject_unlock_judge_queue",
            "ceo_judgment":       "ミュウツーCEO解放実行待ち",
        }
        _append_jsonl(UNLOCK_EXECUTE_QUEUE_PATH, unlock_rec)
        _append_jsonl(UNLOCK_EXECUTE_HISTORY_PATH, {
            **hist_base,
            "status": "promoted",
            "reason": f"unlock_execute_queue に昇格: priority={rec.get('priority')} score={rec.get('priority_score',0):.3f}",
        })
        promoted += 1

    pending_total = sum(
        1 for r in _load_jsonl(UNLOCK_EXECUTE_QUEUE_PATH)
        if r.get("unlock_status") == "pending"
    )
    return {"promoted": promoted, "skipped": skipped, "dup": dup_count, "pending": pending_total}


# ════════════════════════════════════════════════════════════════════
# フェーズ2: 明示 unlock 実行
# ════════════════════════════════════════════════════════════════════

def execute_unlock_candidate(duplicate_key: str) -> dict:
    """
    unlock_execute_queue の指定 duplicate_key レコード1件だけを
    actual_unlocked=true として記録し、unlock_status を "unlocked" に変更する。
    config は変更しない。この関数は自動起動しない。明示呼び出しのみ。

    戻り値: {"status": "unlocked"|"not_found"|"already_unlocked", "target_agent": str, "reason": str}
    """
    recs = _load_jsonl(UNLOCK_EXECUTE_QUEUE_PATH)

    # 対象を探す
    target_rec = None
    for r in recs:
        if r.get("duplicate_key") == duplicate_key and r.get("unlock_status") == "pending":
            target_rec = r
            break

    if target_rec is None:
        # already unlocked?
        for r in recs:
            if r.get("duplicate_key") == duplicate_key and r.get("unlock_status") == "unlocked":
                return {
                    "status": "already_unlocked",
                    "target_agent": r.get("target_agent", "—"),
                    "reason": "既に unlocked 済み",
                }
        return {
            "status": "not_found",
            "target_agent": "—",
            "reason": f"duplicate_key={duplicate_key} の pending レコードが見つからない",
        }

    ta = target_rec.get("target_agent", "—")

    # unlock 記録: 既存 queue に "unlocked" レコードを append
    # （元の pending は変更せず、unlocked バージョンを append-only で追加）
    unlocked_at_str = _now_jst()
    from lib.ceo_apply_hardening import compute_unlock_expires_at
    unlock_expires_at = compute_unlock_expires_at(unlocked_at_str)

    unlocked_rec = {
        **target_rec,
        "unlocked_at":        unlocked_at_str,
        "unlock_expires_at":  unlock_expires_at,
        "actual_unlocked":    True,
        "unlock_status":      "unlocked",
        "execution_blocked":  False,       # unlock = execution_blocked を false 宣言
        "write_scope":        "config_single_key",  # apply 実行可スコープへ昇格
    }
    _append_jsonl(UNLOCK_EXECUTE_QUEUE_PATH, unlocked_rec)
    _append_jsonl(UNLOCK_EXECUTE_HISTORY_PATH, {
        "processed_at":  _now_jst(),
        "target_agent":  ta,
        "duplicate_key": duplicate_key,
        "status":        "unlock_executed",
        "reason":        f"明示 unlock 実行: actual_unlocked=true / execution_blocked=false / write_scope=config_single_key",
        "source_queue":  "ceo_unlock_execute_queue",
        "ceo_judgment":  "ミュウツーCEO解放実行",
    })
    # stale_operation_queue に resolved レコードを append（正規化: Phase C）
    _append_jsonl(STALE_OPERATION_QUEUE_PATH, {
        "resolved_at":    _now_jst(),
        "target_agent":   ta,
        "duplicate_key":  duplicate_key,
        "status":         "resolved",
        "resolved_by":    "ceo_unlock_executor.execute_unlock_candidate",
        "resolve_reason": "明示 unlock 実行により stale 解消",
        "source_queue":   "ceo_unlock_execute_queue",
        "ceo_judgment":   "ミュウツーCEO stale解消記録",
    })

    return {
        "status":       "unlocked",
        "target_agent": ta,
        "reason":       f"{ta} の unlock 完了。apply_execute_queue への昇格待ち。",
    }


# ════════════════════════════════════════════════════════════════════
# フェーズ3: unlock_execute_queue(unlocked) → apply_execute_queue
# ════════════════════════════════════════════════════════════════════

def build_apply_execute_queue() -> dict:
    """
    unlock_execute_queue の actual_unlocked==true レコードを
    apply_execute_queue に昇格する。
    """
    unlock_recs   = _load_jsonl(UNLOCK_EXECUTE_QUEUE_PATH)
    existing_apply = _load_jsonl(APPLY_EXECUTE_QUEUE_PATH)

    existing_dup_keys: set[str] = {
        r.get("duplicate_key", "")
        for r in existing_apply
        if r.get("apply_execute_status") in ("pending", "applied", "archived")
    }

    # actual_unlocked==true かつ unlocked ステータスのみ
    candidates = [
        r for r in unlock_recs
        if r.get("actual_unlocked") is True
        and r.get("unlock_status") == "unlocked"
        and r.get("execution_blocked") is False
        and r.get("write_scope") == "config_single_key"
        and r.get("next_executor") == "ceo_config_executor.py"
        and (r.get("patch_path") or "").startswith("agent_directives.")
        and (r.get("agent_key") or "").strip()
        and (r.get("after_value") or "").strip()
    ]
    candidates.sort(key=lambda r: (-float(r.get("priority_score", 0)), r.get("target_agent", "")))

    promoted  = 0
    dup_count = 0

    for rec in candidates:
        dup_key = rec.get("duplicate_key", "")
        ta      = (rec.get("target_agent") or "").strip()

        hist_base = {
            "processed_at": _now_jst(),
            "target_agent": ta,
            "duplicate_key": dup_key,
            "source_queue": "ceo_unlock_execute_queue",
            "ceo_judgment": "ミュウツーCEO apply実行待ち",
        }

        if dup_key in existing_dup_keys:
            dup_count += 1
            _append_jsonl(APPLY_EXECUTE_HISTORY_PATH, {
                **hist_base,
                "status": "apply_execute_duplicate",
                "reason": f"同一 duplicate_key が apply_execute_queue に存在: {dup_key}",
            })
            continue

        existing_dup_keys.add(dup_key)
        ppath   = (rec.get("patch_path") or "").strip()
        akey    = (rec.get("agent_key") or _agent_key_from_patch_path(ppath)).strip()
        after_v = (rec.get("after_value") or "").strip()

        apply_rec = {
            "queued_at":             _now_jst(),
            "source_unlocked_at":    rec.get("unlocked_at", ""),
            "target_agent":          ta,
            "feedback_type":         rec.get("feedback_type", ""),
            "priority":              rec.get("priority", ""),
            "priority_score":        rec.get("priority_score", 0.0),
            "target_config":         "config/agent_directives.json",
            "patch_path":            ppath,
            "agent_key":             akey,
            "patch_mode":            "upsert_agent_directive",
            "after_value":           after_v,
            "before_value":          "",
            "backup_required":       True,
            "apply_execute_ready":   True,
            "apply_execute_status":  "pending",
            "write_scope":           "config_single_key",
            "next_executor":         rec.get("next_executor", "ceo_config_executor.py"),
            "duplicate_key":         dup_key,
            "source_queue":          "ceo_unlock_execute_queue",
            "ceo_judgment":          "ミュウツーCEO apply実行待ち",
        }
        _append_jsonl(APPLY_EXECUTE_QUEUE_PATH, apply_rec)
        _append_jsonl(APPLY_EXECUTE_HISTORY_PATH, {
            **hist_base,
            "status": "promoted",
            "reason": f"apply_execute_queue に昇格: agent_key={akey}",
        })
        promoted += 1

    pending_total = sum(
        1 for r in _load_jsonl(APPLY_EXECUTE_QUEUE_PATH)
        if r.get("apply_execute_status") == "pending"
    )
    return {"promoted": promoted, "dup": dup_count, "pending": pending_total}


# ════════════════════════════════════════════════════════════════════
# フェーズ4: apply_execute_queue → config/agent_directives.json 実行
# ════════════════════════════════════════════════════════════════════

def apply_execute_queue() -> dict:
    """
    apply_execute_queue の pending を読み、ceo_config_executor の
    _apply_single_record を流用して config/agent_directives.json に書き込む。
    結果を ceo_apply_execute_result_queue.jsonl に記録。
    """
    from lib.ceo_config_executor import (
        _check_blocked,
        _make_backup,
        _write_diff_file,
        _load_json_safe,
        _write_json_pretty,
        CONFIG_TARGET,
        _DIRECTIVE_FIELD,
    )
    from datetime import datetime as _dt

    pending = [
        r for r in _load_jsonl(APPLY_EXECUTE_QUEUE_PATH)
        if r.get("apply_execute_status") == "pending"
        and r.get("apply_execute_ready") is True
    ]
    pending.sort(key=lambda r: r.get("queued_at", ""))

    # result queue の既存 duplicate_key セット
    existing_results: set[str] = {
        r.get("duplicate_key", "")
        for r in _load_jsonl(APPLY_EXECUTE_RESULT_PATH)
        if r.get("result_status") in ("applied", "blocked", "failed")
    }

    applied_count     = 0
    blocked_count     = 0
    failed_count      = 0
    skipped_duplicate = 0

    for rec in pending:
        dup_key = rec.get("duplicate_key", "")
        ta      = rec.get("target_agent", "")
        now_str = _now_jst()

        if dup_key in existing_results:
            skipped_duplicate += 1
            _append_jsonl(APPLY_EXECUTE_RESULT_PATH, {
                "applied_at":    now_str,
                "target_agent":  ta,
                "duplicate_key": dup_key,
                "result_status": "skipped_duplicate",
                "result_reason": "既に apply_execute_result_queue に存在",
                "source_queue":  "ceo_apply_execute_queue",
                "ceo_judgment":  "ミュウツーCEO apply実行結果",
            })
            continue

        # ハードニング事前チェック
        from lib.ceo_apply_hardening import check_apply_preconditions
        precond_ok, precond_reason = check_apply_preconditions(rec)
        if not precond_ok:
            blocked_count += 1
            result = {
                "applied_at":    now_str,
                "target_agent":  ta,
                "duplicate_key": dup_key,
                "result_status": "blocked",
                "result_reason": f"[hardening] {precond_reason}",
                "patch_path":    rec.get("patch_path", ""),
                "before_value":  "",
                "after_value":   rec.get("after_value", ""),
                "backup_path":   "",
                "diff_path":     "",
                "source_queue":  "ceo_apply_execute_queue",
                "ceo_judgment":  "ミュウツーCEO apply実行結果",
            }
            _append_jsonl(APPLY_EXECUTE_RESULT_PATH, result)
            existing_results.add(dup_key)
            continue

        # write_scope チェック（config_single_key のみ許可）
        if rec.get("write_scope") != "config_single_key":
            blocked_count += 1
            result = {
                "applied_at":    now_str,
                "target_agent":  ta,
                "duplicate_key": dup_key,
                "result_status": "blocked",
                "result_reason": f"write_scope={rec.get('write_scope')} (config_single_key 以外)",
                "patch_path":    rec.get("patch_path", ""),
                "before_value":  "",
                "after_value":   rec.get("after_value", ""),
                "backup_path":   "",
                "diff_path":     "",
                "source_queue":  "ceo_apply_execute_queue",
                "ceo_judgment":  "ミュウツーCEO apply実行結果",
            }
            _append_jsonl(APPLY_EXECUTE_RESULT_PATH, result)
            continue

        # 既存 executor の _check_blocked を流用（write_scope を一時的に変換）
        check_rec = {**rec, "write_scope": "config_only"}
        is_blocked, block_reason = _check_blocked(check_rec)
        if is_blocked:
            blocked_count += 1
            result = {
                "applied_at":    now_str,
                "target_agent":  ta,
                "duplicate_key": dup_key,
                "result_status": "blocked",
                "result_reason": block_reason,
                "patch_path":    rec.get("patch_path", ""),
                "before_value":  "",
                "after_value":   rec.get("after_value", ""),
                "backup_path":   "",
                "diff_path":     "",
                "source_queue":  "ceo_apply_execute_queue",
                "ceo_judgment":  "ミュウツーCEO apply実行結果",
            }
            _append_jsonl(APPLY_EXECUTE_RESULT_PATH, result)
            existing_results.add(dup_key)
            continue

        agent_key   = rec.get("agent_key", "")
        after_value = rec.get("after_value", "")
        backup_path = ""
        diff_path   = ""

        try:
            config_data  = _load_json_safe(CONFIG_TARGET)
            ad           = config_data.setdefault("agent_directives", {})
            backup_path  = _make_backup(ta, reason="before_reinject_apply")

            existing_entry = ad.get(agent_key, {})
            if isinstance(existing_entry, dict):
                before_value = existing_entry.get(_DIRECTIVE_FIELD, "")
            elif isinstance(existing_entry, str):
                before_value = existing_entry
            else:
                before_value = ""

            diff_path = _write_diff_file(agent_key, before_value, after_value)

            if agent_key not in ad:
                ad[agent_key] = {}
            if not isinstance(ad[agent_key], dict):
                ad[agent_key] = {"_original": ad[agent_key]}
            ad[agent_key][_DIRECTIVE_FIELD] = after_value
            ad[agent_key]["set_at"]         = _dt.now(JST).strftime("%Y-%m-%d")
            ad[agent_key]["source"]         = "ceo_unlock_executor"
            ad[agent_key]["target_agent"]   = ta

            _write_json_pretty(CONFIG_TARGET, config_data)

            # config ハッシュ（簡易）
            import hashlib
            config_hash = hashlib.md5(
                CONFIG_TARGET.read_text(encoding="utf-8").encode()
            ).hexdigest()[:8]

            result = {
                "applied_at":    now_str,
                "target_agent":  ta,
                "duplicate_key": dup_key,
                "result_status": "applied",
                "result_reason": "正常適用完了（reinject apply）",
                "target_config": "config/agent_directives.json",
                "patch_path":    rec.get("patch_path", ""),
                "agent_key":     agent_key,
                "before_value":  before_value,
                "after_value":   after_value,
                "backup_path":   backup_path,
                "diff_path":     diff_path,
                "config_hash":   config_hash,
                "source_queue":  "ceo_apply_execute_queue",
                "ceo_judgment":  "ミュウツーCEO apply実行結果",
            }
            applied_count += 1

            # post-apply ロック候補を登録
            from lib.ceo_apply_hardening import register_post_apply_lock
            register_post_apply_lock(result)

        except Exception as e:
            result = {
                "applied_at":    now_str,
                "target_agent":  ta,
                "duplicate_key": dup_key,
                "result_status": "failed",
                "result_reason": f"例外: {e}",
                "target_config": "config/agent_directives.json",
                "patch_path":    rec.get("patch_path", ""),
                "agent_key":     agent_key,
                "before_value":  "",
                "after_value":   after_value,
                "backup_path":   backup_path,
                "diff_path":     diff_path,
                "config_hash":   "",
                "source_queue":  "ceo_apply_execute_queue",
                "ceo_judgment":  "ミュウツーCEO apply実行結果",
            }
            failed_count += 1

        _append_jsonl(APPLY_EXECUTE_RESULT_PATH, result)
        existing_results.add(dup_key)

    return {
        "applied":           applied_count,
        "blocked":           blocked_count,
        "failed":            failed_count,
        "skipped_duplicate": skipped_duplicate,
    }


# ════════════════════════════════════════════════════════════════════
# 統計
# ════════════════════════════════════════════════════════════════════

def get_unlock_execute_stats() -> dict:
    recs      = _load_jsonl(UNLOCK_EXECUTE_QUEUE_PATH)
    pending   = [r for r in recs if r.get("unlock_status") == "pending"]
    unlocked  = [r for r in recs if r.get("unlock_status") == "unlocked"]
    latest    = (unlocked or pending or recs)[-1] if recs else {}
    return {
        "unlock_execute_pending_count":  len(pending),
        "unlock_execute_unlocked_count": len(unlocked),
        "unlock_execute_latest_agent":   latest.get("target_agent", "—"),
        "unlock_execute_latest_status":  latest.get("unlock_status", "—"),
    }


def get_apply_execute_stats() -> dict:
    recs    = _load_jsonl(APPLY_EXECUTE_QUEUE_PATH)
    pending = [r for r in recs if r.get("apply_execute_status") == "pending"]
    results = _load_jsonl(APPLY_EXECUTE_RESULT_PATH)
    applied = [r for r in results if r.get("result_status") == "applied"]
    failed  = [r for r in results if r.get("result_status") == "failed"]
    latest  = results[-1] if results else {}
    return {
        "apply_execute_pending_count":     len(pending),
        "apply_execute_applied_count":     len(applied),
        "apply_execute_failed_count":      len(failed),
        "apply_execute_latest_agent":      latest.get("target_agent", "—"),
        "apply_execute_latest_status":     latest.get("result_status", "—"),
        "apply_execute_latest_config_hash": latest.get("config_hash", "—"),
    }


# ════════════════════════════════════════════════════════════════════
# 統合実行（自動起動サイクル）
# ════════════════════════════════════════════════════════════════════

def run_unlock_pipeline_cycle() -> dict:
    """
    フェーズ1+3のみ自動実行（unlock判定キュー構築 + apply待ちキュー構築）。
    フェーズ2（明示unlock）とフェーズ4（apply実行）は含まない。
    """
    unlock_result = build_unlock_execute_queue()
    apply_result  = build_apply_execute_queue()
    return {"unlock": unlock_result, "apply_queue": apply_result}


if __name__ == "__main__":
    import sys
    args = sys.argv[1:]
    if args and args[0] == "unlock":
        if len(args) < 2:
            print("使用法: python3 ceo_unlock_executor.py unlock <duplicate_key>")
            sys.exit(1)
        dup_key = args[1]
        result  = execute_unlock_candidate(dup_key)
        print(f"unlock: {result}")
    elif args and args[0] == "apply":
        result = apply_execute_queue()
        print(f"apply: {result}")
        stats  = get_apply_execute_stats()
        print(f"stats: {stats}")
    else:
        result = run_unlock_pipeline_cycle()
        print(f"cycle: {result}")
