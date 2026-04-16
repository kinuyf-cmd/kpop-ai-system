#!/usr/bin/env python3
"""stock_topic_generator.py — 勝ちテーマ抽出 → stock_topics.json 生成

ソース:
  - logs/title_performance.jsonl
  - logs/kpi_posts.jsonl
  - logs/gardevoir_hook.jsonl (高score記録)

出力:
  - logs/stock_topics.json (優先度順テーマリスト)

使い方:
  python3 lib/stock_topic_generator.py [--top 30]
"""
from __future__ import annotations
import argparse
import json
import re
from collections import defaultdict, Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"
OUT = LOGS / "stock_topics.json"
JST = timezone(timedelta(hours=9))


def load_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    out = []
    for line in p.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def extract_keywords(title: str) -> list[str]:
    """タイトルからアーティスト・ジャンル・話題ワードを抽出"""
    ARTISTS = [
        "BTS", "BLACKPINK", "BIGBANG", "aespa", "BABYMONSTER", "ILLIT", "IVE",
        "SEVENTEEN", "TWICE", "Stray Kids", "NewJeans", "LE SSERAFIM", "NCT",
        "RIIZE", "TXT", "ENHYPEN", "ITZY", "NMIXX", "EXO", "SHINee", "TAEMIN",
        "G-DRAGON", "テミン", "BTS", "T.O.P", "ZEROBASEONE", "KATSEYE"
    ]
    GENRES = ["カムバック", "速報", "美容", "コスメ", "旅行", "イベント",
              "ファッション", "解説", "ゴシップ", "チャート", "ランキング"]
    THEMES = ["コーチェラ", "Billboard", "Melon", "初日", "制覇", "記録",
              "復帰", "衝撃", "ドーム", "ワールドツアー", "デビュー", "解禁"]
    found = []
    for w in ARTISTS + GENRES + THEMES:
        if w.lower() in title.lower():
            found.append(w)
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=30)
    args = ap.parse_args()

    title_perf = load_jsonl(LOGS / "title_performance.jsonl")
    kpi = load_jsonl(LOGS / "kpi_posts.jsonl")
    gardevoir = load_jsonl(LOGS / "gardevoir_hook.jsonl")

    # --- 1. gardevoir score>=80 通過タイトルのキーワード頻度 ---
    winner_keywords: Counter = Counter()
    for r in gardevoir:
        if r.get("score", 0) >= 80 and r.get("verdict") == "PASS":
            title = r.get("title", "")
            for kw in extract_keywords(title):
                winner_keywords[kw] += 1

    # --- 2. title_performance の CTR 上位 ---
    ctr_ranked = []
    for r in title_perf:
        ctr = r.get("ctr_score")
        if ctr is None:
            continue
        try:
            ctr = float(ctr)
        except Exception:
            continue
        if ctr >= 70:
            ctr_ranked.append((ctr, r.get("title", "")))
    ctr_ranked.sort(key=lambda x: -x[0])

    # --- 3. 記事投稿頻度の多いテーマ (kpi_posts から) ---
    post_themes: Counter = Counter()
    for r in kpi:
        t = r.get("title", "")
        for kw in extract_keywords(t):
            post_themes[kw] += 1

    # --- 4. 勝ちテーマ × まだ書かれていない切り口 の組み合わせ ---
    top_artists = [w for w, c in winner_keywords.most_common(10)
                   if any(a.lower() == w.lower() for a in
                          ["BTS", "BLACKPINK", "aespa", "IVE", "TWICE", "BABYMONSTER",
                           "ILLIT", "NewJeans", "SEVENTEEN", "ENHYPEN", "LE SSERAFIM",
                           "NCT", "RIIZE", "TXT", "Stray Kids", "G-DRAGON", "SHINee", "TAEMIN"])]
    if not top_artists:
        top_artists = ["BTS", "BLACKPINK", "aespa", "IVE", "TWICE"]

    angles = [
        ("新曲解説", "{artist}の最新曲を徹底解説｜MV見どころと歌詞の意味【2026年版】"),
        ("メンバー比較", "{artist}メンバー別の人気ランキングと特徴まとめ【最新版】"),
        ("ツアー完全ガイド", "{artist}の日本ツアー完全ガイド｜チケット・会場・セトリ予想"),
        ("ファッション特集", "{artist}のステージ衣装ブランド・私服コーデ徹底解析"),
        ("チャート記録", "{artist}が更新した歴代記録まとめ｜Billboard・Melon制覇の道のり"),
    ]

    stock = []
    for artist in top_artists:
        for angle_type, tmpl in angles:
            stock.append({
                "artist": artist,
                "angle": angle_type,
                "proposed_title": tmpl.format(artist=artist),
                "priority_score": winner_keywords.get(artist, 0) * 10
                                  + (5 if artist in ["BTS", "BLACKPINK"] else 0),
                "genre": "解説",
                "min_chars": 3000,
                "require_cta": True,
                "require_internal_links": True,
            })

    stock.sort(key=lambda x: -x["priority_score"])
    stock = stock[: args.top]

    OUT.write_text(json.dumps({
        "generated_at": datetime.now(tz=JST).isoformat(),
        "source_counts": {
            "title_performance": len(title_perf),
            "kpi_posts": len(kpi),
            "gardevoir_pass": sum(1 for r in gardevoir if r.get("score", 0) >= 80),
        },
        "winner_keywords_top10": winner_keywords.most_common(10),
        "stock_topics": stock,
    }, ensure_ascii=False, indent=2))

    print(f"[stock_topic_generator] stock_topics.json に {len(stock)}テーマを保存")
    print(f"  ログ: {OUT}")
    for s in stock[:5]:
        print(f"    • [{s['artist']}/{s['angle']}] {s['proposed_title']}")


if __name__ == "__main__":
    main()
