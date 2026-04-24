#!/usr/bin/env python3
"""seo_competitor_analyzer.py — GSCデータ駆動の競合キーワードギャップ分析

GSCのクエリ×ページデータを分析し、以下を自動検出する:
  1. 高impだが低順位のキーワード（改善余地大）
  2. 自サイトがカバーしていない競合キーワード（ギャップ）
  3. 順位5-20位のキーワード（TOP5に押し上げるべきターゲット）
  4. カニバリゼーション（同一クエリで複数ページが競合）

出力: logs/seo_competitor_report.json + CEO提案キュー投入

使い方:
  python3 lib/seo_competitor_analyzer.py                 # 分析レポート生成
  python3 lib/seo_competitor_analyzer.py --to-ceo        # CEO提案キューに投入
  python3 lib/seo_competitor_analyzer.py --actionable    # アクション可能な提案のみ
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from collections import defaultdict

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"
LOGS.mkdir(exist_ok=True)
CONFIG = BASE / "config" / "seo_config.json"
GSC_FILE = LOGS / "gsc_metrics_latest.json"
METRICS_FILE = BASE / "google_metrics" / "metrics_yesterday.json"
OUT_FILE = LOGS / "seo_competitor_report.json"
CEO_QUEUE = LOGS / "ceo_proposal_queue.jsonl"
JST = timezone(timedelta(hours=9))


def load_config() -> dict:
    try:
        return json.loads(CONFIG.read_text())
    except Exception:
        return {}


def load_gsc_queries() -> list[dict]:
    """metrics_yesterday.json からクエリ別データを取得"""
    if not METRICS_FILE.exists():
        return []
    try:
        data = json.loads(METRICS_FILE.read_text())
        return data.get("gsc", {}).get("top_queries", [])
    except Exception:
        return []


def load_gsc_pages() -> list[dict]:
    """gsc_metrics_latest.json からページ別データを取得"""
    if not GSC_FILE.exists():
        return []
    try:
        data = json.loads(GSC_FILE.read_text())
        return data.get("pages", [])
    except Exception:
        return []


def load_existing_slugs() -> set[str]:
    """article_index.json から既存記事スラグを取得"""
    idx_file = LOGS / "article_index.json"
    if not idx_file.exists():
        return set()
    try:
        data = json.loads(idx_file.read_text())
        slugs = set()
        for a in data.get("articles", []):
            url = a.get("url", "")
            slug = url.rstrip("/").split("/")[-1] if "/" in url else ""
            if slug:
                slugs.add(slug.lower())
        return slugs
    except Exception:
        return set()


# ─── 分析関数 ────────────────────────────────────────────────────────────────

def find_high_opportunity_keywords(queries: list[dict]) -> list[dict]:
    """高imp × 低順位: 順位改善で大幅クリック増が見込めるキーワード"""
    opportunities = []
    for q in queries:
        pos = q.get("position", 100)
        imp = q.get("impressions", 0)
        ctr = q.get("ctr", 0)
        clicks = q.get("clicks", 0)

        if imp < 10:
            continue

        # 期待CTRモデル（順位別）
        expected_ctr = {
            1: 0.28, 2: 0.15, 3: 0.11, 4: 0.08, 5: 0.06,
            6: 0.05, 7: 0.04, 8: 0.03, 9: 0.025, 10: 0.02,
        }.get(min(int(pos), 10), max(0.01, 0.3 / pos))

        potential_clicks = int(imp * expected_ctr)
        click_gap = potential_clicks - clicks

        if click_gap > 2 and 3 < pos <= 30:
            opportunities.append({
                "query": q["query"],
                "position": round(pos, 1),
                "impressions": imp,
                "clicks": clicks,
                "ctr": round(ctr * 100, 2),
                "potential_clicks": potential_clicks,
                "click_gap": click_gap,
                "action": "improve_existing" if pos <= 15 else "create_pillar",
                "priority": "high" if click_gap > 10 else "medium",
            })

    opportunities.sort(key=lambda x: -x["click_gap"])
    return opportunities[:30]


def find_cannibalization(queries: list[dict], pages: list[dict]) -> list[dict]:
    """同一クエリで複数ページが表示されるカニバリゼーションを検出"""
    # queries にはpage情報がないため、ページURLのスラグからクエリとの関連を推定
    # 簡易版: 同一アーティスト名を含む複数ページを検出
    from collections import Counter

    artist_pages: dict[str, list[dict]] = defaultdict(list)
    artists = [
        "bts", "blackpink", "aespa", "twice", "seventeen", "newjeans",
        "ive", "le sserafim", "stray kids", "nct", "riize", "illit",
        "bigbang", "exo", "itzy", "babymonster", "txt", "enhypen",
    ]

    for pg in pages:
        url = pg.get("url", "").lower()
        slug = url.rstrip("/").split("/")[-1] if "/" in url else ""
        for artist in artists:
            if artist.replace(" ", "-") in slug or artist.replace(" ", "") in slug:
                artist_pages[artist].append({
                    "url": pg["url"],
                    "impressions": pg.get("impressions", 0),
                    "clicks": pg.get("clicks", 0),
                    "ctr": round(pg.get("ctr", 0) * 100, 2),
                    "position": round(pg.get("position", 0), 1),
                })

    cannibal = []
    for artist, pgs in artist_pages.items():
        if len(pgs) < 2:
            continue
        # 同一アーティストで順位が近い（両方10位以内等）場合はカニバリの可能性
        top_pages = sorted(pgs, key=lambda x: x.get("position", 100))[:5]
        if len(top_pages) >= 2 and top_pages[0]["position"] < 20 and top_pages[1]["position"] < 20:
            cannibal.append({
                "artist": artist,
                "page_count": len(pgs),
                "top_pages": top_pages[:3],
                "action": "consolidate_or_differentiate",
            })

    return cannibal


def find_content_gaps(queries: list[dict]) -> list[dict]:
    """カバーすべきだがまだ記事がない（順位30+）のキーワード"""
    gaps = []
    for q in queries:
        pos = q.get("position", 100)
        imp = q.get("impressions", 0)
        if pos > 25 and imp > 20:
            gaps.append({
                "query": q["query"],
                "position": round(pos, 1),
                "impressions": imp,
                "action": "create_new_article",
                "suggested_type": "long_tail" if len(q["query"].split()) >= 3 else "pillar",
            })
    gaps.sort(key=lambda x: -x["impressions"])
    return gaps[:20]


def find_defend_keywords(queries: list[dict]) -> list[dict]:
    """TOP5を維持すべき重要キーワード"""
    defend = []
    for q in queries:
        pos = q.get("position", 100)
        imp = q.get("impressions", 0)
        if pos <= 5 and imp > 30:
            defend.append({
                "query": q["query"],
                "position": round(pos, 1),
                "impressions": imp,
                "clicks": q.get("clicks", 0),
                "action": "defend_and_update",
            })
    defend.sort(key=lambda x: -x["impressions"])
    return defend[:15]


# ─── レポート生成 ─────────────────────────────────────────────────────────────

def generate_report() -> dict:
    queries = load_gsc_queries()
    pages = load_gsc_pages()
    config = load_config()

    report = {
        "generated_at": datetime.now(JST).isoformat(),
        "data_source": {
            "queries": len(queries),
            "pages": len(pages),
        },
        "high_opportunity": find_high_opportunity_keywords(queries),
        "content_gaps": find_content_gaps(queries),
        "cannibalization": find_cannibalization(queries, pages),
        "defend_keywords": find_defend_keywords(queries),
        "competitor_domains": config.get("competitor_domains", []),
        "summary": {},
    }

    # サマリ
    ho = report["high_opportunity"]
    report["summary"] = {
        "total_opportunity_keywords": len(ho),
        "total_click_gap": sum(x["click_gap"] for x in ho),
        "top3_opportunity": [x["query"] for x in ho[:3]],
        "content_gaps_count": len(report["content_gaps"]),
        "cannibalization_artists": len(report["cannibalization"]),
        "defended_keywords": len(report["defend_keywords"]),
    }

    return report


def push_to_ceo_queue(report: dict):
    """分析結果をCEO提案キューに投入"""
    proposals = []

    for kw in report["high_opportunity"][:5]:
        proposals.append({
            "ts": datetime.now(JST).isoformat(),
            "source": "seo_competitor_analyzer",
            "type": "seo_opportunity",
            "priority": kw["priority"],
            "summary": f"[SEO] '{kw['query']}' 順位{kw['position']}→TOP5で+{kw['click_gap']}クリック/日",
            "action": kw["action"],
            "data": kw,
        })

    for gap in report["content_gaps"][:3]:
        proposals.append({
            "ts": datetime.now(JST).isoformat(),
            "source": "seo_competitor_analyzer",
            "type": "content_gap",
            "priority": "medium",
            "summary": f"[GAP] '{gap['query']}' imp={gap['impressions']}だが順位{gap['position']} → 新記事作成推奨",
            "action": "create_new_article",
            "data": gap,
        })

    if proposals:
        with CEO_QUEUE.open("a") as f:
            for p in proposals:
                f.write(json.dumps(p, ensure_ascii=False) + "\n")
        print(f"[seo_analyzer] CEO提案キューに{len(proposals)}件投入")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--to-ceo", action="store_true", help="CEO提案キューに投入")
    ap.add_argument("--actionable", action="store_true", help="アクション可能な提案のみ表示")
    args = ap.parse_args()

    report = generate_report()

    # 保存
    OUT_FILE.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"[seo_analyzer] レポート保存: {OUT_FILE}")

    # サマリ表示
    s = report["summary"]
    print(f"\n=== SEO競合分析レポート ===")
    print(f"  機会キーワード: {s['total_opportunity_keywords']}件 (潜在+{s['total_click_gap']}クリック/日)")
    print(f"  コンテンツギャップ: {s['content_gaps_count']}件")
    print(f"  カニバリゼーション: {s['cannibalization_artists']}アーティスト")
    print(f"  防衛キーワード: {s['defended_keywords']}件")

    if s["top3_opportunity"]:
        print(f"  TOP3機会: {', '.join(s['top3_opportunity'])}")

    if args.actionable:
        print(f"\n--- アクション提案 ---")
        for kw in report["high_opportunity"][:10]:
            print(f"  [{kw['priority'].upper()}] {kw['query']}: "
                  f"pos={kw['position']} imp={kw['impressions']} → +{kw['click_gap']}clicks ({kw['action']})")
        for gap in report["content_gaps"][:5]:
            print(f"  [GAP] {gap['query']}: pos={gap['position']} imp={gap['impressions']} → 新記事作成")

    if args.to_ceo:
        push_to_ceo_queue(report)


if __name__ == "__main__":
    main()
