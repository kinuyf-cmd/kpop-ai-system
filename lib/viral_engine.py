#!/usr/bin/env python3
"""
バイラルコンテンツ戦略エンジン

機能:
  1. バイラル予測スコア算出（タイトル・記事属性から拡散可能性を予測）
  2. SNSシェア数トラッキング（X/Twitter API連携）
  3. 「衝撃」「感動」「炎上」系記事の自動生成ロジック支援
  4. バイラルレポート出力

使い方:
  python3 lib/viral_engine.py score "タイトル文字列"
  python3 lib/viral_engine.py track [--days 7]
  python3 lib/viral_engine.py suggest [--count 5]
  python3 lib/viral_engine.py report
"""
from __future__ import annotations
import argparse
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"
CONFIG = BASE / "config"
GMETRICS = BASE / "google_metrics"

VIRAL_LOG = LOGS / "viral_scores.jsonl"
SHARE_LOG = LOGS / "sns_shares.jsonl"

WP = "https://www.kpopjournal.tokyo"
WP_AUTH = str(Path.home() / ".wp_auth")
JST = timezone(timedelta(hours=9))

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# バイラル予測スコア
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 感情トリガーワード（各カテゴリ0-25点、合計100点満点）
EMOTION_TRIGGERS = {
    "shock": {
        "words": ["衝撃", "まさか", "異常", "強すぎる", "止まらない", "信じられない",
                  "ヤバい", "やばい", "前代未聞", "史上初", "歴代最高", "崩壊",
                  "爆発", "激震", "暴露", "真相", "なぜ", "なのに"],
        "weight": 25,
        "label": "衝撃・驚き",
    },
    "emotion": {
        "words": ["感動", "号泣", "涙", "泣ける", "鳥肌", "最高",
                  "伝説", "神", "圧倒", "圧巻", "無双", "覚醒",
                  "復帰", "約束", "6年", "7年", "再結成", "解禁"],
        "weight": 25,
        "label": "感動・共感",
    },
    "controversy": {
        "words": ["炎上", "批判", "謝罪", "問題", "騒動", "訴訟",
                  "脱退", "活動休止", "破局", "熱愛", "発覚", "疑惑",
                  "裏切り", "闇", "告白"],
        "weight": 20,
        "label": "論争・炎上",
    },
    "curiosity": {
        "words": ["？", "なぜ", "理由", "真実", "本当", "秘密",
                  "知らなかった", "裏側", "舞台裏", "素顔", "正体",
                  "実は", "ついに", "初めて", "だけ"],
        "weight": 15,
        "label": "好奇心・疑問",
    },
    "specificity": {
        "words": [],  # 数字・固有名詞で判定
        "weight": 15,
        "label": "具体性・数字",
    },
}

# トレンドアーティスト（時期により変動・定期更新推奨）
TRENDING_ARTISTS = [
    "BTS", "BLACKPINK", "NewJeans", "aespa", "IVE", "LE SSERAFIM",
    "Stray Kids", "SEVENTEEN", "ENHYPEN", "TXT", "BABYMONSTER",
    "G-DRAGON", "BIGBANG", "TWICE", "ILLIT", "RIIZE",
]

# バイラルテーマテンプレート
VIRAL_TEMPLATES = {
    "shock_record": {
        "pattern": "{artist}、{record}を達成──{detail}",
        "emotion": "shock",
        "example": "BTS、初週641,000枚を達成──3週連続1位の異常な数字",
    },
    "emotional_comeback": {
        "pattern": "{duration}の空白、{artist}が帰ってきた。{hook}",
        "emotion": "emotion",
        "example": "6年半の空白、BTSが帰ってきた。全部返してきた夜",
    },
    "why_question": {
        "pattern": "なぜ{artist}だけ{phenomenon}なのか？{data}",
        "emotion": "curiosity",
        "example": "なぜBTSだけ止まらないのか？3週連続1位の異常な数字",
    },
    "vs_comparison": {
        "pattern": "{artist_a} vs {artist_b}──{axis}で比較した結果",
        "emotion": "curiosity",
        "example": "NewJeans vs LE SSERAFIM──デビュー1年の成績で比較した結果",
    },
    "controversy_deep": {
        "pattern": "{artist}の{event}、その裏で何が起きていたのか",
        "emotion": "controversy",
        "example": "NewJeansの契約問題、その裏で何が起きていたのか",
    },
    "ranking_surprise": {
        "pattern": "「{item}」が{rank}位に──{surprise_element}",
        "emotion": "shock",
        "example": "「Magnetic」が年間1位に──デビュー曲で達成は史上初",
    },
    "legacy_analysis": {
        "pattern": "{period}、{artist}は何を溜めていたのか──{reveal}",
        "emotion": "emotion",
        "example": "13年間、T.O.Pは何を溜めていたのか──ついに解放された音楽の正体",
    },
}


