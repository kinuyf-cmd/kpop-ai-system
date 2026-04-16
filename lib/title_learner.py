#!/usr/bin/env python3
"""
タイトル学習システム

- 過去の勝ちパターン（win）タイトルから共通ワードを抽出
- 新規タイトル生成時に勝ちパターンを参照
- X投稿後のスコアを記録

Usage:
  # 記録
  python3 lib/title_learner.py record --title "..." --pattern "感情型" --score 85

  # 勝ちパターン取得
  python3 lib/title_learner.py winners

  # 勝ちワード抽出
  python3 lib/title_learner.py winning-words
"""

import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

PERF_FILE = Path(__file__).parent.parent / "logs" / "title_performance.jsonl"

# 強ワード辞書（勝ちパターン判定用）
STRONG_WORDS = [
    "ついに", "完全", "衝撃", "レベチ", "まさか", "神", "電撃",
    "復活", "速報", "判明", "解禁", "決定", "炎上", "暴露",
    "初公開", "騒然", "尊い", "即完売",
]

WEAK_WORDS = [
    "まとめ", "解説", "情報", "レポート", "について", "を紹介",
]


def load_records() -> list[dict]:
    if not PERF_FILE.exists():
        return []
    records = []
    for line in PERF_FILE.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def save_record(record: dict) -> None:
    PERF_FILE.parent.mkdir(parents=True, exist_ok=True)
    # post_id が設定されている場合、既存の pending レコードと重複しないか確認
    post_id = record.get("post_id", "")
    if post_id:
        existing = load_records()
        for r in existing:
            if r.get("post_id") == post_id and r.get("result") == record.get("result") == "pending":
                return  # 同じ post_id の pending が既にある場合はスキップ
    with open(PERF_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def classify_pattern(title: str) -> str:
    """タイトルのパターンを自動分類"""
    has_strong = any(w in title for w in STRONG_WORDS)
    has_number = bool(re.search(r'\d', title))
    has_compare = any(w in title for w in ["vs", "比較", "どっち", "対決"])

    if has_compare:
        return "比較型"
    if has_strong:
        return "感情型"
    return "情報型"


def score_to_result(score: float) -> str:
    """スコアからwin/loseを判定"""
    return "win" if score >= 50 else "lose"


def get_winners(min_count: int = 3) -> list[dict]:
    """勝ちパターンのタイトル一覧を返す"""
    records = load_records()
    winners = [r for r in records if r.get("result") == "win"]
    return winners[-20:]  # 直近20件


def extract_winning_words(top_n: int = 10) -> list[tuple[str, int]]:
    """勝ちタイトルから頻出ワードを抽出"""
    records = load_records()
    winners = [r for r in records if r.get("result") == "win"]

    if not winners:
        return []

    word_counter: Counter = Counter()
    for r in winners:
        title = r.get("title", "")
        # 強ワードをカウント
        for w in STRONG_WORDS:
            if w in title:
                word_counter[w] += 1
        # 数字パターン
        if re.search(r'\d+[冠位選曲]', title):
            word_counter["数字+単位"] += 1

    return word_counter.most_common(top_n)


def generate_winning_prompt() -> str:
    """勝ちパターンをプロンプトに変換"""
    winners = get_winners()
    winning_words = extract_winning_words(8)

    if not winners and not winning_words:
        return ""

    lines = ["【過去の勝ちパターン参照（CTRスコア高のタイトル）】"]

    if winning_words:
        words_str = "、".join(f"{w}({c}回)" for w, c in winning_words)
        lines.append(f"勝ちワード: {words_str}")

    if winners:
        lines.append("勝ちタイトル例:")
        for w in winners[-5:]:
            lines.append(f"  - {w.get('title', '')} (pattern={w.get('pattern', '')})")

    lines.append("上記のパターンを参考に、タイトルBを生成せよ。")
    return "\n".join(lines)


def cmd_record(args):
    """タイトルパフォーマンスを記録"""
    pattern = args.pattern or classify_pattern(args.title)

    if args.pending:
        result = "pending"
    else:
        result = score_to_result(args.score)

    record = {
        "title": args.title,
        "ctr_score": args.score,
        "pattern": pattern,
        "result": result,
        "post_id": args.post_id or "",
        "timestamp": __import__("datetime").datetime.now().isoformat(),
    }
    save_record(record)
    print(json.dumps(record, ensure_ascii=False))


def cmd_update(args):
    """pending レコードを実CTRデータで win/lose 確定する"""
    records = load_records()
    updated = 0
    new_records = []
    for r in records:
        if r.get("post_id") == args.post_id and r.get("result") == "pending":
            r["ctr_score"] = args.score
            r["result"] = score_to_result(args.score)
            updated += 1
        new_records.append(r)

    if updated == 0:
        print(f"No pending records found for post_id={args.post_id}")
        return

    # 全レコードを書き直す
    PERF_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PERF_FILE, "w", encoding="utf-8") as f:
        for r in new_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"Updated {updated} records for post_id={args.post_id} → score={args.score}, result={score_to_result(args.score)}")


def cmd_winners(args):
    """勝ちパターン一覧"""
    winners = get_winners()
    if not winners:
        print("学習データなし")
        return
    for w in winners:
        print(f"  [{w.get('pattern','')}] {w.get('title','')} (score={w.get('ctr_score',0)})")


def cmd_winning_words(args):
    """勝ちワード抽出"""
    words = extract_winning_words()
    if not words:
        print("学習データなし")
        return
    for w, c in words:
        print(f"  {w}: {c}回")


def cmd_prompt(args):
    """勝ちパターンプロンプト生成"""
    prompt = generate_winning_prompt()
    if prompt:
        print(prompt)
    else:
        print("")


def main():
    parser = argparse.ArgumentParser(description="タイトル学習システム")
    sub = parser.add_subparsers(dest="command")

    p_record = sub.add_parser("record", help="パフォーマンス記録")
    p_record.add_argument("--title", required=True)
    p_record.add_argument("--score", type=float, required=True)
    p_record.add_argument("--pattern", default="")
    p_record.add_argument("--post-id", default="")
    p_record.add_argument("--pending", action="store_true",
                          help="result=pending で記録（実CTR取得後に確定）")

    p_update = sub.add_parser("update", help="pending → win/lose 確定")
    p_update.add_argument("--post-id", required=True)
    p_update.add_argument("--score", type=float, required=True)

    sub.add_parser("winners", help="勝ちパターン一覧")
    sub.add_parser("winning-words", help="勝ちワード抽出")
    sub.add_parser("prompt", help="勝ちパターンプロンプト生成")

    args = parser.parse_args()

    if args.command == "record":
        cmd_record(args)
    elif args.command == "update":
        cmd_update(args)
    elif args.command == "winners":
        cmd_winners(args)
    elif args.command == "winning-words":
        cmd_winning_words(args)
    elif args.command == "prompt":
        cmd_prompt(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
