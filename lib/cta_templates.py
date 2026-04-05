#!/usr/bin/env python3
"""
CTA Template Engine - 記事タイプ × ASP別のCTAブロック生成
収益本部（ニャース/カイリュー）管轄
"""
import json
import os
import sys

CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config")


def load_revenue_config():
    with open(os.path.join(CONFIG_DIR, "revenue_config.json"), encoding="utf-8") as f:
        return json.load(f)


# ── CTA HTML テンプレート ──

TEMPLATES = {
    "product_review": """<div class="revenue-cta cta-product" style="border:2px solid #ff4d6d;padding:24px;margin:32px 0;border-radius:12px;background:linear-gradient(135deg,#fff5f7,#fff0f3);">
<p style="font-size:1.2em;font-weight:bold;margin:0 0 8px;color:#ff4d6d;">{headline}</p>
<p style="margin:0 0 16px;color:#555;line-height:1.8;">{description}</p>
<a href="{url}" target="_blank" rel="noopener sponsored" style="display:inline-block;background:#ff4d6d;color:#fff;padding:12px 32px;border-radius:8px;text-decoration:none;font-weight:bold;font-size:1.05em;">{button_text}</a>
<p style="font-size:0.8em;color:#999;margin:8px 0 0;">※広告・PRを含みます</p>
</div>""",

    "product_link": """<div class="revenue-cta cta-amazon" style="border:1px solid #ddd;padding:20px;margin:24px 0;border-radius:8px;background:#fafafa;">
<p style="font-weight:bold;margin:0 0 12px;">{headline}</p>
<ul style="margin:0 0 16px;padding-left:20px;line-height:2;">
{product_list}
</ul>
<p style="font-size:0.8em;color:#999;margin:0;">※リンクにはアフィリエイトが含まれます</p>
</div>""",

    "booking_link": """<div class="revenue-cta cta-booking" style="border:2px solid #4a90d9;padding:24px;margin:32px 0;border-radius:12px;background:linear-gradient(135deg,#f0f7ff,#e8f2ff);">
<p style="font-size:1.1em;font-weight:bold;margin:0 0 8px;color:#2c5282;">{headline}</p>
<p style="margin:0 0 16px;color:#555;line-height:1.8;">{description}</p>
<a href="{url}" target="_blank" rel="noopener sponsored" style="display:inline-block;background:#4a90d9;color:#fff;padding:12px 32px;border-radius:8px;text-decoration:none;font-weight:bold;">{button_text}</a>
<p style="font-size:0.8em;color:#999;margin:8px 0 0;">※広告・PRを含みます</p>
</div>""",

    "internal_revenue_link": """<div class="revenue-cta cta-internal" style="border:2px solid #ff4d6d;padding:20px;margin:32px 0;border-radius:12px;background:#fff5f7;">
<p style="font-size:1.1em;font-weight:bold;margin:0 0 12px;">📌 あわせて読みたい</p>
<ul style="margin:0;padding-left:20px;line-height:2;">{link_list}</ul>
</div>""",

    "comparison_table": """<div class="revenue-cta cta-compare" style="border:1px solid #e2e8f0;padding:24px;margin:32px 0;border-radius:12px;background:#fff;">
<p style="font-size:1.2em;font-weight:bold;margin:0 0 16px;">{headline}</p>
<table style="width:100%;border-collapse:collapse;margin:0 0 16px;">
<thead><tr style="background:#f7fafc;">{table_headers}</tr></thead>
<tbody>{table_rows}</tbody>
</table>
<p style="font-size:0.8em;color:#999;margin:0;">※価格は{date}時点。リンクにはアフィリエイトが含まれます</p>
</div>""",
}


