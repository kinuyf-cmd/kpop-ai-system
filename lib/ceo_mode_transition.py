#!/usr/bin/env python3
"""
ceo_mode_transition.py — モード移行チェックリスト v1.0
CEO: ミュウツー / オーナー: 人間（閲覧専用）

【役割】
  MANUAL → SAFE_AUTO の移行可否をチェックリスト形式で出力する。

【チェック項目】
  1. stale pending = 0
  2. invariant violations = 0
  3. rollback_dispatch pending = 0
  4. hardening escalated = false
  5. unlock_pick top1 exists
  6. runtime_mode current = MANUAL

【制約】
  - モード自動変更禁止
  - config 書き込み禁止
  - execution_blocked 変更禁止
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

STALE_OP_QUEUE          = LOGS / "ceo_stale_operation_queue.jsonl"
INVARIANT_QUEUE         = LOGS / "ceo_invariant_violation_queue.jsonl"
ROLLBACK_DISPATCH_QUEUE = LOGS / "ceo_rollback_dispatch_queue.jsonl"
UNLOCK_PICK_QUEUE       = LOGS / "ceo_unlock_pick_queue.jsonl"
UNLOCK_EXECUTE_QUEUE    = LOGS / "ceo_unlock_execute_queue.jsonl"
APPLY_EXECUTE_QUEUE     = LOGS / "ceo_apply_execute_queue.jsonl"
DASHBOARD_SUMMARY       = BASE / "dashboard_summary.json"
RUNTIME_MODE_PATH       = BASE / "config" / "runtime_mode.json"

TRANSITION_QUEUE   = LOGS / "ceo_mode_transition_queue.jsonl"
TRANSITION_HISTORY = LOGS / "ceo_mode_transition_history.jsonl"


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


def _load_current_mode() -> str:
    if not RUNTIME_MODE_PATH.exists():
        return "MANUAL"
    try:
        return json.loads(RUNTIME_MODE_PATH.read_text(encoding="utf-8")).get("mode", "MANUAL")
    except Exception:
        return "MANUAL"


def _load_hardening_escalated() -> bool:
    try:
        s = json.loads(DASHBOARD_SUMMARY.read_text(encoding="utf-8"))
        return bool(s.get("hardening_is_escalated", False))
    except Exception:
        return False


def _transition_key(checked_at: str) -> str:
    return checked_at[:16]


# ═══════════════════════════════════════════════════════════════════
# チェックリスト
# ═══════════════════════════════════════════════════════════════════

def run_mode_transition_check() -> dict:
    """
    MANUAL → SAFE_AUTO の移行可否チェックリストを生成する。
    分単位で重複スキップ。
    """
    checked_at = _now_jst()
    tkey       = _transition_key(checked_at)

    existing = _load_jsonl(TRANSITION_QUEUE)
    existing_keys = {_transition_key(r.get("checked_at", "")) for r in existing}

    # ── unlock済み duplicate_key（stale除外用）──
    already_unlocked = {r.get("duplicate_key", "")
                        for r in _load_jsonl(UNLOCK_EXECUTE_QUEUE)
                        if r.get("unlock_status") == "unlocked"
                        and r.get("actual_unlocked") is True}

    # ── 各条件チェック ──
    stale_pending = len([r for r in _load_jsonl(STALE_OP_QUEUE)
                         if r.get("status") == "pending"
                         and r.get("duplicate_key", "") not in already_unlocked])
    inv_pending   = len([r for r in _load_jsonl(INVARIANT_QUEUE)
                         if r.get("violation_status") == "pending"])
    rb_pending    = len([r for r in _load_jsonl(ROLLBACK_DISPATCH_QUEUE)
                         if r.get("router_status") == "pending"])
    escalated     = _load_hardening_escalated()
    current_mode  = _load_current_mode()

    # unlock_pick top1 存在チェック
    # ※ apply_execute_queue に pending があれば unlock 不要（unlock済みで次ステージ）
    apply_pending = len([r for r in _load_jsonl(APPLY_EXECUTE_QUEUE)
                         if r.get("apply_execute_status") == "pending"
                         or r.get("apply_status") == "pending"])
    pick_recs     = _load_jsonl(UNLOCK_PICK_QUEUE)
    top1_pick     = next((r for r in reversed(pick_recs)
                          if r.get("is_top") and r.get("pick_status") in ("active", "pending")), None)
    has_pick      = top1_pick is not None or apply_pending > 0

    check_items = [
        {
            "name":    "stale_operation pending = 0",
            "ok":      stale_pending == 0,
            "current": f"pending={stale_pending}",
            "fix":     "bash run_agent_monitor.sh  # BO stale解消候補を確認し手動unlock実行" if stale_pending > 0 else "",
        },
        {
            "name":    "invariant_violation pending = 0",
            "ok":      inv_pending == 0,
            "current": f"pending={inv_pending}",
            "fix":     "bash run_agent_monitor.sh  # BG安全不変条件を確認・手動解消" if inv_pending > 0 else "",
        },
        {
            "name":    "rollback_dispatch pending = 0",
            "ok":      rb_pending == 0,
            "current": f"pending={rb_pending}",
            "fix":     "python3 lib/ceo_config_executor.py rollback <agent>  # rollback確認" if rb_pending > 0 else "",
        },
        {
            "name":    "hardening escalated = false",
            "ok":      not escalated,
            "current": f"escalated={escalated}",
            "fix":     "bash run_agent_monitor.sh  # BA Hardening最優先を確認" if escalated else "",
        },
        {
            "name":    "unlock_pick top1 exists (or apply_pending > 0)",
            "ok":      has_pick,
            "current": f"top1={'あり' if top1_pick else 'なし'} / apply_pending={apply_pending}",
            "fix":     "python3 lib/agent_monitor.py  # Phase32 unlock_pick を実行" if not has_pick else "",
        },
        {
            "name":    "runtime_mode = MANUAL（現在モード確認）",
            "ok":      current_mode == "MANUAL",
            "current": f"mode={current_mode}",
            "fix":     "" if current_mode == "MANUAL" else f"現在 {current_mode} モード — MANUAL に戻してから再確認",
        },
    ]

    all_green       = all(item["ok"] for item in check_items)
    transition_status = "ready" if all_green else "blocked"

    # next_command 決定
    first_fail = next((item for item in check_items if not item["ok"]), None)
    if all_green:
        next_cmd = (
            'python3 -c "'
            "import json; from pathlib import Path; "
            "p=Path('config/runtime_mode.json'); "
            "c=json.loads(p.read_text()); "
            "c['mode']='SAFE_AUTO'; "
            "p.write_text(json.dumps(c,ensure_ascii=False,indent=2)+'\\\\n')"
            '"  # SAFE_AUTO に切替'
        )
        next_reason = "全条件クリア — SAFE_AUTO への切替が可能"
    else:
        next_cmd    = first_fail["fix"] if first_fail else "bash run_agent_monitor.sh"
        next_reason = f"未クリア項目: {first_fail['name']}" if first_fail else "不明"

    rec = {
        "checked_at":        checked_at,
        "transition_from":   "MANUAL",
        "transition_to":     "SAFE_AUTO",
        "current_mode":      current_mode,
        "check_items":       check_items,
        "all_green":         all_green,
        "transition_status": transition_status,
        "failed_count":      sum(1 for i in check_items if not i["ok"]),
        "next_command":      next_cmd,
        "next_reason":       next_reason,
        "execution_blocked": True,
        "write_scope":       "none",
        "ceo_judgment":      "ミュウツーCEOモード移行判定",
    }
    _append_jsonl(TRANSITION_QUEUE, rec)
    _append_jsonl(TRANSITION_HISTORY, {
        "processed_at":      checked_at,
        "transition_status": transition_status,
        "all_green":         all_green,
        "failed_count":      rec["failed_count"],
        "ceo_judgment":      "ミュウツーCEOモード移行判定",
    })
    return _stats_from_rec(rec)


def _stats_from_rec(rec: dict) -> dict:
    items = rec.get("check_items", [])
    return {
        "mode_transition_ready":        rec.get("all_green", False),
        "mode_transition_status":       rec.get("transition_status", "blocked"),
        "mode_transition_failed_count": rec.get("failed_count", 0),
        "mode_transition_next_command": rec.get("next_command", "—"),
        "mode_transition_next_reason":  rec.get("next_reason", "—"),
        "mode_transition_check_items":  items,
    }


def get_mode_transition_stats() -> dict:
    recs   = _load_jsonl(TRANSITION_QUEUE)
    latest = recs[-1] if recs else {}
    return _stats_from_rec(latest)


if __name__ == "__main__":
    import json as _json
    result = run_mode_transition_check()
    print(_json.dumps(result, ensure_ascii=False, indent=2))
