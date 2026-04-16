#!/usr/bin/env python3
"""
thumb_learning.py — サムネコピー学習集計（improvement_engine STEP 6.5）

集計元: logs/thumb_copy_generation.jsonl
出力先: logs/thumb_learning.log（improvement_engine.log にも STEP サマリを出力）
追加出力: logs/thumb_bad_phrase_candidates.json（週次で raikou_thumb.md への反映候補）

学習ルール:
  1. 直近 7 日の raikou_thumb 出力を集計
  2. pass率 / 平均スコア / 10文字超過率 を計測
  3. スコア < 60 のサンプルから頻出語尾句（N-gram）を抽出
  4. 既知の禁則句（agents/raikou_thumb.md）と照合し、未登録の bad 候補を提案
"""
import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOG_SRC = BASE / "logs" / "thumb_copy_generation.jsonl"
LOG_OUT = BASE / "logs" / "thumb_learning.log"
BAD_CAND_OUT = BASE / "logs" / "thumb_bad_phrase_candidates.json"
AGENT_MD = BASE / "agents" / "raikou_thumb.md"

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)
SINCE = NOW - timedelta(days=7)


def load_entries():
    if not LOG_SRC.exists():
        return []
    entries = []
    for line in LOG_SRC.read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(line)
        except Exception:
            continue
        try:
            ts = datetime.fromisoformat(d["ts"])
        except Exception:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=JST)
        if ts >= SINCE:
            d["_ts"] = ts
            entries.append(d)
    return entries


def extract_suffix_ngrams(text: str, n_range=(3, 5)) -> list[str]:
    """2行の末尾 n-gram（3〜5文字）を抽出。汎用語尾句の候補源。"""
    out = []
    for line in text.split("\n"):
        line = line.strip()
        if len(line) < 3:
            continue
        for n in range(n_range[0], min(n_range[1], len(line)) + 1):
            out.append(line[-n:])
    return out


def known_bad_phrases() -> set[str]:
    """agents/raikou_thumb.md から禁則語尾句を抽出（テーブル内の NG 出力列）"""
    bad = set()
    if not AGENT_MD.exists():
        return bad
    txt = AGENT_MD.read_text(encoding="utf-8")
    # 「NG出力」「悪い例」テーブル行から抽出（粗め）
    for m in re.finditer(r'\|\s*`?([^`|]+?)の?(衝撃|真相|覚悟|全貌|完全版|秘密|裏側|全て|本気が止まらない)`?', txt):
        bad.add(m.group(2))
    for w in ["の衝撃", "の真相", "が示す覚悟", "を徹底", "が止まらない", "の全貌",
              "の真実", "の裏側", "の秘密", "完全版", "まとめ", "完全ガイド"]:
        bad.add(w)
    return bad


def main():
    entries = load_entries()
    raikou = [e for e in entries if e.get("agent") == "raikou_thumb"]
    if not raikou:
        summary = "raikou_thumb 出力なし（過去7日）"
        LOG_OUT.parent.mkdir(parents=True, exist_ok=True)
        with LOG_OUT.open("a", encoding="utf-8") as f:
            f.write(f"[{NOW.isoformat()}] {summary}\n")
        print(summary)
        return

    t1 = [e for e in raikou if e.get("attempt", 1) == 1]
    passed = [e for e in t1 if e.get("pass") and not e.get("overlong")]
    overlong = [e for e in t1 if e.get("overlong")]
    scores = [e.get("score", 0) for e in t1]
    avg = sum(scores) / len(scores) if scores else 0

    low = [e for e in raikou if (e.get("score", 0) < 60) and e.get("text")]
    known = known_bad_phrases()
    suffix_counter: Counter = Counter()
    for e in low:
        for ng in extract_suffix_ngrams(e["text"]):
            suffix_counter[ng] += 1
    # 5回以上出現かつ未登録の suffix を bad 候補に
    candidates = [
        {"phrase": ng, "count": c}
        for ng, c in suffix_counter.most_common(40)
        if c >= 5 and ng not in known and len(ng) >= 3
    ]

    summary_lines = [
        f"[thumb_learning] 期間={SINCE.date()}〜{NOW.date()}",
        f"  raikou_thumb 試行総数: {len(raikou)}（うち try1 {len(t1)}）",
        f"  try1 pass率: {len(passed)}/{len(t1)} = {100 * len(passed) // max(1, len(t1))}%",
        f"  10文字超過率: {len(overlong)}/{len(t1)} = {100 * len(overlong) // max(1, len(t1))}%",
        f"  平均スコア: {avg:.1f}",
        f"  低スコア(<60): {len(low)}件 / 禁則候補(5回以上・未登録): {len(candidates)}件",
    ]
    if candidates:
        summary_lines.append("  候補語尾句: " + ", ".join(f"{c['phrase']}({c['count']})" for c in candidates[:10]))

    out = "\n".join(summary_lines)
    LOG_OUT.parent.mkdir(parents=True, exist_ok=True)
    with LOG_OUT.open("a", encoding="utf-8") as f:
        f.write(f"[{NOW.isoformat()}]\n{out}\n")
    BAD_CAND_OUT.write_text(json.dumps({
        "generated_at": NOW.isoformat(),
        "period_days": 7,
        "candidates": candidates,
        "metrics": {
            "try1_total": len(t1),
            "try1_passed": len(passed),
            "try1_pass_rate": round(100 * len(passed) / max(1, len(t1)), 1),
            "try1_overlong_rate": round(100 * len(overlong) / max(1, len(t1)), 1),
            "avg_score": round(avg, 1),
        },
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
