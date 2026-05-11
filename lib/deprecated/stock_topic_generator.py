#!/usr/bin/env python3
"""[DEPRECATED 2026-05-11] stock_topic_generator.py — 勝ちテーマ抽出 → stock_topics.json 生成

廃止理由 (Phase 4 / GENERATOR_DEPRECATION_PLAN.md):
- 2026-04-16 を最後に未稼働 (cron 未登録 → silent rot)
- 出力 logs/stock_topics.json の消費者が存在しない (Python import / 参照 0)
- winning_title_patterns.py の docstring に名前があるだけで実呼出なし
- 同等機能は winning_pattern_expander / pv_kpi_winner_expansion が代替済

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

    # --- 勝ちパターン読み込み (winning_title_patterns.json) ---
    # 2026-04-16: ctr_title_rewriter のscore>=9データ12件から学習した勝ち要素を
    # タイトルテンプレに反映。4要素同居 (num+emo+con+art) 75% の成功率を狙う。
    win_path = LOGS / "winning_title_patterns.json"
    win_emo = ["完全", "解禁", "衝撃", "制覇", "首位"]
    win_con = ["→", "年ぶり", "一転", "復帰", "週連続"]
    win_len_target = (33, 43)  # 勝ちパターン実測範囲
    if win_path.exists():
        try:
            wp = json.loads(win_path.read_text())
            patt = wp.get("patterns", {})
            win_emo = [e for e, _ in patt.get("emotions_top", [])[:5]] or win_emo
            win_con = [c for c, _ in patt.get("contrasts_top", [])[:5]] or win_con
            lmin, lmax = patt.get("length_min", 33), patt.get("length_max", 43)
            win_len_target = (lmin, lmax)
        except Exception:
            pass

    # 勝ちパターンに基づいた angle templates (4要素必須: 数字/固有/感情/対比)
    angles = [
        ("新曲解説",    f"{{artist}}新曲ついに{win_emo[0]}｜2026年{win_con[0]}MV見どころ徹底解説"),
        ("メンバー比較", f"{{artist}}メンバー別人気ランキング2026｜{win_emo[1] if len(win_emo)>1 else '解禁'}の{win_con[0]}特徴全まとめ"),
        ("ツアー完全ガイド", f"{{artist}}日本ツアー2026{win_con[0]}{win_emo[0]}ガイド｜チケット・会場・セトリ予想"),
        ("ファッション特集", f"{{artist}}2026年ステージ衣装ブランド{win_emo[1] if len(win_emo)>1 else '解禁'}｜私服コーデ15選徹底解析"),
        ("チャート記録", f"{{artist}}が更新した歴代記録10選｜Billboard・Melon{win_emo[3] if len(win_emo)>3 else '制覇'}の{win_con[0]}道のり"),
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
