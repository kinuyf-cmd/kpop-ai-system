"""
ceo_reinject_commit.py — patch_plan queue への再投入コミット
フェーズ1: reinject_patch_reserve_queue → reinject_patch_commit_queue
フェーズ2: reinject_patch_commit_queue → ceo_config_patch_plan_queue（append-only）

config/agent_directives.json 本体は変更しない。
patch_plan queue への再投入のみ。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"

RESERVE_QUEUE_PATH    = LOGS / "ceo_reinject_patch_reserve_queue.jsonl"
COMMIT_QUEUE_PATH     = LOGS / "ceo_reinject_patch_commit_queue.jsonl"
COMMIT_HISTORY_PATH   = LOGS / "ceo_reinject_patch_commit_history.jsonl"
PATCH_PLAN_QUEUE_PATH = LOGS / "ceo_config_patch_plan_queue.jsonl"

# カタカナ名 → agent_key マップ
_AGENT_KEY_MAP: dict[str, str] = {
    "バタフリー":  "butterfree",
    "X投稿B":     "x_post_b",
    "X投稿":      "x_post",
    "サーナイト":  "gardevoir_hook_critic",
    "カイリュー":  "kairyu",
    "アルセウス":  "arceus",
    "WP投稿":     "wp_poster",
    "デオキシス":  "deoxys",
    "メタモン":   "metamon",
    "イーブイ":   "eevee",
    "ジラーチ":   "jirachi",
    "ミュウツー":  "mewtwo",
    "ラプラス":   "lapras",
    "ミミッキュ":  "mimikyu",
    "ソーナンス":  "wobbuffet",
}

_LABEL_TO_PRIORITY = {"CRITICAL": "HIGH", "HIGH": "HIGH", "MEDIUM": "MEDIUM", "LOW": "LOW"}


# ────────────────────────────────────────────
# ユーティリティ
# ────────────────────────────────────────────

def _now_jst() -> str:
    jst = timezone(timedelta(hours=9))
    return datetime.now(jst).strftime("%Y-%m-%d %H:%M:%S JST")


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


def _make_dup_key(rec: dict) -> str:
    agent = rec.get("target_agent", "")
    ftype = rec.get("feedback_type", "")
    hint  = (rec.get("next_improvement_hint", "") or "").strip()
    if hint:
        return f"{agent}|{ftype}|{hint[:80]}"
    action = (rec.get("proposed_reinject_action", "") or "").strip()
    return f"{agent}|{ftype}|{action[:80]}"


def _agent_key(target_agent: str) -> str:
    return _AGENT_KEY_MAP.get(target_agent, target_agent.lower().replace(" ", "_"))


def _patch_path(target_agent: str) -> str:
    key = _agent_key(target_agent)
    return f"agent_directives.{key}.action"


def _proposed_change(rec: dict) -> str:
    """patch_plan の after_value に使う改善内容"""
    hint   = (rec.get("next_improvement_hint", "") or "").strip()
    action = (rec.get("proposed_reinject_action", "") or "").strip()
    # hint から "[fail_rate=...] " プレフィックスを除いた本文を使う
    if hint:
        # "[xxx] テキスト" → "テキスト" を取り出す
        import re
        cleaned = re.sub(r"^\[.*?\]\s*", "", hint).strip()
        return cleaned if cleaned else action
    return action


# ────────────────────────────────────────────
# フェーズ1: reserve → commit_queue
# ────────────────────────────────────────────

def build_commit_queue() -> dict:
    """reserve_order==1 の候補だけ commit_queue に登録"""
    reserve_recs   = _load_jsonl(RESERVE_QUEUE_PATH)
    existing_commit = _load_jsonl(COMMIT_QUEUE_PATH)

    existing_dup_keys: set[str] = {
        r.get("duplicate_key", "")
        for r in existing_commit
        if r.get("commit_status") in ("pending", "archived")
    }

    # 対象: reserve_order==1 + pending + ready
    candidates = [
        r for r in reserve_recs
        if r.get("reserve_status") == "pending"
        and r.get("reserve_ready") is True
        and int(r.get("reserve_order", 0)) == 1
    ]

    committed = 0
    dup_count  = 0

    for rec in candidates:
        dup_key = _make_dup_key(rec)

        commit_rec = {
            "committed_at":            _now_jst(),
            "source_reserved_at":      rec.get("reserved_at", ""),
            "target_agent":            rec.get("target_agent", ""),
            "feedback_type":           rec.get("feedback_type", ""),
            "reinject_priority_score": rec.get("reinject_priority_score", 0.0),
            "reserve_priority_score":  rec.get("reserve_priority_score", 0.0),
            "reserve_label":           rec.get("reserve_label", ""),
            "reserve_order":           rec.get("reserve_order", 1),
            "proposed_reinject_action": rec.get("proposed_reinject_action", ""),
            "next_improvement_hint":   rec.get("next_improvement_hint", ""),
            "patch_target_lane":       rec.get("patch_target_lane", "ceo_config_patch_plan_queue"),
            "commit_ready":            True,
            "commit_status":           "pending",
            "execution_blocked":       True,
            "write_scope":             "queue_only",
            "committed_from":          "ceo_reinject_patch_reserve_queue",
            "duplicate_key":           dup_key,
            "ceo_judgment":            "ミュウツーCEO再投入コミット",
        }

        if dup_key in existing_dup_keys:
            dup_count += 1
            _append_jsonl(COMMIT_HISTORY_PATH, {
                **commit_rec,
                "commit_status": "commit_duplicate",
                "reason": f"同一 duplicate_key が commit_queue に pending/archived で存在: {dup_key}",
            })
            continue

        existing_dup_keys.add(dup_key)
        _append_jsonl(COMMIT_QUEUE_PATH, commit_rec)
        committed += 1

    pending_total = sum(
        1 for r in _load_jsonl(COMMIT_QUEUE_PATH)
        if r.get("commit_status") == "pending"
    )
    return {"committed": committed, "dup": dup_count, "pending": pending_total}


# ────────────────────────────────────────────
# フェーズ2: commit_queue → patch_plan_queue
# ────────────────────────────────────────────

def promote_to_patch_plan() -> dict:
    """commit_queue(pending) を ceo_config_patch_plan_queue に append-only で再投入"""
    commit_recs  = _load_jsonl(COMMIT_QUEUE_PATH)
    patch_recs   = _load_jsonl(PATCH_PLAN_QUEUE_PATH)

    # patch_plan の重複チェック: pending/archived の duplicate_key（source問わず）
    existing_patch_dup_keys: set[str] = {
        r.get("duplicate_key", "")
        for r in patch_recs
        if r.get("queue_status") in ("pending", "archived")
        or r.get("plan_status") in ("pending", "archived")
    }

    candidates = [
        r for r in commit_recs
        if r.get("commit_status") == "pending"
        and r.get("commit_ready") is True
    ]

    promoted  = 0
    dup_count = 0

    for rec in candidates:
        dup_key  = rec.get("duplicate_key", "")
        agent    = rec.get("target_agent", "")
        ftype    = rec.get("feedback_type", "")
        r_label  = rec.get("reserve_label", "LOW")
        r_score  = rec.get("reserve_priority_score", 0.0)
        priority = _LABEL_TO_PRIORITY.get(r_label, "LOW")
        p_change = _proposed_change(rec)
        a_key    = _agent_key(agent)
        p_path   = _patch_path(agent)
        p_scope  = "single_agent" if agent.strip() else "global"

        patch_rec = {
            "planned_at":       _now_jst(),
            "source":           "reinject_commit",
            "source_committed_at": rec.get("committed_at", ""),
            "target_agent":     agent,
            "improvement_type": "prompt_fix",
            "priority":         priority,
            "priority_score":   r_score,
            "execution_order":  1,
            "duplicate_key":    dup_key,
            "plan_status":      "pending",
            "plan_from":        "ceo_reinject_patch_commit_queue",
            "target_config":    "config/agent_directives.json",
            "patch_mode":       "upsert_agent_directive",
            "patch_path":       p_path,
            "agent_key":        a_key,
            "before_value":     "",
            "after_value":      p_change,
            "diff_preview":     f"BEFORE: \nAFTER:  {p_change}",
            "backup_required":  True,
            "apply_ready":      True,
            "execution_scope":  "single_config_single_key",
            "execution_blocked": True,
            "write_scope":      "queue_only",
            "ceo_judgment":     "ミュウツーCEO patch_plan再投入",
        }

        if dup_key in existing_patch_dup_keys:
            dup_count += 1
            _append_jsonl(COMMIT_HISTORY_PATH, {
                **rec,
                "commit_status": "patch_plan_duplicate",
                "reason": f"同一 duplicate_key が patch_plan_queue(reinject_commit) に存在: {dup_key}",
            })
            continue

        existing_patch_dup_keys.add(dup_key)
        _append_jsonl(PATCH_PLAN_QUEUE_PATH, patch_rec)
        promoted += 1

    return {"promoted": promoted, "dup": dup_count}


# ────────────────────────────────────────────
# 統計
# ────────────────────────────────────────────

def get_reinject_commit_stats() -> dict:
    commit_recs = _load_jsonl(COMMIT_QUEUE_PATH)
    pending     = [r for r in commit_recs if r.get("commit_status") == "pending"]

    sorted_p = sorted(pending, key=lambda r: (int(r.get("reserve_order", 999)), -float(r.get("reserve_priority_score", 0))))
    top1   = sorted_p[0] if sorted_p else {}
    latest = pending[-1] if pending  else {}

    # patch_plan に reinject_commit source で入ったレコード数
    patch_recs = _load_jsonl(PATCH_PLAN_QUEUE_PATH)
    promoted_count = sum(1 for r in patch_recs if r.get("source") == "reinject_commit")
    dup_count      = sum(
        1 for r in _load_jsonl(COMMIT_HISTORY_PATH)
        if r.get("commit_status") in ("commit_duplicate", "patch_plan_duplicate")
    )

    return {
        "reinject_commit_pending_count":        len(pending),
        "reinject_commit_latest_agent":          latest.get("target_agent", "—"),
        "reinject_commit_latest_label":          latest.get("reserve_label", "—"),
        "reinject_commit_latest_order":          latest.get("reserve_order", 0),
        "reinject_commit_top1_agent":            top1.get("target_agent", "—"),
        "reinject_commit_top1_score":            top1.get("reserve_priority_score", 0.0),
        "reinject_commit_patch_plan_promoted_count": promoted_count,
        "reinject_commit_duplicate_count":       dup_count,
    }


# ────────────────────────────────────────────
# 統合実行
# ────────────────────────────────────────────

def run_reinject_commit_cycle() -> dict:
    commit_result  = build_commit_queue()
    promote_result = promote_to_patch_plan()
    return {"commit": commit_result, "patch_plan": promote_result}
