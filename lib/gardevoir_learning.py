#!/usr/bin/env python3
"""
gardevoir_learning.py — Gardevoir X-hook スコア分布と HARD_FAIL パターン学習

データ: logs/gardevoir_hook.jsonl
出力:
  - logs/gardevoir_learning.log: 7日間のスコア分布・verdict比率・HARD_FAILタイトル特徴
  - logs/gardevoir_hard_fail_patterns.json: HARD_FAILタイトルのN-gram頻出パターン候補

用途:
  gardevoir_hook_critic のSOFT_RETRY/HARD_FAIL率が高いとき、原因タイトルに共通する
  言語パターンを抽出してmetamon/deoxysに投入（将来 auto_directives 経由）。
"""
import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
SRC = BASE / "logs" / "gardevoir_hook.jsonl"
LOG_OUT = BASE / "logs" / "gardevoir_learning.log"
PATTERNS_OUT = BASE / "logs" / "gardevoir_hard_fail_patterns.json"

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)
SINCE = NOW - timedelta(days=7)


def _parse_ts(s):
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except Exception:
        return None


def load_entries():
    if not SRC.exists():
        return []
    out = []
    for line in SRC.read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(line)
        except Exception:
            continue
        ts = _parse_ts(d.get("ts", ""))
        if ts is None:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if ts >= SINCE.astimezone(ts.tzinfo):
            d["_ts"] = ts
            out.append(d)
    return out


def extract_ngrams(text, ns=(3, 4, 5)):
    text = re.sub(r'\s+', ' ', text).strip()
    out = []
    for n in ns:
        for i in range(len(text) - n + 1):
            out.append(text[i:i + n])
    return out


def main():
    entries = load_entries()
    if not entries:
        msg = f"[{NOW.isoformat()}] gardevoir_hook.jsonl に過去7日分のデータなし"
        LOG_OUT.parent.mkdir(parents=True, exist_ok=True)
        with LOG_OUT.open("a", encoding="utf-8") as f:
            f.write(msg + "\n")
        print(msg)
        return

    # verdictカウント
    verdicts = Counter()
    scores = []
    hard_fail_titles = []
    soft_retry_titles = []
    for e in entries:
        v = (e.get("verdict") or "").upper()
        verdicts[v] += 1
        try:
            s = int(e.get("score", 0))
        except Exception:
            s = 0
        scores.append(s)
        t = e.get("title", "")
        if v in ("HARD_FAIL", "HARD"):
            hard_fail_titles.append(t)
        elif v == "SOFT_RETRY":
            soft_retry_titles.append(t)

    # エージェント応答汚染タイトル検出（「記事本文を確認」「以下のタイトル」等）
    error_pattern_hits = Counter()
    _error_patterns = [
        "記事本文を確認", "以下のタイトル案", "提案します", "見てください",
        "WebFetch", "権限が付与", "申し訳ありません",
    ]
    for t in hard_fail_titles:
        for p in _error_patterns:
            if p in t:
                error_pattern_hits[p] += 1

    # HARD_FAIL タイトルからN-gram
    ng_counter = Counter()
    for t in hard_fail_titles:
        for ng in extract_ngrams(t, ns=(4, 5, 6)):
            ng_counter[ng] += 1
    # 3回以上出現 & 長さ4以上の上位20
    hot_ngrams = [
        {"ngram": ng, "count": c}
        for ng, c in ng_counter.most_common(50)
        if c >= 3 and len(ng) >= 4
    ][:20]

    lines = [f"[gardevoir_learning] 期間 {SINCE.date()}〜{NOW.date()}"]
    lines.append(f"  総サンプル: {len(entries)}")
    lines.append(f"  verdict比率: {dict(verdicts)}")
    avg = sum(scores) / len(scores) if scores else 0
    lines.append(f"  スコア: avg={avg:.1f} min={min(scores, default=0)} max={max(scores, default=0)}")
    lines.append(f"  HARD_FAIL: {len(hard_fail_titles)}件 / SOFT_RETRY: {len(soft_retry_titles)}件")
    if error_pattern_hits:
        lines.append(f"  エージェント応答汚染検出: {dict(error_pattern_hits)}")
    if hot_ngrams:
        lines.append(f"  HARD_FAIL共通n-gram TOP5: " + ", ".join(
            f"'{x['ngram']}'({x['count']})" for x in hot_ngrams[:5]))

    out = "\n".join(lines)
    LOG_OUT.parent.mkdir(parents=True, exist_ok=True)
    with LOG_OUT.open("a", encoding="utf-8") as f:
        f.write(f"[{NOW.isoformat()}]\n{out}\n")

    PATTERNS_OUT.write_text(json.dumps({
        "generated_at": NOW.isoformat(),
        "period_days": 7,
        "total_samples": len(entries),
        "verdict_counts": dict(verdicts),
        "avg_score": round(avg, 1),
        "hard_fail_count": len(hard_fail_titles),
        "soft_retry_count": len(soft_retry_titles),
        "error_response_contamination": dict(error_pattern_hits),
        "hard_fail_ngrams": hot_ngrams,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
