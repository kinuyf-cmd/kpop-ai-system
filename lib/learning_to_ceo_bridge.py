#!/usr/bin/env python3
"""
learning_to_ceo_bridge.py — 学習結果を CEO 提案キューに投入する橋渡し

入力:
  logs/thumb_bad_phrase_candidates.json
  logs/pipeline_bottleneck.json
  logs/gardevoir_hard_fail_patterns.json
  logs/timeslot_ranking.json

出力:
  logs/ceo_action_queue.jsonl  （既存のCEO自律改善パイプラインの入口）

動作:
  - 閾値を超える「有意な異常」を検出したときのみエントリを投入
  - 重複防止: 同日同 action_type+target_agent は追加しない
  - 既存 CEO スキーマ（action_type/target_agent/priority/reason/expected_effect/execute_recommended）に準拠
"""
import json
from datetime import datetime, date, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"
QUEUE = LOGS / "ceo_action_queue.jsonl"

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)
TODAY_ISO = date.today().isoformat()


def _load_json(p: Path) -> dict:
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _existing_today_keys() -> set:
    """本日既にqueueに入った (action_type, target_agent) の組を返す（重複防止）"""
    if not QUEUE.exists():
        return set()
    seen = set()
    for line in QUEUE.read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(line)
        except Exception:
            continue
        ts = d.get("generated_at", "")
        if not ts.startswith(TODAY_ISO):
            continue
        seen.add((d.get("action_type"), d.get("target_agent")))
    return seen


def _enqueue(entry: dict, seen: set) -> str:
    key = (entry["action_type"], entry["target_agent"])
    if key in seen:
        return "skipped_duplicate"
    entry["generated_at"] = NOW.isoformat()
    entry.setdefault("status", "pending")
    entry.setdefault("source", "learning_bridge")
    with QUEUE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    seen.add(key)
    return "queued"


def bridge_thumb(seen) -> list:
    data = _load_json(LOGS / "thumb_bad_phrase_candidates.json")
    m = data.get("metrics", {})
    cands = data.get("candidates", [])
    out = []
    # try1 pass率が低すぎる
    rate = m.get("try1_pass_rate", 100)
    if rate < 50:
        out.append(_enqueue({
            "priority": "MEDIUM",
            "action_type": "tune_agent_prompt",
            "target_agent": "ライコウ",
            "target_log": "logs/thumb_copy_generation.jsonl",
            "target_metric": f"try1_pass_rate={rate}%",
            "reason": f"raikou_thumb の try1 pass率が {rate}% に低迷。10文字制約・禁則句の追加が必要",
            "expected_effect": "try1 で pass する比率を70%以上に引き上げ、再試行コスト削減",
            "execute_recommended": False,
        }, seen))
    # 未登録禁則句が5件以上溜まっている
    if len(cands) >= 5:
        kw = ", ".join(c["phrase"] for c in cands[:5])
        out.append(_enqueue({
            "priority": "LOW",
            "action_type": "extend_bad_phrase_list",
            "target_agent": "ライコウ",
            "target_log": "logs/thumb_bad_phrase_candidates.json",
            "target_metric": f"new_candidates={len(cands)}",
            "reason": f"低スコアで繰り返される未登録語尾句: {kw}",
            "expected_effect": "agents/raikou_thumb.md の禁則表への昇格により将来的 pass率向上",
            "execute_recommended": True,
        }, seen))
    return out


