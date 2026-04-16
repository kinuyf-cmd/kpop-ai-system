#!/usr/bin/env python3
"""winning_title_patterns.py — score>=9のCTRリライト成功タイトルからパターン抽出

入力: logs/ctr_title_rewrite.jsonl
出力: logs/winning_title_patterns.json

抽出する次元:
  - numbers: 使用された数字/単位パターン
  - emotions: 感情語の出現頻度
  - contrasts: 対比構造の出現頻度
  - length_avg: 文字数分布
  - combinations: 3要素以上同居パターン

使い方:
  python3 lib/winning_title_patterns.py [--min-score 9]
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from statistics import mean, median

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"
SRC = LOGS / "ctr_title_rewrite.jsonl"
OUT = LOGS / "winning_title_patterns.json"

NUMBER_PAT = re.compile(r"(\d[\d,，]*(?:\.\d+)?)(万|億|千|百|週連続|日連続|年ぶり|連続|倍|冠|枚|回|位|人|%|％|形態|公演|曲)?")
EMOTION_WORDS = [
    "衝撃", "電撃", "判明", "ついに", "まさか", "速報", "記録", "驚愕",
    "神", "レベチ", "解禁", "完全", "必見", "復帰", "制覇", "初", "歴史",
    "快挙", "1位", "首位", "伝説", "奇跡", "爆発", "炎上", "暴露", "激白",
    "異常", "異次元", "世界一",
]
CONTRAST_WORDS = [
    "→", "⇒", "vs", "VS",
    "から", "でも", "なのに", "ただし", "一転", "激変", "崩壊", "逆転",
    "復帰", "空白", "空白", "塗替", "更新", "超え",
    "週連続", "日連続", "年ぶり", "回連続", "連覇",
]
ARTIST_PAT = re.compile(
    r"BTS|BLACKPINK|BIGBANG|aespa|BABYMONSTER|ILLIT|IVE|SEVENTEEN|TWICE|"
    r"Stray\s*Kids|NewJeans|LE\s*SSERAFIM|NCT|RIIZE|TXT|ENHYPEN|ITZY|NMIXX|"
    r"EXO|SHINee|TAEMIN|G-DRAGON|T\.O\.P|KATSEYE|Demon\s*Hunters|Jimin|ジミン|"
    r"BOA|ZEROBASEONE",
    re.IGNORECASE,
)


def load_wins(min_score: int) -> list[dict]:
    if not SRC.exists():
        return []
    wins = []
    seen_urls = set()
    for line in SRC.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        if d.get("score", 0) < min_score:
            continue
        # dedupe by url (keep first seen)
        u = d.get("url", "")
        if u in seen_urls:
            continue
        seen_urls.add(u)
        wins.append(d)
    return wins


def extract_patterns(wins: list[dict]) -> dict:
    numbers: Counter = Counter()
    number_units: Counter = Counter()
    emotions: Counter = Counter()
    contrasts: Counter = Counter()
    artists: Counter = Counter()
    lengths = []
    combinations_count = Counter()

    for w in wins:
        t = w.get("new_title", "")
        lengths.append(len(t))

        # Numbers
        for m in NUMBER_PAT.finditer(t):
            numbers[m.group(0)] += 1
            if m.group(2):
                number_units[m.group(2)] += 1

        # Emotions
        e_hits = [e for e in EMOTION_WORDS if e in t]
        for e in e_hits:
            emotions[e] += 1

        # Contrasts
        c_hits = [c for c in CONTRAST_WORDS if c in t]
        for c in c_hits:
            contrasts[c] += 1

        # Artists
        for am in ARTIST_PAT.finditer(t):
            artists[am.group(0)] += 1

        # Combinations
        has_num = bool(re.search(r"[0-9]", t))
        has_emo = bool(e_hits)
        has_con = bool(c_hits)
        has_art = bool(ARTIST_PAT.search(t))
        combo_key = "+".join([k for k, v in
                              [("num", has_num), ("emo", has_emo),
                               ("con", has_con), ("art", has_art)] if v])
        combinations_count[combo_key] += 1

    return {
        "sample_size": len(wins),
        "length_avg":  round(mean(lengths), 1) if lengths else 0,
        "length_median": round(median(lengths), 1) if lengths else 0,
        "length_min":   min(lengths) if lengths else 0,
        "length_max":   max(lengths) if lengths else 0,
        "numbers_top":     numbers.most_common(15),
        "number_units_top": number_units.most_common(10),
        "emotions_top":     emotions.most_common(15),
        "contrasts_top":    contrasts.most_common(15),
        "artists_top":      artists.most_common(15),
        "element_combos":   combinations_count.most_common(10),
    }


def recommend_template(p: dict) -> dict:
    """抽出したパターンから stock_topic_generator に渡す『勝ちテンプレ』を生成"""
    if p["sample_size"] == 0:
        return {"template": None, "note": "no wins to analyze"}

    top_emo = [e for e, _ in p["emotions_top"][:5]] or ["完全", "解禁"]
    top_con = [c for c, _ in p["contrasts_top"][:5]] or ["→"]
    top_units = [u for u, _ in p["number_units_top"][:5]] or ["週連続", "年ぶり"]

    templates = [
        "{artist}{number}{unit}{contrast}{event}{emotion}",
        "{artist}{emotion}｜{number}{unit}{event}",
        "{emotion}の{artist}、{event}{contrast}{number}{unit}",
        "{artist}×{event}、{number}{unit}{contrast}{emotion}",
    ]
    return {
        "templates": templates,
        "target_length_range": [max(26, p["length_min"]), min(45, p["length_max"])],
        "required_elements": {
            "number": "例: " + ", ".join([str(n) for n, _ in p["numbers_top"][:5]]),
            "emotion": "推奨: " + ", ".join(top_emo),
            "contrast": "推奨: " + ", ".join(top_con),
            "artist": "推奨: " + ", ".join([a for a, _ in p["artists_top"][:5]]),
        },
        "format_example": f"{{artist}}{{number}}{top_units[0] if top_units else ''}{top_con[0]}{top_emo[0]}",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-score", type=int, default=9)
    args = ap.parse_args()

    wins = load_wins(args.min_score)
    print(f"[winning_patterns] score>={args.min_score} 件数: {len(wins)}")
    if not wins:
        print("データ不足で分析停止")
        return

    patterns = extract_patterns(wins)
    template = recommend_template(patterns)
    output = {
        "analyzed_at": "2026-04-16",
        "source": str(SRC),
        "min_score_threshold": args.min_score,
        "patterns": patterns,
        "recommended_template": template,
        "top_examples": [
            {"score": w["score"], "new_title": w["new_title"],
             "old_title": w.get("old_title", "")}
            for w in sorted(wins, key=lambda x: -x["score"])[:5]
        ],
    }
    OUT.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(f"[winning_patterns] 保存: {OUT}")
    print(f"  平均文字数: {patterns['length_avg']} (範囲 {patterns['length_min']}〜{patterns['length_max']})")
    print(f"  感情語TOP5: {', '.join(f'{e}({c})' for e,c in patterns['emotions_top'][:5])}")
    print(f"  対比TOP5:   {', '.join(f'{c}({n})' for c,n in patterns['contrasts_top'][:5])}")
    print(f"  要素同居:   {dict(patterns['element_combos'])}")


if __name__ == "__main__":
    main()