def calculate_viral_score(title: str, content: str = "") -> dict:
    """バイラル予測スコアを算出（0-100点）"""
    text = title.lower()
    scores = {}
    details = {}

    # 感情トリガー
    for cat, cfg in EMOTION_TRIGGERS.items():
        if cat == "specificity":
            # 数字の有無
            has_number = bool(re.search(r"[0-9０-９]", title))
            # 固有名詞の有無
            has_artist = any(a.lower() in text for a in TRENDING_ARTISTS)
            specificity_score = 0
            if has_number:
                specificity_score += 8
            if has_artist:
                specificity_score += 7
            scores[cat] = min(specificity_score, cfg["weight"])
            details[cat] = {"has_number": has_number, "has_artist": has_artist}
        else:
            hits = [w for w in cfg["words"] if w.lower() in text or w in title]
            # 各カテゴリの最大スコアまで（ヒット数に応じて加点）
            raw = min(len(hits) * 8, cfg["weight"])
            scores[cat] = raw
            details[cat] = {"hits": hits[:5], "count": len(hits)}

    total = sum(scores.values())

    # ボーナス: タイトル文字数（30-40文字が最適）
    title_len = len(title)
    if 28 <= title_len <= 40:
        total = min(total + 5, 100)
    elif title_len > 50:
        total = max(total - 10, 0)

    # ボーナス: 対比構造
    if any(w in title for w in ["vs", "→", "——", "──", "なのに", "でも", "ただし"]):
        total = min(total + 5, 100)

    return {
        "title": title,
        "total_score": total,
        "grade": _grade(total),
        "breakdown": {k: {"score": v, "max": EMOTION_TRIGGERS[k]["weight"],
                         "label": EMOTION_TRIGGERS[k]["label"],
                         **details.get(k, {})}
                     for k, v in scores.items()},
        "recommendation": _recommend(total, scores),
    }


def _grade(score: int) -> str:
    if score >= 80:
        return "S（バイラル確実）"
    elif score >= 65:
        return "A（高拡散）"
    elif score >= 50:
        return "B（中拡散）"
    elif score >= 35:
        return "C（低拡散）"
    else:
        return "D（改善必要）"


