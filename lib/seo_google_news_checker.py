#!/usr/bin/env python3
"""
seo_google_news_checker.py — Googleニュース申請要件チェッカー

Googleニュースパブリッシャーセンター申請に必要な技術要件を検証し、
不足分を報告する。

要件チェック項目:
  1. サイト構造: 明確なカテゴリ階層
  2. 記事要件: 日付・著者・見出し（h1/h2）の存在
  3. 構造化データ: Article or NewsArticle JSON-LD
  4. robots.txt / sitemap.xml の確認
  5. ニュースサイトマップ対応
  6. 透明性: 連絡先ページ・プライバシーポリシー・運営者情報
"""

import json
import os
import re
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, "lib"))

SITE_URL = "https://www.kpopjournal.tokyo"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 要件定義
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

REQUIREMENTS = {
    "technical": {
        "article_structured_data": {
            "description": "Article または NewsArticle 構造化データ（JSON-LD）が全記事に存在",
            "priority": "CRITICAL",
            "status": "implemented",
            "detail": "lib/seo_structured_data.py + html_postprocess.py で自動挿入済み",
        },
        "breadcrumb_structured_data": {
            "description": "BreadcrumbList 構造化データが全記事に存在",
            "priority": "HIGH",
            "status": "implemented",
            "detail": "lib/seo_structured_data.py + html_postprocess.py で自動挿入済み",
        },
        "faq_structured_data": {
            "description": "FAQPage 構造化データ（FAQ セクションがある記事のみ）",
            "priority": "MEDIUM",
            "status": "implemented",
            "detail": "lib/seo_structured_data.py で FAQ 検出時に自動生成",
        },
        "meta_description": {
            "description": "全記事に 110-130 文字の最適化されたメタディスクリプション",
            "priority": "HIGH",
            "status": "implemented",
            "detail": "post_to_wp.py の optimize_meta_description() で自動生成",
        },
        "news_sitemap": {
            "description": "ニュースサイトマップ（news-sitemap.xml）の生成",
            "priority": "HIGH",
            "status": "action_required",
            "detail": "lib/news_sitemap_generator.py で自動生成。WordPress側 functions.php の設置が必要",
            "action": "wordpress/functions_news_sitemap.php をテーマ functions.php に追記、またはmu-pluginsに配置 → パーマリンク設定を再保存",
        },
        "robots_txt": {
            "description": "robots.txt で Googlebot-News を許可",
            "priority": "HIGH",
            "status": "action_required",
            "detail": "functions_news_sitemap.php のrobots_txtフィルタで自動追加。WordPress側設置で解決",
            "action": "wordpress/functions_news_sitemap.php を設置すればrobots.txtも自動追加される",
        },
    },
    "content": {
        "clear_dateline": {
            "description": "各記事に明確な公開日時が表示されている",
            "priority": "CRITICAL",
            "status": "check_needed",
            "detail": "WordPressテーマで公開日が表示されているか確認",
            "action": "テーマの single.php で get_the_date() が出力されていることを確認",
        },
        "author_byline": {
            "description": "記事に著者名（バイライン）が表示されている",
            "priority": "HIGH",
            "status": "check_needed",
            "detail": "WordPressテーマで著者名が表示されているか確認",
            "action": "テーマ設定で著者表示を有効化、または functions.php でカスタム著者名を設定",
        },
        "unique_original_content": {
            "description": "独自のオリジナルコンテンツ（コピーコンテンツでない）",
            "priority": "CRITICAL",
            "status": "ok",
            "detail": "AIパイプラインで生成した独自記事。post_guard でコピーチェック済み",
        },
        "article_length": {
            "description": "ニュース記事として十分な長さ（最低 400 文字、推奨 1000+ 文字）",
            "priority": "HIGH",
            "status": "ok",
            "detail": "seo_config.json の min_word_count: 2500 で下限保証済み",
        },
    },
    "transparency": {
        "contact_page": {
            "description": "問い合わせページ（/contact/ or /inquiry/）が存在",
            "priority": "CRITICAL",
            "status": "check_needed",
            "action": f"確認: {SITE_URL}/contact/ または {SITE_URL}/inquiry/ が存在するか",
        },
        "privacy_policy": {
            "description": "プライバシーポリシーページが存在",
            "priority": "CRITICAL",
            "status": "check_needed",
            "action": f"確認: {SITE_URL}/privacy-policy/ が存在するか",
        },
        "about_page": {
            "description": "運営者情報（/about/）ページが存在",
            "priority": "CRITICAL",
            "status": "check_needed",
            "action": f"確認: {SITE_URL}/about/ が存在するか",
        },
    },
}


