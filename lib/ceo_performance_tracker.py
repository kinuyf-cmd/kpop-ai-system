#!/usr/bin/env python3
"""
ceo_performance_tracker.py — CEO改善ループ 実行結果追跡・評価・フィードバック v1.0
CEO: ミュウツー / オーナー: 人間（閲覧専用）

【役割】
  config_apply_result → agent_execution_result
                      → performance_evaluation
                      → feedback_loop
                      → improvement_queue（再連携）

【制約】
  - 読み取りは pipeline.jsonl + agent_metrics.json + logs のみ
  - config 以外への書き込み禁止
  - LLM 判断なし / 完全ルールベース
  - 実行ログのみ参照、記事・pipeline本体・WP/APIは触らない
"""

import hashlib
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).parent.parent
JST  = timezone(timedelta(hours=9))

# ── パス定義 ─────────────────────────────────────────────────
PIPELINE_LOG_PATH        = BASE / "logs" / "pipeline.jsonl"
AGENT_METRICS_PATH       = BASE / "agent_metrics.json"
APPLY_RESULT_PATH        = BASE / "logs" / "ceo_config_apply_result_queue.jsonl"

EXEC_RESULT_QUEUE_PATH   = BASE / "logs" / "ceo_agent_execution_result_queue.jsonl"
EXEC_RESULT_HIST_PATH    = BASE / "logs" / "ceo_agent_execution_result_history.jsonl"
PERF_EVAL_QUEUE_PATH     = BASE / "logs" / "ceo_performance_evaluation_queue.jsonl"
PERF_EVAL_HIST_PATH      = BASE / "logs" / "ceo_performance_evaluation_history.jsonl"
FEEDBACK_QUEUE_PATH      = BASE / "logs" / "ceo_feedback_loop_queue.jsonl"
FEEDBACK_HIST_PATH       = BASE / "logs" / "ceo_feedback_loop_history.jsonl"
IMPROVEMENT_QUEUE_PATH   = BASE / "logs" / "ceo_improvement_queue.jsonl"
IMPROVEMENT_HIST_PATH    = BASE / "logs" / "ceo_improvement_history.jsonl"

# ── 評価定数 ─────────────────────────────────────────────────
_IMPROVE_THRESHOLD       = 0.05   # success_rate 改善と判定する delta
_DEGRADE_THRESHOLD       = -0.03  # success_rate 悪化と判定する delta
_WINDOW_RECENT           = 10     # 評価に使う直近 N 件のログレコード
_MAX_HINT_LEN            = 300

# ── ステータス正規化 ─────────────────────────────────────────
_SUCCESS_STATUSES = {"ok", "approved", "PASS"}
_FAIL_STATUSES    = {"error", "rejected", "HARD_FAIL", "hard_fail", "ERROR"}
_SKIP_STATUSES    = {"skipped", ""}


def _now_jst() -> str:
    return datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S JST")


def _load_jsonl(path: Path) -> list:
    if not path.exists():
        return []
    records = []
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
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


def _config_version_hash() -> str:
    """config/agent_directives.json の SHA256 先頭8桁"""
    cfg = BASE / "config" / "agent_directives.json"
    if not cfg.exists():
        return "no_config"
    try:
        return hashlib.sha256(cfg.read_bytes()).hexdigest()[:8]
    except Exception:
        return "hash_err"


# ── pipeline.jsonl からエージェントの実行レコードを抽出 ─────────

def _get_pipeline_records_for_agent(agent_id: str, limit: int = _WINDOW_RECENT) -> list:
    """
    pipeline.jsonl から agent_id(step名) の直近 limit 件を返す。
    """
    if not PIPELINE_LOG_PATH.exists():
        return []
    recs = []
    try:
        with PIPELINE_LOG_PATH.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        r = json.loads(line)
                        if r.get("step") == agent_id:
                            recs.append(r)
                    except json.JSONDecodeError:
                        pass
    except Exception:
        pass
    return recs[-limit:]