def bridge_pipeline(seen) -> list:
    data = _load_json(LOGS / "pipeline_bottleneck.json")
    out = []
    rate = data.get("completion_rate", 100)
    fail_rate = data.get("step_fail_rate", {})
    if rate < 50 and data.get("total_runs", 0) >= 10:
        out.append(_enqueue({
            "priority": "HIGH",
            "action_type": "inspect_pipeline_completion",
            "target_agent": "ミュウツー",
            "target_log": "logs/pipeline_bottleneck.json",
            "target_metric": f"completion_rate={rate}%",
            "reason": f"過去7日のパイプライン完走率 {rate}%。投稿停止が慢性化",
            "expected_effect": "失敗ステップ特定→改善で完走率を60%以上へ",
            "execute_recommended": False,
        }, seen))
    # 特定stepの失敗率が50%超
    agent_map = {
        "gardevoir_hook_critic": "ガルデヴォワール",
        "butterfree": "バタフリー",
        "metamon": "メタモン",
        "deoxys": "デオキシス",
        "eevee": "イーブイ",
        "arceus": "アルセウス",
        "persian": "ペルシアン",
        "jirachi": "ジラーチ",
        "lapras": "ラプラス",
        "mimikyu": "ミミッキュ",
    }
    for step, fr in fail_rate.items():
        total = data.get("step_total", {}).get(step, 0)
        if fr >= 50 and total >= 5 and step in agent_map:
            out.append(_enqueue({
                "priority": "HIGH" if fr >= 70 else "MEDIUM",
                "action_type": "inspect_agent_failure",
                "target_agent": agent_map[step],
                "target_log": "logs/pipeline.jsonl",
                "target_metric": f"fail_rate={fr}% ({total}回)",
                "reason": f"{step} の失敗率 {fr}% が7日間で慢性化",
                "expected_effect": "失敗要因排除で pipeline 完走率が復調",
                "execute_recommended": False,
            }, seen))
    return out


def bridge_gardevoir(seen) -> list:
    data = _load_json(LOGS / "gardevoir_hard_fail_patterns.json")
    out = []
    hf = data.get("hard_fail_count", 0)
    total = data.get("total_samples", 0)
    contamination = data.get("error_response_contamination", {})
    if total > 0 and hf / total > 0.4:
        out.append(_enqueue({
            "priority": "HIGH",
            "action_type": "tune_title_agents",
            "target_agent": "メタモン",
            "target_log": "logs/gardevoir_hard_fail_patterns.json",
            "target_metric": f"hard_fail_rate={round(100*hf/total,1)}%",
            "reason": f"gardevoir HARD_FAIL率 {round(100*hf/total,1)}% (計{hf}/{total})。タイトル刺さり不足が慢性化",
            "expected_effect": "metamon/deoxysプロンプト調整でHARD_FAILを20%以下に",
            "execute_recommended": False,
        }, seen))
    if contamination:
        kw = ", ".join(f"{k}({v})" for k, v in list(contamination.items())[:3])
        out.append(_enqueue({
            "priority": "HIGH",
            "action_type": "prompt_fix",
            "target_agent": "デオキシス",
            "target_log": "logs/gardevoir_hard_fail_patterns.json",
            "target_metric": f"contamination_count={sum(contamination.values())}",
            "reason": f"エージェント応答汚染検出: {kw}",
            "expected_effect": "sanitize_output.sh 拡張 or agent プロンプト強化で応答汚染を0へ",
            "execute_recommended": True,
        }, seen))
    return out


def bridge_timeslot(seen) -> list:
    data = _load_json(LOGS / "timeslot_ranking.json")
    out = []
    hours = data.get("hour_ranking", [])
    if len(hours) >= 5:
        # 最低PVの時間帯で投稿数が多い場合は枠入替候補
        weak = sorted(hours, key=lambda x: x["avg_pv"])[0]
        if weak["posts"] >= 3 and weak["avg_pv"] < 5:
            out.append(_enqueue({
                "priority": "LOW",
                "action_type": "review_schedule_slot",
                "target_agent": "ミュウツー",
                "target_log": "logs/timeslot_ranking.json",
                "target_metric": f"weak_hour={weak['hour']} avg_pv={weak['avg_pv']}",
                "reason": f"{weak['hour']}時枠の平均PVが{weak['avg_pv']}と低迷（{weak['posts']}投稿）",
                "expected_effect": "枠入替で全体PV底上げ",
                "execute_recommended": False,
            }, seen))
    return out


def main():
    seen = _existing_today_keys()
    all_results = []
    all_results.extend(bridge_thumb(seen))
    all_results.extend(bridge_pipeline(seen))
    all_results.extend(bridge_gardevoir(seen))
    all_results.extend(bridge_timeslot(seen))
    queued = [r for r in all_results if r == "queued"]
    skipped = [r for r in all_results if r == "skipped_duplicate"]
    print(f"[learning_to_ceo_bridge] {NOW.isoformat()} queued={len(queued)} skipped_duplicate={len(skipped)}")


if __name__ == "__main__":
    main()
