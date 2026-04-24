#!/usr/bin/env python3
"""seo_longtail_generator.py — ロングテールキーワードから記事テーマを自動生成

GSCデータ + 競合分析レポートから「低難易度×高ニーズ」のロングテールキーワードを抽出し、
strategy_pipeline / kpop_pipeline に投入可能な記事テーマを自動生成する。

ロングテール戦略:
  - 3語以上の具体的クエリ（「BTS ジン 復帰 いつ」等）
  - 順位10-50位で表示はあるがクリックが少ない
  - 競合が手薄（position 10+は記事が弱いか存在しない）
  - FAQ構造化データで0クリックSEOにも対応

出力:
  1. logs/seo_longtail_themes.json — 生成テーマリスト
  2. config/auto_directives.json の focus_themes に自動注入（オプション）

使い方:
  python3 lib/seo_longtail_generator.py                    # テーマ生成のみ
  python3 lib/seo_longtail_generator.py --inject            # auto_directivesに注入
  python3 lib/seo_longtail_generator.py --generate-prompts  # パイプライン用プロンプト生成
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from collections import defaultdict

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"
CONFIG = BASE / "config"
METRICS_FILE = BASE / "google_metrics" / "metrics_yesterday.json"
COMPETITOR_REPORT = LOGS / "seo_competitor_report.json"
OUT_THEMES = LOGS / "seo_longtail_themes.json"
AUTO_DIRECTIVES = CONFIG / "auto_directives.json"
JST = timezone(timedelta(hours=9))

# テーマテンプレート: クエリパターン→記事構成
THEME_TEMPLATES = {
    "date_query": {
        "patterns": ["いつ", "日程", "日付", "スケジュール", "予定"],
        "article_type": "解説",
        "h2_template": [
            "{topic}の最新スケジュール",
            "公式発表の内容まとめ",
            "過去の{artist}の{event}パターンから予測",
            "チケット・参加方法",
            "よくある質問（FAQ）",
        ],
        "faq_required": True,
    },
    "price_query": {
        "patterns": ["値段", "価格", "いくら", "料金", "費用", "チケット"],
        "article_type": "解説",
        "h2_template": [
            "{topic}の価格・料金一覧",
            "席種別・形態別の比較表",
            "最安値で手に入れる方法",
            "過去の価格推移",
            "よくある質問（FAQ）",
        ],
        "faq_required": True,
    },
    "howto_query": {
        "patterns": ["方法", "やり方", "手順", "申し込み", "買い方", "入手"],
        "article_type": "解説",
        "h2_template": [
            "{topic}の手順を完全解説",
            "事前に準備すべきもの",
            "ステップバイステップガイド",
            "よくある失敗と対策",
            "よくある質問（FAQ）",
        ],
        "faq_required": True,
    },
    "comparison_query": {
        "patterns": ["比較", "違い", "どっち", "おすすめ", "vs"],
        "article_type": "解説",
        "h2_template": [
            "{topic}を徹底比較",
            "項目別の比較表",
            "こんな人には{optionA}がおすすめ",
            "こんな人には{optionB}がおすすめ",
            "まとめ：結局どちらを選ぶべきか",
        ],
        "faq_required": False,
    },
    "ranking_query": {
        "patterns": ["ランキング", "人気", "top", "おすすめ", "一覧"],
        "article_type": "chart",
        "h2_template": [
            "{topic}ランキングTOP10",
            "選定基準と評価方法",
            "1位〜3位の詳細レビュー",
            "注目の急上昇",
            "よくある質問（FAQ）",
        ],
        "faq_required": True,
    },
    "location_query": {
        "patterns": ["場所", "アクセス", "行き方", "住所", "ソウル", "韓国"],
        "article_type": "travel",
        "h2_template": [
            "{topic}へのアクセス方法",
            "周辺の見どころ・カフェ",
            "実際に行った人の口コミ",
            "持ち物チェックリスト",
            "よくある質問（FAQ）",
        ],
        "faq_required": True,
    },
    "generic_longtail": {
        "patterns": [],
        "article_type": "解説",
        "h2_template": [
            "{topic}とは？基本情報まとめ",
            "最新の動向と注目ポイント",
            "ファンが知っておくべき5つのこと",
            "今後の展開予測",
            "よくある質問（FAQ）",
        ],
        "faq_required": True,
    },
}

# アーティスト名正規化
ARTIST_NORMALIZE = {
    "bts": "BTS", "blackpink": "BLACKPINK", "aespa": "aespa",
    "twice": "TWICE", "seventeen": "SEVENTEEN", "newjeans": "NewJeans",
    "ive": "IVE", "le sserafim": "LE SSERAFIM", "stray kids": "Stray Kids",
    "nct": "NCT", "riize": "RIIZE", "illit": "ILLIT", "bigbang": "BIGBANG",
    "exo": "EXO", "itzy": "ITZY", "babymonster": "BABYMONSTER",
    "txt": "TXT", "enhypen": "ENHYPEN", "plave": "PLAVE",
}


def load_gsc_queries() -> list[dict]:
    if not METRICS_FILE.exists():
        return []
    try:
        data = json.loads(METRICS_FILE.read_text())
        return data.get("gsc", {}).get("top_queries", [])
    except Exception:
        return []


def load_competitor_gaps() -> list[dict]:
    if not COMPETITOR_REPORT.exists():
        return []
    try:
        data = json.loads(COMPETITOR_REPORT.read_text())
        return data.get("content_gaps", [])
    except Exception:
        return []


def classify_query_intent(query: str) -> str:
    """クエリの検索意図をテンプレートキーにマッピング"""
    q = query.lower()
    for key, tmpl in THEME_TEMPLATES.items():
        if key == "generic_longtail":
            continue
        for pat in tmpl["patterns"]:
            if pat in q:
                return key
    return "generic_longtail"


def extract_artist(query: str) -> str | None:
    q = query.lower()
    for key, name in ARTIST_NORMALIZE.items():
        if key in q:
            return name
    return None


def generate_longtail_themes(queries: list[dict], gaps: list[dict]) -> list[dict]:
    """ロングテールキーワードから記事テーマを生成"""
    themes = []
    seen_topics: set[str] = set()

    # 1. GSCクエリからロングテール抽出
    for q in queries:
        query_text = q.get("query", "")
        pos = q.get("position", 100)
        imp = q.get("impressions", 0)
        clicks = q.get("clicks", 0)
        word_count = len(query_text.split())

        # ロングテール条件: 3語以上 OR 具体的な意図キーワード含む
        is_longtail = word_count >= 3
        intent = classify_query_intent(query_text)
        if intent != "generic_longtail":
            is_longtail = True

        if not is_longtail:
            continue
        if imp < 5:
            continue
        # 既にTOP3なら不要
        if pos <= 3 and clicks > 5:
            continue

        # 正規化
        topic = query_text.strip()
        if topic.lower() in seen_topics:
            continue
        seen_topics.add(topic.lower())

        artist = extract_artist(topic)
        template = THEME_TEMPLATES[intent]

        # タイトル案生成
        title_candidates = []
        if artist:
            if intent == "date_query":
                title_candidates.append(f"{artist}の{topic.replace(artist.lower(), '').strip()}はいつ？最新情報と日程まとめ")
            elif intent == "price_query":
                title_candidates.append(f"{artist}の{topic.replace(artist.lower(), '').strip()}の値段・料金を完全ガイド")
            elif intent == "howto_query":
                title_candidates.append(f"{artist}の{topic.replace(artist.lower(), '').strip()}のやり方・手順を徹底解説")
            else:
                title_candidates.append(f"{artist}の{topic.replace(artist.lower(), '').strip()}を徹底解説【{date.today().year}年最新】")
        else:
            title_candidates.append(f"{topic}を徹底解説【{date.today().year}年最新】")

        themes.append({
            "query": topic,
            "intent": intent,
            "artist": artist,
            "position": round(pos, 1),
            "impressions": imp,
            "clicks": clicks,
            "difficulty": "low" if pos > 15 else "medium",
            "article_type": template["article_type"],
            "title_candidates": title_candidates,
            "h2_structure": template["h2_template"],
            "faq_required": template.get("faq_required", False),
            "priority_score": imp * (1 + max(0, pos - 3) / 10),
        })

    # 2. 競合ギャップからも追加
    for gap in gaps:
        query_text = gap.get("query", "")
        if query_text.lower() in seen_topics:
            continue
        seen_topics.add(query_text.lower())

        intent = classify_query_intent(query_text)
        artist = extract_artist(query_text)
        template = THEME_TEMPLATES[intent]

        themes.append({
            "query": query_text,
            "intent": intent,
            "artist": artist,
            "position": gap.get("position", 50),
            "impressions": gap.get("impressions", 0),
            "clicks": 0,
            "difficulty": "low",
            "article_type": template["article_type"],
            "title_candidates": [f"{query_text}を徹底解説【{date.today().year}年最新】"],
            "h2_structure": template["h2_template"],
            "faq_required": template.get("faq_required", False),
            "priority_score": gap.get("impressions", 0) * 2,
            "source": "competitor_gap",
        })

    # priority_score で降順ソート
    themes.sort(key=lambda x: -x["priority_score"])
    return themes[:30]


def inject_to_auto_directives(themes: list[dict], max_inject: int = 3):
    """上位テーマをauto_directives.jsonのfocus_themesに注入"""
    try:
        directives = json.loads(AUTO_DIRECTIVES.read_text()) if AUTO_DIRECTIVES.exists() else {}
    except Exception:
        directives = {}

    existing_topics = {t.get("topic", "").lower() for t in directives.get("focus_themes", [])}
    new_themes = []

    for t in themes[:max_inject]:
        if t["query"].lower() in existing_topics:
            continue
        new_themes.append({
            "topic": t["query"],
            "hint": f"検索意図: {t['intent']} / 現在順位: {t['position']} / imp: {t['impressions']}",
            "category_suggest": t["article_type"],
            "source": "seo_longtail_generator",
            "added_date": date.today().isoformat(),
        })

    if new_themes:
        directives.setdefault("focus_themes", [])
        directives["focus_themes"].extend(new_themes)
        AUTO_DIRECTIVES.write_text(json.dumps(directives, ensure_ascii=False, indent=2))
        print(f"[longtail] auto_directives.jsonに{len(new_themes)}テーマ注入")
    else:
        print("[longtail] 注入対象なし（既存と重複）")


def generate_pipeline_prompts(themes: list[dict]) -> list[dict]:
    """パイプライン投入用のプロンプトを生成"""
    prompts = []
    for t in themes[:5]:
        artist = t.get("artist", "")
        h2_list = "\n".join(f"  - {h}" for h in t["h2_structure"])
        faq_note = "必ずFAQセクション（3問以上）を含め、FAQ構造化データ対応にすること。" if t["faq_required"] else ""

        prompt = f"""以下のキーワードを狙った記事を作成せよ。