def _agent_id_from_ja(name_ja: str) -> str:
    """カタカナ名 → pipeline.jsonl の step 名に変換"""
    _MAP = {
        "バタフリー": "butterfree",
        "X投稿B":     "x_post_b",
        "X投稿":      "x_post",
        "サーナイト":  "gardevoir_hook_critic",
        "カイリュー":  "カイリュー",
        "アルセウス":  "arceus",
        "WP投稿":     "wordpress_post",
        "デオキシス":  "deoxys",
        "メタモン":    "metamon",
        "イーブイ":    "eevee",
        "ジラーチ":    "jirachi",
        "ミュウツー":  "mewtwo",
        "ラプラス":    "lapras",
        "ミミッキュ":  "mimikyu",
        "ソーナンス":  "wobbuffet",
        "フシギバナ":  "venusaur",
        "フーディン":  "alakazam",
        "ゲンガー":    "gengar",
        "ペルシアン":  "persian",
        "サンダー":    "zapdos",
    }
    return _MAP.get(name_ja, name_ja.lower())


def _is_exec_result_duplicate(execution_id: str, target_agent: str) -> bool:
    for r in _load_jsonl(EXEC_RESULT_QUEUE_PATH):
        if r.get("execution_id") == execution_id and r.get("target_agent") == target_agent:
            return True
    return False


def _is_perf_eval_duplicate(target_agent: str, config_hash: str) -> bool:
    for r in _load_jsonl(PERF_EVAL_QUEUE_PATH):
        if r.get("target_agent") == target_agent and r.get("config_version_hash") == config_hash:
            return True
    return False


def _is_feedback_duplicate(target_agent: str, config_hash: str) -> bool:
    for r in _load_jsonl(FEEDBACK_QUEUE_PATH):
        if r.get("target_agent") == target_agent and r.get("config_version_hash") == config_hash:
            return True
    return False


# ─────────────────────────────────────────────────────────────
# フェーズ1: config_apply_result → agent_execution_result_queue
# ─────────────────────────────────────────────────────────────

def collect_agent_execution_results() -> dict:
    """
    config_apply_result の applied 候補ごとに pipeline.jsonl を参照し、
    直近実行結果を agent_execution_result_queue に記録する。
    """
    now_str   = _now_jst()
    apply_recs = [r for r in _load_jsonl(APPLY_RESULT_PATH)
                  if r.get("result_status") == "applied"]

    collected         = 0
    skipped_duplicate = 0
    skipped_no_data   = 0

    EXEC_RESULT_QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    EXEC_RESULT_HIST_PATH.parent.mkdir(parents=True, exist_ok=True)

    config_hash = _config_version_hash()

    processed_agents = set()
    for ar in apply_recs:
        target_agent = ar.get("target_agent", "")
        if not target_agent or target_agent in processed_agents:
            continue
        processed_agents.add(target_agent)

        agent_id  = _agent_id_from_ja(target_agent)
        pipe_recs = _get_pipeline_records_for_agent(agent_id, _WINDOW_RECENT)

        if not pipe_recs:
            skipped_no_data += 1
            continue

        for pr in pipe_recs:
            run_id     = pr.get("run_id", "")
            timestamp  = pr.get("timestamp", "")
            raw_status = pr.get("status", "")
            message    = pr.get("message", "")
            size_bytes = pr.get("size_bytes", 0)

            execution_id = f"{agent_id}_{run_id}"

            if _is_exec_result_duplicate(execution_id, target_agent):
                skipped_duplicate += 1
                continue

            norm_status  = "success" if raw_status in _SUCCESS_STATUSES else "fail"
            error_type   = raw_status if raw_status in _FAIL_STATUSES else ""
            latency_hint = round(size_bytes / 1000.0, 3) if size_bytes else 0.0

            rec = {
                "executed_at":          now_str,
                "pipeline_timestamp":   timestamp,
                "target_agent":         target_agent,
                "execution_id":         execution_id,
                "run_id":               run_id,
                "input":                f"pipeline step: {agent_id}",
                "output":               message or f"size={size_bytes}bytes",
                "status":               norm_status,
                "raw_status":           raw_status,
                "latency":              latency_hint,
                "error_type":           error_type,
                "config_version_hash":  config_hash,
                "source_config_apply":  ar.get("applied_at", ""),
                "ceo_judgment":         "ミュウツーCEO実行結果観測",
            }
            with EXEC_RESULT_QUEUE_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            collected += 1

    return {
        "collected":          collected,
        "skipped_duplicate":  skipped_duplicate,
        "skipped_no_data":    skipped_no_data,
    }


