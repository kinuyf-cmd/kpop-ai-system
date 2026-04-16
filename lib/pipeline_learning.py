#!/usr/bin/env python3
"""
pipeline_learning.py — パイプライン完走率・段階別失敗パターン集計

対象: kpop_pipeline.sh / kpop_strategy_pipeline.sh / kpop_chart_pipeline.sh
データ: logs/pipeline.jsonl
出力:
  - logs/pipeline_learning.log: 7日間のstep別失敗率・完走率サマリー（時系列追記）
  - logs/pipeline_bottleneck.json: 失敗ステップランキング（週次レポートに組込）

用途:
  エージェント責務とパイプラインのどこで記事がボツになっているかを定量把握し、
  改善エンジンの次の打ち手を特定する。
"""
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
SRC = BASE / "logs" / "pipeline.jsonl"
LOG_OUT = BASE / "logs" / "pipeline_learning.log"
BOTTLENECK = BASE / "logs" / "pipeline_bottleneck.json"

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)
SINCE = NOW - timedelta(days=7)


def load_entries():
    if not SRC.exists():
        return []
    out = []
    for line in SRC.read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(line)
            ts = datetime.fromisoformat(d["timestamp"].replace("Z", "+00:00"))
            if ts >= SINCE:
                out.append(d)
        except Exception:
            continue
    return out


def aggregate(entries):
    runs = defaultdict(list)
    for e in entries:
        runs[e.get("run_id", "?")].append(e)

    step_total = Counter()
    step_fail = Counter()
    run_outcome = Counter()
    last_step_per_failed_run = Counter()
    failure_messages = Counter()

    for rid, events in runs.items():
        final = None
        for ev in events:
            step = ev.get("step", "?")
            status = (ev.get("status") or "").lower()
            step_total[step] += 1
            if status in ("error", "hard_fail", "blocked"):
                step_fail[step] += 1
                msg = (ev.get("message") or "")[:80]
                failure_messages[msg] += 1
            final = ev
        # run全体の最終判定
        last_status = (final.get("status") or "").lower() if final else ""
        if last_status in ("ok", "approved", "pass"):
            # persian/ok で終わるのが成功
            if final.get("step") in ("persian", "wordpress_post", "arceus"):
                run_outcome["complete"] += 1
            else:
                run_outcome["partial"] += 1
        else:
            run_outcome["failed"] += 1
            if final:
                last_step_per_failed_run[final.get("step", "?")] += 1

    return {
        "total_runs": len(runs),
        "outcomes": dict(run_outcome),
        "step_total": dict(step_total),
        "step_fail": dict(step_fail),
        "step_fail_rate": {
            s: round(100 * step_fail[s] / max(1, step_total[s]), 1)
            for s in step_total
        },
        "failed_at_last_step": dict(last_step_per_failed_run),
        "top_failure_messages": dict(failure_messages.most_common(10)),
    }


def main():
    entries = load_entries()
    if not entries:
        msg = f"[{NOW.isoformat()}] pipeline.jsonl に過去7日分のデータなし"
        LOG_OUT.parent.mkdir(parents=True, exist_ok=True)
        with LOG_OUT.open("a", encoding="utf-8") as f:
            f.write(msg + "\n")
        print(msg)
        return

    agg = aggregate(entries)

    lines = [f"[pipeline_learning] 期間 {SINCE.date()}〜{NOW.date()}"]
    lines.append(f"  総run数: {agg['total_runs']}")
    lines.append(f"  結果内訳: {agg['outcomes']}")
    complete = agg["outcomes"].get("complete", 0)
    rate = round(100 * complete / max(1, agg["total_runs"]), 1)
    lines.append(f"  完走率: {rate}%")
    # 失敗率TOP5のstep
    fails = sorted(agg["step_fail_rate"].items(), key=lambda x: -x[1])
    meaningful = [(s, r) for s, r in fails if agg["step_total"][s] >= 2]
    lines.append(f"  失敗率TOP5 (最低2回実行): " + ", ".join(f"{s}={r}%" for s, r in meaningful[:5]))
    if agg["failed_at_last_step"]:
        lines.append(f"  最終失敗ステップ分布: {agg['failed_at_last_step']}")
    if agg["top_failure_messages"]:
        lines.append("  頻出エラー:")
        for m, n in list(agg["top_failure_messages"].items())[:5]:
            lines.append(f"    - ({n}回) {m}")

    out = "\n".join(lines)
    LOG_OUT.parent.mkdir(parents=True, exist_ok=True)
    with LOG_OUT.open("a", encoding="utf-8") as f:
        f.write(f"[{NOW.isoformat()}]\n{out}\n")

    BOTTLENECK.write_text(json.dumps({
        "generated_at": NOW.isoformat(),
        "period_days": 7,
        **agg,
        "completion_rate": rate,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