【ターゲットキーワード】{t['query']}
【検索意図】{t['intent']}
【記事カテゴリ】{t['article_type']}
【推奨タイトル】{t['title_candidates'][0]}

【H2構成案】
{h2_list}

【SEO指示】
- ターゲットKWをタイトル・H2・冒頭100文字に必ず含めること
- 関連キーワード（LSI）を本文中に自然に散りばめること
- {faq_note}
- メタディスクリプション（110-130文字）を末尾に出力すること
- 情報元を明記すること
"""
        prompts.append({
            "query": t["query"],
            "prompt": prompt,
            "priority": t["priority_score"],
            "article_type": t["article_type"],
        })
    return prompts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inject", action="store_true", help="auto_directivesに注入")
    ap.add_argument("--generate-prompts", action="store_true", help="パイプライン用プロンプト生成")
    args = ap.parse_args()

    queries = load_gsc_queries()
    gaps = load_competitor_gaps()
    print(f"[longtail] GSCクエリ: {len(queries)}件 / 競合ギャップ: {len(gaps)}件")

    themes = generate_longtail_themes(queries, gaps)
    print(f"[longtail] ロングテールテーマ: {len(themes)}件生成")

    # 保存
    output = {
        "generated_at": datetime.now(JST).isoformat(),
        "total_themes": len(themes),
        "themes": themes,
    }
    OUT_THEMES.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(f"[longtail] 保存: {OUT_THEMES}")

    # サマリ表示
    print(f"\n=== ロングテールテーマ TOP10 ===")
    for i, t in enumerate(themes[:10], 1):
        print(f"  {i}. [{t['difficulty']}] {t['query']}")
        print(f"     pos={t['position']} imp={t['impressions']} intent={t['intent']} type={t['article_type']}")
        if t.get("title_candidates"):
            print(f"     title: {t['title_candidates'][0][:60]}")

    if args.inject:
        inject_to_auto_directives(themes)

    if args.generate_prompts:
        prompts = generate_pipeline_prompts(themes)
        prompt_file = LOGS / "seo_longtail_prompts.json"
        prompt_file.write_text(json.dumps(prompts, ensure_ascii=False, indent=2))
        print(f"\n[longtail] プロンプト{len(prompts)}件保存: {prompt_file}")


if __name__ == "__main__":
    main()