def get_exec_result_stats() -> dict:
    records  = _load_jsonl(EXEC_RESULT_QUEUE_PATH)
    success  = [r for r in records if r.get("status") == "success"]
    fail     = [r for r in records if r.get("status") == "fail"]
    agents   = list(dict.fromkeys(r.get("target_agent", "") for r in records))
    latest   = records[-1] if records else {}
    return {
        "total":          len(records),
        "success":        len(success),
        "fail":           len(fail),
        "agents_tracked": agents,
        "latest_agent":   latest.get("target_agent", ""),
        "latest_status":  latest.get("status", ""),
        "latest_run_id":  latest.get("run_id", ""),
    }


# ─────────────────────────────────────────────────────────────
# フェーズ2: agent_execution_result → performance_evaluation_queue
# ─────────────────────────────────────────────────────────────

def evaluate_performance() -> dict:
    """
    agent_execution_result_queue と agent_metrics.json を使い、
    config 適用前後の成功率変化を評価する。
    """
    now_str     = _now_jst()
    exec_recs   = _load_jsonl(EXEC_RESULT_QUEUE_PATH)
    metrics     = _load_json_safe(AGENT_METRICS_PATH)
    config_hash = _config_version_hash()

    agents_to_eval = list(dict.fromkeys(r.get("target_agent", "") for r in exec_recs if r.get("target_agent")))

    evaluated         = 0
    skipped_duplicate = 0

    PERF_EVAL_QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PERF_EVAL_HIST_PATH.parent.mkdir(parents=True, exist_ok=True)

    for target_agent in agents_to_eval:
        if _is_perf_eval_duplicate(target_agent, config_hash):
            skipped_duplicate += 1
            continue

        # 当該 agent の実行結果（直近 _WINDOW_RECENT 件）
        ag_recs  = [r for r in exec_recs if r.get("target_agent") == target_agent][-_WINDOW_RECENT:]
        total    = len(ag_recs)
        if total == 0:
            continue

        success_n   = sum(1 for r in ag_recs if r.get("status") == "success")
        fail_n      = total - success_n
        hard_fail_n = sum(1 for r in ag_recs if r.get("raw_status") in ("HARD_FAIL", "hard_fail"))
        success_rate = round(success_n / total, 4)
        fail_rate    = round(fail_n    / total, 4)
        hard_fail_rate = round(hard_fail_n / total, 4)
        latency_avg  = round(sum(r.get("latency", 0.0) for r in ag_recs) / total, 3)

        # agent_metrics.json からの baseline success_rate
        agent_id  = _agent_id_from_ja(target_agent)
        am_agents = metrics.get("agents", {})
        baseline  = None
        for aid, v in am_agents.items():
            if aid == agent_id or v.get("name_ja") == target_agent:
                baseline = v.get("success_rate")
                break

        # delta 計算（baseline があれば）
        if baseline is not None:
            delta = round(success_rate - baseline, 4)
        else:
            delta = 0.0

        # 評価判定（完全ルールベース）
        if delta >= _IMPROVE_THRESHOLD:
            evaluation_result = "improved"
            perf_delta_str    = f"+{delta:.1%}"
        elif delta <= _DEGRADE_THRESHOLD:
            evaluation_result = "degraded"
            perf_delta_str    = f"{delta:.1%}"
        else:
            evaluation_result = "no_change"
            perf_delta_str    = f"{delta:+.1%}"

        eval_rec = {
            "evaluated_at":        now_str,
            "target_agent":        target_agent,
            "agent_id":            agent_id,
            "config_version_hash": config_hash,
            "window_size":         total,
            "success_count":       success_n,
            "fail_count":          fail_n,
            "hard_fail_count":     hard_fail_n,
            "success_rate":        success_rate,
            "fail_rate":           fail_rate,
            "hard_fail_rate":      hard_fail_rate,
            "latency_avg":         latency_avg,
            "baseline_success_rate": baseline if baseline is not None else "N/A",
            "performance_delta":   perf_delta_str,
            "evaluation_result":   evaluation_result,
            "ceo_judgment":        "ミュウツーCEO性能評価",
        }
        with PERF_EVAL_QUEUE_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(eval_rec, ensure_ascii=False) + "\n")
        evaluated += 1

    return {"evaluated": evaluated, "skipped_duplicate": skipped_duplicate}