def generate_cta(article_type, categories, title, site_url="https://www.kpopjournal.tokyo"):
    """記事タイプとカテゴリからCTAブロックを生成"""
    config = load_revenue_config()
    cv_design = config["article_type_cv_design"].get(article_type, config["article_type_cv_design"]["flow"])

    cta_blocks = []
    cta_count = cv_design["cta_count"]

    # ASPマッチング
    matched_asp = None
    for asp_key, asp in config["asp_providers"].items():
        if any(cat in asp["priority_categories"] for cat in categories):
            matched_asp = (asp_key, asp)
            break

    # 収益記事: ASP直接CTA
    if article_type == "revenue" and matched_asp:
        asp_key, asp = matched_asp
        tmpl = TEMPLATES.get(asp["cta_style"], TEMPLATES["product_review"])
        cta_blocks.append(tmpl.format(
            headline=_generate_headline(title, asp_key),
            description=_generate_description(asp_key, categories),
            url="{affiliate_url}",
            button_text=_generate_button_text(asp_key),
            product_list="",
            link_list="",
        ))

    # 資産記事: 内部リンク型CTA + 軽めアフィリエイト
    elif article_type == "asset":
        cta_blocks.append(TEMPLATES["internal_revenue_link"].format(
            link_list=_generate_internal_links(categories, site_url)
        ))
        if matched_asp and cta_count >= 2:
            asp_key, asp = matched_asp
            tmpl = TEMPLATES.get(asp["cta_style"], TEMPLATES["product_link"])
            cta_blocks.append(tmpl.format(
                headline=_generate_headline(title, asp_key),
                description=_generate_description(asp_key, categories),
                url="{affiliate_url}",
                button_text=_generate_button_text(asp_key),
                product_list="",
                link_list="",
            ))

    # フロー記事: 内部リンクのみ
    else:
        cta_blocks.append(TEMPLATES["internal_revenue_link"].format(
            link_list=_generate_internal_links(categories, site_url)
        ))

    return "\n\n".join(cta_blocks[:cta_count])


def _generate_headline(title, asp_key):
    headlines = {
        "a8": "✨ 記事で紹介したアイテムをチェック",
        "amazon": "🛒 関連グッズ・アルバムをチェック",
        "rakuten": "🏨 関連の旅行・チケット情報",
    }
    return headlines.get(asp_key, "📌 関連情報をチェック")


def _generate_description(asp_key, categories):
    descs = {
        "a8": "韓国で人気のスキンケア・コスメアイテムを厳選。実際の口コミと合わせてチェックできます。",
        "amazon": "最新アルバム・公式グッズをAmazonでチェック。プライム対象商品なら翌日届きます。",
        "rakuten": "お得なプラン・早割チケットをチェック。楽天ポイントも貯まります。",
    }
    return descs.get(asp_key, "")


def _generate_button_text(asp_key):
    buttons = {
        "a8": "詳細をチェックする →",
        "amazon": "Amazonで見る →",
        "rakuten": "楽天で予約する →",
    }
    return buttons.get(asp_key, "詳しく見る →")


def _generate_internal_links(categories, site_url):
    """カテゴリベースの内部リンク生成"""
    link_map = {
        5: ("/kpop-events-japan-2025-list/", "K-POPライブ・イベント総まとめ"),
        3: ("/kpop-comeback-schedule-2026/", "K-POPカムバックスケジュール"),
        12: ("/korean-skincare-routine-2026/", "韓国スキンケアルーティン完全ガイド"),
        11: ("/seoul-travel-guide-2026/", "ソウル旅行完全ガイド"),
        71: ("/kpop-chart-weekly/", "K-POPチャート週間ランキング"),
        8: ("/korean-drama-streaming-guide/", "韓国ドラマ配信ガイド"),
    }
    links = []
    for cat in categories:
        if cat in link_map:
            slug, text = link_map[cat]
            links.append(f'<li><a href="{site_url}{slug}" style="color:#ff4d6d;font-weight:bold;">{text}</a></li>')
    if not links:
        links.append(f'<li><a href="{site_url}/kpop-events-japan-2025-list/" style="color:#ff4d6d;font-weight:bold;">K-POPライブ・イベント総まとめ</a></li>')
    return "\n".join(links[:3])


def get_cv_metrics(article_type):
    """記事タイプ別のCV期待値を返す"""
    config = load_revenue_config()
    design = config["article_type_cv_design"].get(article_type, {})
    return {
        "expected_cvr": design.get("expected_cvr", 0),
        "expected_revenue_per_pv": design.get("expected_revenue_per_pv", 0),
        "cta_count": design.get("cta_count", 1),
    }


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: cta_templates.py <article_type> <category_ids_comma> [title]")
        sys.exit(1)

    a_type = sys.argv[1]
    cats = [int(x) for x in sys.argv[2].split(",") if x.strip()]
    title = sys.argv[3] if len(sys.argv) > 3 else ""
    print(generate_cta(a_type, cats, title))
