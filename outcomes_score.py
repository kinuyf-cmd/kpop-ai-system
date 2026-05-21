#!/usr/bin/env python3
"""outcomes_score.py — M10 P-2 Outcomes 自動採点ループ

orchestration-leader SKILL §5 の Outcomes 機能を実装。
各エージェントの直近実行結果(jsonl ログ)をルーブリックで採点し、
orchestration_state.json の outcomes_scores に書き込む。

採点対象:
- qa_test_log.jsonl       : passed_rate(passed / total)
- red_team_log.jsonl      : detection 件数 + 重大度配分
- blue_team_log.jsonl     : auto_repair_rate + queue 件数
- audit_log.jsonl         : violation 件数
- skill_metrics.jsonl     : 集計済 skill 数

各エージェントのスコア 0-1 を出して 100point-rubric-judge の入力に使う。

用途:
    python3 outcomes_score.py                # 全エージェント
    python3 outcomes_score.py --suite morning
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

LOG_DIR = Path.home() / ".kpop_recovery"
STATE_FILE = LOG_DIR / "orchestration_state.json"


def now_iso() -> str:
    return datetime.now(timezone(timedelta(hours=9))).isoformat()


def load_jsonl(path: Path, limit: int = 100) -> list[dict]:
    """直近 limit 行を読む"""
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    out = []
    for ln in lines[-limit:]:
        ln = ln.strip()
        if not ln:
            continue
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return out


def score_qa(records: list[dict]) -> dict:
    if not records:
        return {"score": 0.0, "reason": "no data", "count": 0}
    last = records[-1]
    total = last.get("total", 0)
    passed = last.get("passed", 0)
    if total == 0:
        return {"score": 0.0, "reason": "zero tests", "count": 0}
    rate = passed / total
    return {"score": round(rate, 3), "reason": f"{passed}/{total} passed (latest run)", "count": total}


def score_red(records: list[dict]) -> dict:
    if not records:
        return {"score": 1.0, "reason": "no detections (CLEAN)", "count": 0}
    last = records[-1]
    severities = last.get("severities", {}) if isinstance(last.get("severities"), dict) else {}
    crit = severities.get("CRITICAL", 0)
    high = severities.get("HIGH", 0)
    # CRITICAL/HIGH ゼロ = 高スコア
    if crit > 0:
        return {"score": 0.0, "reason": f"{crit} CRITICAL detected", "count": len(records)}
    if high > 0:
        return {"score": 0.5, "reason": f"{high} HIGH detected", "count": len(records)}
    return {"score": 0.9, "reason": "no CRITICAL/HIGH", "count": len(records)}


def score_blue(records: list[dict]) -> dict:
    if not records:
        return {"score": 0.5, "reason": "no repair activity", "count": 0}
    last = records[-1]
    auto = last.get("auto_repaired", 0)
    queue = last.get("queued", 0)
    total = auto + queue
    if total == 0:
        return {"score": 1.0, "reason": "nothing to repair", "count": 0}
    rate = auto / total
    return {"score": round(rate, 3), "reason": f"{auto}/{total} auto-repaired", "count": total}


def score_audit(records: list[dict]) -> dict:
    if not records:
        return {"score": 0.5, "reason": "no audit data", "count": 0}
    last = records[-1]
    violations = last.get("violations", 0)
    if violations == 0:
        return {"score": 1.0, "reason": "zero violations", "count": 0}
    return {"score": max(0.0, 1.0 - violations / 10), "reason": f"{violations} violations", "count": violations}


def score_skill_metrics(records: list[dict]) -> dict:
    if not records:
        return {"score": 0.0, "reason": "no metrics", "count": 0}
    # 直近スナップショットの skill 数
    skills = {r.get("skill_name") for r in records if r.get("skill_name")}
    return {"score": 1.0 if len(skills) >= 15 else round(len(skills) / 15, 2), "reason": f"{len(skills)} skills tracked", "count": len(skills)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", default="all")
    args = ap.parse_args()

    LOG_DIR.mkdir(exist_ok=True)
    scores = {
        "qa":            score_qa(load_jsonl(LOG_DIR / "qa_test_log.jsonl")),
        "red_team":      score_red(load_jsonl(LOG_DIR / "red_team_log.jsonl")),
        "blue_team":     score_blue(load_jsonl(LOG_DIR / "blue_team_log.jsonl")),
        "audit":         score_audit(load_jsonl(LOG_DIR / "audit_log.jsonl")),
        "skill_metrics": score_skill_metrics(load_jsonl(LOG_DIR / "skill_metrics.jsonl", limit=200)),
    }

    # 状態書き込み
    state = {}
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            state = {}
    state.setdefault("outcomes_scores", {})
    state["outcomes_scores"][args.suite] = {
        "timestamp": now_iso(),
        "scores": scores,
        "average": round(sum(s["score"] for s in scores.values()) / len(scores), 3),
    }
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))

    # 標準出力サマリ
    print("OUTCOMES SCORING")
    print(f"  suite     : {args.suite}")
    for name, s in scores.items():
        print(f"  {name:14s}: {s['score']:.3f}  {s['reason']}")
    avg = state["outcomes_scores"][args.suite]["average"]
    print(f"  AVERAGE   : {avg:.3f}")
    print(f"  state     : {STATE_FILE}")

    # 嘘の完了宣言検知: average < 0.5 で警告
    if avg < 0.5:
        print("  ⚠ low score (< 0.5): check agents", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