def get_perf_eval_stats() -> dict:
    records   = _load_jsonl(PERF_EVAL_QUEUE_PATH)
    improved  = [r for r in records if r.get("evaluation_result") == "improved"]
    no_change = [r for r in records if r.get("evaluation_result") == "no_change"]
    degraded  = [r for r in records if r.get("evaluation_result") == "degraded"]
    latest    = records[-1] if records else {}
    return {
        "total":          len(records),
        "improved":       len(improved),
        "no_change":      len(no_change),
        "degraded":       len(degraded),
        "latest_agent":   latest.get("target_agent", ""),
        "latest_result":  latest.get("evaluation_result", ""),
        "latest_delta":   latest.get("performance_delta", ""),
    }


# ─────────────────────────────────────────────────────────────
# フェーズ3: performance_evaluation → feedback_loop_queue
# ─────────────────────────────────────────────────────────────

_FEEDBACK_TYPE_MAP = {
    "improved":  "keep",
    "no_change": "minor_adjust",
    "degraded":  "urgent_fix",
}
_FEEDBACK_PRIORITY_MAP = {
    "improved":  "LOW",
    "no_change": "MEDIUM",
    "degraded":  "HIGH",
}
_FEEDBACK_HINT_MAP = {
    "improved": (
        "成功率が改善されました。現在の directive を維持し、次サイクルも同様の方針で継続してください。"
    ),
    "no_change": (
        "成功率に有意な変化なし。directive の適用範囲または具体性を見直し、"
        "出力フォーマット指定をより明確にする微調整を検討してください。"
    ),
    "degraded": (
        "成功率が低下しました。直前の config 変更をロールバックし、"
        "エラーパターンを pipeline.jsonl で再分析してから再計画してください。"
    ),
}


def generate_feedback_loop() -> dict:
    """
    performance_evaluation_queue の最新評価から feedback_loop_queue を生成する。
    """
    now_str     = _now_jst()
    eval_recs   = _load_jsonl(PERF_EVAL_QUEUE_PATH)
    config_hash = _config_version_hash()

    # エージェントごとに最新評価1件を使う
    latest_by_agent: dict = {}
    for r in eval_recs:
        ta = r.get("target_agent", "")
        if ta:
            latest_by_agent[ta] = r

    generated         = 0
    skipped_duplicate = 0

    FEEDBACK_QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    FEEDBACK_HIST_PATH.parent.mkdir(parents=True, exist_ok=True)

    for target_agent, er in latest_by_agent.items():
        if _is_feedback_duplicate(target_agent, config_hash):
            skipped_duplicate += 1
            continue

        eval_result   = er.get("evaluation_result", "no_change")
        feedback_type = _FEEDBACK_TYPE_MAP.get(eval_result, "minor_adjust")
        priority      = _FEEDBACK_PRIORITY_MAP.get(eval_result, "MEDIUM")
        hint          = _FEEDBACK_HINT_MAP.get(eval_result, "")

        # エラー率情報を hint に補足
        if er.get("fail_rate", 0) > 0:
            hint = f"[fail_rate={er['fail_rate']:.1%} / hard_fail={er.get('hard_fail_rate',0):.1%}] " + hint
        hint = hint[:_MAX_HINT_LEN]

        fb_rec = {
            "feedback_at":          now_str,
            "target_agent":         target_agent,
            "agent_id":             er.get("agent_id", ""),
            "config_version_hash":  config_hash,
            "evaluation_result":    eval_result,
            "feedback_type":        feedback_type,
            "next_improvement_hint": hint,
            "priority":             priority,
            "success_rate":         er.get("success_rate", 0.0),
            "performance_delta":    er.get("performance_delta", ""),
            "feedback_status":      "pending",
            "ceo_judgment":         "ミュウツーCEO次改善指示",
        }
        with FEEDBACK_QUEUE_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(fb_rec, ensure_ascii=False) + "\n")
        generated += 1

    return {"generated": generated, "skipped_duplicate": skipped_duplicate}