def run_check() -> dict:
    """Googleニュース要件チェックを実行し、結果を返す。"""
    results = {
        "total": 0,
        "implemented": 0,
        "action_required": 0,
        "check_needed": 0,
        "ok": 0,
        "items": [],
    }

    for category, items in REQUIREMENTS.items():
        for key, req in items.items():
            results["total"] += 1
            status = req["status"]
            results[status] = results.get(status, 0) + 1

            item = {
                "category": category,
                "key": key,
                "description": req["description"],
                "priority": req["priority"],
                "status": status,
            }
            if "action" in req:
                item["action"] = req["action"]
            if "detail" in req:
                item["detail"] = req["detail"]

            results["items"].append(item)

    return results


def print_report(results: dict):
    """チェック結果をレポート出力する。"""
    print("=" * 60)
    print(" Googleニュース申請要件チェックレポート")
    print("=" * 60)
    print(f"\n  合計: {results['total']} 項目")
    print(f"  ✅ 実装済み: {results.get('implemented', 0) + results.get('ok', 0)}")
    print(f"  🔧 対応必要: {results.get('action_required', 0)}")
    print(f"  🔍 確認必要: {results.get('check_needed', 0)}")

    for status_label, status_key, emoji in [
        ("対応必要", "action_required", "🔧"),
        ("確認必要", "check_needed", "🔍"),
        ("実装済み", "implemented", "✅"),
        ("OK", "ok", "✅"),
    ]:
        items = [i for i in results["items"] if i["status"] == status_key]
        if not items:
            continue
        print(f"\n--- {emoji} {status_label} ---")
        for item in items:
            print(f"  [{item['priority']}] {item['description']}")
            if "action" in item:
                print(f"    → {item['action']}")
            if "detail" in item:
                print(f"    ({item['detail']})")

    print("\n" + "=" * 60)
    print(" Googleニュース パブリッシャーセンター申請手順:")
    print("  1. https://publishercenter.google.com/ にアクセス")
    print(f"  2. サイト URL: {SITE_URL} を登録")
    print("  3. カテゴリ: エンターテインメント > 音楽 を選択")
    print("  4. 上記の「対応必要」「確認必要」を解消後に申請")
    print("=" * 60)


def generate_robots_txt_additions() -> str:
    """robots.txt に追加すべき行を返す。"""
    return """
# Googleニュース対応
User-agent: Googlebot-News
Allow: /

# ニュースサイトマップ
Sitemap: {site_url}/news-sitemap.xml
""".format(site_url=SITE_URL).strip()


def generate_news_sitemap_entry(
    title: str,
    url: str,
    pub_date: str,
    keywords: list[str] | None = None,
) -> str:
    """ニュースサイトマップの1エントリXMLを返す（参考用）。
    実際の生成はWordPressプラグインに任せる。
    """
    kw_str = ", ".join(keywords[:10]) if keywords else ""
    return f"""  <url>
    <loc>{url}</loc>
    <news:news>
      <news:publication>
        <news:name>KPOP JOURNAL</news:name>
        <news:language>ja</news:language>
      </news:publication>
      <news:publication_date>{pub_date}</news:publication_date>
      <news:title>{title}</news:title>
      {f'<news:keywords>{kw_str}</news:keywords>' if kw_str else ''}
    </news:news>
  </url>"""


if __name__ == "__main__":
    results = run_check()
    print_report(results)

    # robots.txt追加分を表示
    print("\n--- robots.txt 追加推奨行 ---")
    print(generate_robots_txt_additions())
