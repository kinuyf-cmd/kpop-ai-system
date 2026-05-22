#!/usr/bin/env python3
"""lib/revenue/genre_classifier.py — J-2 A8.net ジャンル判定 → CTA案件選択。

config/affiliate/a8_master.json(9カテゴリ×案件マトリクス)と
config/affiliate/cta_genre_map.json(タイトル正規表現/WPタグ → ジャンル)を使い、
記事のタイトル・カテゴリ・タグから最適な A8 案件を選ぶ。

a8mat/pid 等は公開トラッキングコード(secretではない)。

Usage:
  python3 lib/revenue/genre_classifier.py "BTSソウルコンサート2026 完全ガイド"
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from lib.revenue import settings  # noqa: E402

# 9カテゴリ(a8_master.json _metadata.categories と整合)
A8_CATEGORIES = [
    "kpop_goods", "korean_cosme", "korean_fashion", "korean_language",
    "travel_korea", "esim_wifi", "vod", "lifestyle", "shopping_mall",
]


def load_a8_master() -> dict:
    try:
        with open(settings.a8_master_path(), encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"programs": {}, "_metadata": {"categories": A8_CATEGORIES}}


def load_genre_map() -> tuple[dict, dict]:
    try:
        with open(settings.a8_genre_map_path(), encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}, {}
    return data.get("hybrid_banner_matrix", {}), data.get("hybrid_defaults", {})


def classify_genre(title: str, category_names: list | None = None,
                   tag_names: list | None = None) -> str:
    """記事を cta_genre_map の hybrid_banner_matrix ジャンルに分類する。

    タイトル正規表現マッチ数 + WPタグ一致(加点)でスコアし、最大スコアを返す。
    該当なしは "default"。
    """
    category_names = category_names or []
    tag_names = tag_names or []
    matrix, _ = load_genre_map()
    text = " ".join([title, *category_names, *tag_names])

    best_match, best_score = None, 0
    for genre_key, rule in matrix.items():
        if not isinstance(rule, dict):
            continue
        regex = rule.get("title_regex", "")
        if not regex:
            continue
        score = len(re.findall(regex, text, re.IGNORECASE))
        for tag in tag_names:
            if tag in rule.get("wp_tags", []):
                score += 2
        if score > best_score:
            best_score, best_match = score, genre_key
    return best_match or "default"


def select_programs(title: str, category_names: list | None = None,
                    tag_names: list | None = None) -> dict:
    """ジャンル判定 → 各ポジション(top/middle/bottom)の案件キーを返す。"""
    genre = classify_genre(title, category_names, tag_names)
    matrix, defaults = load_genre_map()
    rule = matrix.get(genre, {})
    out = {"genre": genre, "positions": {}}
    for pos in ("position_top", "position_middle", "position_bottom"):
        pos_data = rule.get(pos) if rule else None
        if not pos_data:
            pos_data = defaults.get(pos, {})
        out["positions"][pos] = pos_data
    return out


def programs_by_category(category: str) -> list[dict]:
    """A8マスターから、指定カテゴリに属する案件一覧(tier順)を返す。"""
    master = load_a8_master()
    progs = []
    for key, prog in master.get("programs", {}).items():
        if category in prog.get("categories", []):
            progs.append({
                "key": key,
                "name": prog.get("name", ""),
                "tier": prog.get("tier", 99),
                "estimated_reward": prog.get("estimated_reward", ""),
                "ctr": prog.get("ctr", 0),
                "best_for": prog.get("best_for", []),
            })
    return sorted(progs, key=lambda p: (p.get("tier", 99), -float(p.get("ctr") or 0)))


def category_matrix() -> dict:
    """9カテゴリ × 案件 のマトリクス(各カテゴリに属する案件キー一覧)。"""
    master = load_a8_master()
    cats = master.get("_metadata", {}).get("categories", A8_CATEGORIES)
    matrix = {c: [] for c in cats}
    for key, prog in master.get("programs", {}).items():
        for c in prog.get("categories", []):
            matrix.setdefault(c, []).append(key)
    return matrix


def main():
    if len(sys.argv) < 2:
        print("Usage: genre_classifier.py <article_title> [tag1,tag2,...]")
        print("\n9カテゴリ × 案件マトリクス:")
        print(json.dumps(category_matrix(), ensure_ascii=False, indent=2))
        return
    title = sys.argv[1]
    tags = sys.argv[2].split(",") if len(sys.argv) > 2 else []
    result = select_programs(title, tag_names=tags)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