def get_feedback_stats() -> dict:
    records   = _load_jsonl(FEEDBACK_QUEUE_PATH)
    keep      = [r for r in records if r.get("feedback_type") == "keep"]
    adjust    = [r for r in records if r.get("feedback_type") == "minor_adjust"]
    fix       = [r for r in records if r.get("feedback_type") == "urgent_fix"]
    latest    = records[-1] if records else {}
    return {
        "total":          len(records),
        "keep":           len(keep),
        "minor_adjust":   len(adjust),
        "urgent_fix":     len(fix),
        "latest_agent":   latest.get("target_agent", ""),
        "latest_type":    latest.get("feedback_type", ""),
        "latest_priority": latest.get("priority", ""),
        "latest_delta":   latest.get("performance_delta", ""),
    }


# ─────────────────────────────────────────────────────────────
# フェーズ4: feedback_loop → improvement_queue（ループ再連携）
# ─────────────────────────────────────────────────────────────

def feedback_to_improvement_queue() -> dict:
    """
    feedback_loop_queue の pending レコードを improvement_queue に投入する。
    feedback_type が keep のものは投入しない（改善不要のため）。
    """
    now_str   = _now_jst()
    fb_recs   = [r for r in _load_jsonl(FEEDBACK_QUEUE_PATH)
                 if r.get("feedback_status") == "pending"
                 and r.get("feedback_type") != "keep"]

    enqueued          = 0
    skipped_duplicate = 0
    skipped_keep      = 0

    # keep は数だけカウント
    skipped_keep = sum(1 for r in _load_jsonl(FEEDBACK_QUEUE_PATH)
                       if r.get("feedback_status") == "pending"
                       and r.get("feedback_type") == "keep")

    IMPROVEMENT_QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    IMPROVEMENT_HIST_PATH.parent.mkdir(parents=True, exist_ok=True)

    existing_impr = _load_jsonl(IMPROVEMENT_QUEUE_PATH)

    for fb in fb_recs:
        target_agent = fb.get("target_agent", "")
        hint         = fb.get("next_improvement_hint", "")
        priority     = fb.get("priority", "MEDIUM")
        fb_type      = fb.get("feedback_type", "minor_adjust")
        itype        = "prompt_fix"  # feedback からの再連携は常に prompt_fix

        # improvement_queue に同一エージェント×タイプの pending がすでにあれば skip
        dup = any(
            r.get("target_agent") == target_agent
            and r.get("improvement_type") == itype
            and r.get("status") == "pending"
            for r in existing_impr
        )
        if dup:
            skipped_duplicate += 1
            with IMPROVEMENT_HIST_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "generated_at":  now_str,
                    "target_agent":  target_agent,
                    "status":        "feedback_loop_duplicate",
                    "reason":        "improvement_queueに同エージェントのpending存在",
                }, ensure_ascii=False) + "\n")
            continue

        # improvement_queue レコード（既存の enqueue 形式に合わせる）
        impr_rec = {
            "generated_at":       now_str,
            "target_agent":       target_agent,
            "improvement_type":   itype,
            "proposed_change":    hint[:200],
            "priority":           priority,
            "status":             "pending",
            "source":             "feedback_loop",
            "feedback_type":      fb_type,
            "config_version_hash": fb.get("config_version_hash", ""),
            "execute_recommended": False,
            "recommendation_reason": f"feedback_loop: {fb_type}",
            "safety_class":       "REVIEW",
            "human_review_required": True,
            "ceo_judgment":       "ミュウツーCEOフィードバック再投入",
        }
        with IMPROVEMENT_QUEUE_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(impr_rec, ensure_ascii=False) + "\n")
        enqueued += 1

    return {
        "enqueued":          enqueued,
        "skipped_duplicate": skipped_duplicate,
        "skipped_keep":      skipped_keep,
    }


# ─────────────────────────────────────────────────────────────
# 統合実行
# ─────────────────────────────────────────────────────────────

def run_full_tracking_cycle() -> dict:
    """
    フェーズ1〜4を一括実行する。
    """
    r1 = collect_agent_execution_results()
    r2 = evaluate_performance()
    r3 = generate_feedback_loop()
    r4 = feedback_to_improvement_queue()
    return {
        "execution_result":   r1,
        "performance_eval":   r2,
        "feedback_loop":      r3,
        "improvement_reinject": r4,
    }


if __name__ == "__main__":
    result = run_full_tracking_cycle()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("exec_result_stats:", get_exec_result_stats())
    print("perf_eval_stats:",   get_perf_eval_stats())
    print("feedback_stats:",    get_feedback_stats())