def _recommend(total: int, scores: dict) -> str:
    if total >= 65:
        return "このままでOK。X投稿を優先し、ハッシュタグを3個以上付与"
    weak = min(scores, key=scores.get)
    label = EMOTION_TRIGGERS[weak]["label"]
    if weak == "specificity":
        return f"数字またはアーティスト名を追加してください（{label}が弱い）"
    else:
        example_words = EMOTION_TRIGGERS[weak]["words"][:3]
        return f"「{'」「'.join(example_words)}」等のワードを追加してください（{label}が弱い）"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SNSシェアトラッキング
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def track_shares(days: int = 7) -> list[dict]:
    """X/Twitter APIからシェア数を取得"""
    print(f"=== SNSシェアトラッキング（直近{days}日）===")

    # X API v2でURL引用ツイート数を取得
    bearer = os.environ.get("X_BEARER_TOKEN", "")

    # WPから直近記事を取得
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
    cmd = ["curl", "-s",
           f"{WP}/wp-json/wp/v2/posts?per_page=50&after={cutoff}&_fields=id,title,link",
           "-K", WP_AUTH]
    try:
        posts = json.loads(subprocess.check_output(cmd, timeout=15))
    except Exception as e:
        print(f"  ⚠️ WP取得失敗: {e}")
        return []

    results = []
    for post in posts:
        url = post.get("link", "")
        title = post.get("title", {}).get("rendered", "")
        pid = post["id"]

        share_count = 0

        # X API（Bearer Tokenあれば使用）
        if bearer and url:
            try:
                import urllib.request
                api_url = f"https://api.twitter.com/2/tweets/counts/recent?query=url:{url}"
                req = urllib.request.Request(api_url, headers={"Authorization": f"Bearer {bearer}"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read())
                    share_count = data.get("meta", {}).get("total_tweet_count", 0)
            except Exception:
                pass

        # フォールバック: X post logから取得
        if share_count == 0:
            x_log = LOGS / "x_post.log"
            if x_log.exists():
                with open(x_log) as f:
                    for line in f:
                        if str(pid) in line or url in line:
                            share_count = max(share_count, 1)

        results.append({
            "post_id": pid,
            "title": title[:60],
            "url": url,
            "x_shares": share_count,
        })

    # ログ記録
    LOGS.mkdir(exist_ok=True)
    ts = datetime.now(JST).isoformat()
    with open(SHARE_LOG, "a") as f:
        f.write(json.dumps({
            "date": ts,
            "period_days": days,
            "articles": len(results),
            "total_shares": sum(r["x_shares"] for r in results),
            "top_shared": sorted(results, key=lambda x: x["x_shares"], reverse=True)[:5],
        }, ensure_ascii=False) + "\n")

    results.sort(key=lambda x: x["x_shares"], reverse=True)
    print(f"  対象記事: {len(results)}件")
    print(f"  シェア合計: {sum(r['x_shares'] for r in results)}件")
    if results:
        print(f"\n  TOP5:")
        for i, r in enumerate(results[:5], 1):
            print(f"    {i}. {r['x_shares']}シェア | {r['title'][:50]}")

    return results


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# バイラルテーマ提案
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def suggest_viral_themes(count: int = 5) -> list[dict]:
    """バイラル記事テーマの提案"""
    print(f"=== バイラルテーマ提案（{count}件）===")

    suggestions = []
    for key, tmpl in list(VIRAL_TEMPLATES.items())[:count]:
        suggestions.append({
            "template_key": key,
            "pattern": tmpl["pattern"],
            "emotion_type": tmpl["emotion"],
            "example": tmpl["example"],
            "viral_score": calculate_viral_score(tmpl["example"])["total_score"],
        })

    for s in suggestions:
        print(f"\n  [{s['emotion_type'].upper()}] スコア: {s['viral_score']}")
        print(f"    パターン: {s['pattern']}")
        print(f"    例: {s['example']}")

    return suggestions


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# バイラルレポート
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def report():
    """バイラルレポート出力"""
    print("=== バイラルコンテンツレポート ===")

    # スコアログ
    if VIRAL_LOG.exists():
        entries = []
        with open(VIRAL_LOG) as f:
            for line in f:
                if line.strip():
                    entries.append(json.loads(line))

        if entries:
            recent = entries[-20:]
            avg_score = sum(e.get("total_score", 0) for e in recent) / len(recent)
            print(f"\n  直近20記事の平均バイラルスコア: {avg_score:.1f}")

            grade_dist = defaultdict(int)
            for e in recent:
                grade_dist[e.get("grade", "?")[0]] += 1
            print(f"  グレード分布: {dict(grade_dist)}")

    # シェアログ
    if SHARE_LOG.exists():
        with open(SHARE_LOG) as f:
            lines = [json.loads(l) for l in f if l.strip()]
        if lines:
            latest = lines[-1]
            print(f"\n  直近シェアトラッキング:")
            print(f"    対象期間: {latest.get('period_days', '?')}日")
            print(f"    シェア合計: {latest.get('total_shares', 0)}件")

    # 改善提案
    print(f"\n  💡 バイラル改善提案:")
    print(f"    1. タイトルに数字+感情ワードを必ず含める（スコア+15〜25点）")
    print(f"    2. 対比構造（vs/なのに/——）を使う（スコア+5点）")
    print(f"    3. 30-40文字以内に収める（長すぎるとスコア-10点）")
    print(f"    4. トレンドアーティスト名を含める（スコア+7点）")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# メイン
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def main():
    parser = argparse.ArgumentParser(description="バイラルコンテンツ戦略エンジン")
    sub = parser.add_subparsers(dest="command")

    p_score = sub.add_parser("score", help="バイラルスコア算出")
    p_score.add_argument("title", type=str)

    p_track = sub.add_parser("track", help="SNSシェアトラッキング")
    p_track.add_argument("--days", type=int, default=7)

    p_suggest = sub.add_parser("suggest", help="バイラルテーマ提案")
    p_suggest.add_argument("--count", type=int, default=5)

    sub.add_parser("report", help="バイラルレポート")

    args = parser.parse_args()

    if args.command == "score":
        result = calculate_viral_score(args.title)
        print(f"\n  タイトル: {result['title']}")
        print(f"  スコア: {result['total_score']}/100 ({result['grade']})")
        print(f"  内訳:")
        for k, v in result["breakdown"].items():
            bar = "█" * (v["score"] // 2) + "░" * ((v["max"] - v["score"]) // 2)
            print(f"    {v['label']:10s}: {v['score']:2d}/{v['max']:2d} {bar}")
        print(f"  提案: {result['recommendation']}")

        # ログ記録
        LOGS.mkdir(exist_ok=True)
        with open(VIRAL_LOG, "a") as f:
            result["ts"] = datetime.now(JST).isoformat()
            f.write(json.dumps(result, ensure_ascii=False) + "\n")

    elif args.command == "track":
        track_shares(days=args.days)

    elif args.command == "suggest":
        suggest_viral_themes(count=args.count)

    elif args.command == "report":
        report()

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
