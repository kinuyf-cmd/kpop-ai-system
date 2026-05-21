#!/usr/bin/env python3
"""
ceo_post_apply_judge.py — apply後判定エンジン v1.0
CEO: ミュウツー / オーナー: 人間（閲覧専用）

【役割】
  apply_result + performance_evaluation を参照し、
  keep_monitoring / re_adjust_minor / rollback_recommended の3ラベルで分類する。

【判定条件（完全決定論）】
  improved かつ hard_fail_rate 低下 → keep_monitoring
  no_change                          → re_adjust_minor
  degraded または fail 増加 または hard_fail 増加 → rollback_recommended

【制約】
  - config への書き込みなし
  - rollback 自動実行なし
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

APPLY_RESULT_PATH        = LOGS / "ceo_apply_execute_result_queue.jsonl"
PERF_EVAL_QUEUE_PATH     = LOGS / "ceo_performance_evaluation_queue.jsonl"
EXEC_RESULT_QUEUE_PATH   = LOGS / "ceo_agent_execution_result_queue.jsonl"

POST_APPLY_JUDGE_QUEUE   = LOGS / "ceo_post_apply_judge_queue.jsonl"
POST_APPLY_JUDGE_HISTORY = LOGS / "ceo_post_apply_judge_history.jsonl"

JUDGE_LABELS = ("keep_monitoring", "re_adjust_minor", "rollback_recommended")


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


def _judge_label(perf_rec: dict | None, exec_result_rec: dict | None) -> tuple[str, str]:
    """
    Returns (label, reason).
    perf_rec: latest ceo_performance_evaluation_queue record for agent
    exec_result_rec: latest ceo_agent_execution_result_queue record for agent
    """
    if perf_rec is None and exec_result_rec is None:
        return "re_adjust_minor", "評価データなし（様子見）"

    # performance_evaluation から判定
    verdict = (perf_rec.get("verdict", "") if perf_rec else "")
    raw_delta = perf_rec.get("performance_delta", 0) if perf_rec else 0
    try:
        # '+0.0%' / '-3.2%' / 0.05 など混在に対応
        delta = float(str(raw_delta).rstrip("%")) / (100.0 if "%" in str(raw_delta) else 1.0)
    except (ValueError, TypeError):
        delta = 0.0

    if verdict == "improved" or delta >= 0.05:
        # hard_fail 増加チェック
        try:
            hfd_raw = perf_rec.get("hard_fail_delta", 0) if perf_rec else 0
            hard_fail_delta = float(str(hfd_raw).rstrip("%")) / (100.0 if "%" in str(hfd_raw) else 1.0)
        except (ValueError, TypeError):
            hard_fail_delta = 0.0
        if hard_fail_delta > 0:
            return "rollback_recommended", f"改善あり({delta:+.3f})だが hard_fail 増加({hard_fail_delta:+.3f})"
        return "keep_monitoring", f"改善確認(delta={delta:+.3f})"

    if verdict in ("degraded", "critical") or delta <= -0.03:
        return "rollback_recommended", f"性能悪化(delta={delta:+.3f})"

    # exec_result から追加確認
    if exec_result_rec:
        hard_fail_count = int(exec_result_rec.get("hard_fail_count", 0))
        success_rate    = float(exec_result_rec.get("success_rate_recent", -1))
        if hard_fail_count > 0:
            return "rollback_recommended", f"hard_fail 発生({hard_fail_count}件)"
        if success_rate >= 0 and success_rate < 0.5:
            return "rollback_recommended", f"直近成功率 {success_rate:.1%} < 50%"

    return "re_adjust_minor", f"変化なし(delta={delta:+.3f})、微調整推奨"


# ════════════════════════════════════════════════════════════════════
# メイン判定関数
# ════════════════════════════════════════════════════════════════════

def run_post_apply_judge() -> dict:
    """
    apply_execute_result_queue の applied レコードを対象に判定し
    post_apply_judge_queue に記録する。
    """
    apply_results = [r for r in _load_jsonl(APPLY_RESULT_PATH)
                     if r.get("result_status") == "applied"]
    perf_evals    = _load_jsonl(PERF_EVAL_QUEUE_PATH)
    exec_results  = _load_jsonl(EXEC_RESULT_QUEUE_PATH)

    # 既存 judge 済みの duplicate_key セット
    existing = _load_jsonl(POST_APPLY_JUDGE_QUEUE)
    existing_keys = {r.get("duplicate_key", "") for r in existing
                     if r.get("judge_label") in JUDGE_LABELS}

    judged     = 0
    dup_count  = 0

    for ar in apply_results:
        dup_key = ar.get("duplicate_key", "")
        ta      = ar.get("target_agent", "—")

        if dup_key in existing_keys:
            dup_count += 1
            continue

        # 該当エージェントの最新評価・実行結果を取得
        agent_perf = [r for r in perf_evals
                      if r.get("target_agent") == ta or r.get("agent_id") == ta]
        agent_exec = [r for r in exec_results
                      if r.get("target_agent") == ta or r.get("agent_id") == ta]

        perf_rec  = agent_perf[-1] if agent_perf else None
        exec_rec  = agent_exec[-1] if agent_exec else None

        label, reason = _judge_label(perf_rec, exec_rec)
        existing_keys.add(dup_key)

        rec = {
            "judged_at":       _now_jst(),
            "target_agent":    ta,
            "duplicate_key":   dup_key,
            "agent_key":       ar.get("agent_key", ""),
            "patch_path":      ar.get("patch_path", ""),
            "config_hash":     ar.get("config_hash", ""),
            "backup_path":     ar.get("backup_path", ""),
            "judge_label":     label,
            "judge_reason":    reason,
            "performance_delta": (lambda v: float(str(v).rstrip("%")) / (100.0 if "%" in str(v) else 1.0) if v else 0.0)(perf_rec.get("performance_delta", 0) if perf_rec else 0),
            "verdict":          (perf_rec.get("verdict", "unknown") if perf_rec else "unknown"),
            "source_applied_at": ar.get("applied_at", ""),
            "source_queue":    "ceo_apply_execute_result_queue",
            "ceo_judgment":    "ミュウツーCEO apply後判定",
        }
        _append_jsonl(POST_APPLY_JUDGE_QUEUE, rec)
        _append_jsonl(POST_APPLY_JUDGE_HISTORY, {
            "processed_at": _now_jst(),
            "target_agent": ta,
            "duplicate_key": dup_key,
            "status": "judged",
            "judge_label": label,
            "reason": reason,
            "source_queue": "ceo_apply_execute_result_queue",
            "ceo_judgment": "ミュウツーCEO apply後判定",
        })
        judged += 1

    recs = _load_jsonl(POST_APPLY_JUDGE_QUEUE)
    keep  = [r for r in recs if r.get("judge_label") == "keep_monitoring"]
    adj   = [r for r in recs if r.get("judge_label") == "re_adjust_minor"]
    roll  = [r for r in recs if r.get("judge_label") == "rollback_recommended"]

    return {
        "judged":    judged,
        "dup":       dup_count,
        "keep_monitoring":      len(keep),
        "re_adjust_minor":      len(adj),
        "rollback_recommended": len(roll),
    }


def get_post_apply_judge_stats() -> dict:
    recs  = _load_jsonl(POST_APPLY_JUDGE_QUEUE)
    keep  = [r for r in recs if r.get("judge_label") == "keep_monitoring"]
    adj   = [r for r in recs if r.get("judge_label") == "re_adjust_minor"]
    roll  = [r for r in recs if r.get("judge_label") == "rollback_recommended"]
    latest = recs[-1] if recs else {}
    return {
        "post_apply_judge_keep_count":      len(keep),
        "post_apply_judge_readjust_count":  len(adj),
        "post_apply_judge_rollback_count":  len(roll),
        "post_apply_judge_total":           len(recs),
        "post_apply_judge_latest_agent":    latest.get("target_agent", "—"),
        "post_apply_judge_latest_label":    latest.get("judge_label", "—"),
        "post_apply_judge_latest_reason":   latest.get("judge_reason", "—"),
    }


if __name__ == "__main__":
    import json as _json
    result = run_post_apply_judge()
    print(_json.dumps(result, ensure_ascii=False, indent=2))
    print(_json.dumps(get_post_apply_judge_stats(), ensure_ascii=False, indent=2))
