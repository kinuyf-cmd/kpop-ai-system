#!/usr/bin/env python3
"""
seo_structured_data.py — SEO構造化データ自動生成モジュール

Phase 0-SEO 緊急対策:
  1. Article Schema (JSON-LD) — 全記事に挿入
  2. FAQPage Schema — FAQ セクション検出時に自動生成
  3. BreadcrumbList Schema — パンくずリスト構造化データ
  4. メタディスクリプション最適化ヘルパー
  5. Googleニュース対応メタタグ生成

挿入先: html_postprocess.py の最終段で呼び出す
"""

import json
import re
from datetime import datetime


SITE_NAME = "KPOP JOURNAL"
SITE_URL = "https://www.kpopjournal.tokyo"
SITE_LANGUAGE = "ja"
LOGO_URL = f"{SITE_URL}/wp-content/uploads/kpop-journal-logo.png"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. Article Schema
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def generate_article_schema(
    title: str,
    url: str = "",
    description: str = "",
    date_published: str = "",
    date_modified: str = "",
    image_url: str = "",
    article_section: str = "K-POP",
) -> dict:
    """Article schema (JSON-LD) を生成する。

    WordPressのAIOSEOプラグインと競合しないよう、
    プラグインが未生成のフィールドのみを補完する設計。
    """
    now_iso = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+09:00")
    schema = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": title[:110],  # Google推奨: 110文字以内
        "name": title,
        "articleSection": article_section,
        "inLanguage": SITE_LANGUAGE,
        "datePublished": date_published or now_iso,
        "dateModified": date_modified or now_iso,
        "author": {
            "@type": "Organization",
            "name": SITE_NAME,
            "url": SITE_URL,
        },
        "publisher": {
            "@type": "Organization",
            "name": SITE_NAME,
            "url": SITE_URL,
            "logo": {
                "@type": "ImageObject",
                "url": LOGO_URL,
            },
        },
        "mainEntityOfPage": {
            "@type": "WebPage",
            "@id": url or SITE_URL,
        },
    }
    if description:
        schema["description"] = description[:200]
    if image_url:
        schema["image"] = {
            "@type": "ImageObject",
            "url": image_url,
        }
    return schema


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. FAQ Schema
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def extract_faq_pairs(body: str) -> list[dict]:
    """本文HTMLからFAQ（質問＋回答）ペアを抽出する。

    検出パターン:
      - <h2>よくある質問</h2> or <h3>Q. ...</h3><p>A. ...</p>
      - <dt>質問</dt><dd>回答</dd>
      - <strong>Q.</strong> ... <strong>A.</strong> ...
    """
    pairs = []

    # パターン1: h3 Q/A 形式
    qa_h3 = re.findall(
        r'<h3[^>]*>\s*Q[\.\s:：]?\s*(.*?)\s*</h3>\s*'
        r'(?:<p[^>]*>)?\s*A[\.\s:：]?\s*(.*?)\s*(?:</p>)?'
        r'(?=<h[23]|<div|$)',
        body, re.DOTALL | re.IGNORECASE,
    )
    for q, a in qa_h3:
        q_clean = re.sub(r'<[^>]+>', '', q).strip()
        a_clean = re.sub(r'<[^>]+>', '', a).strip()
        if q_clean and a_clean and len(a_clean) >= 10:
            pairs.append({"question": q_clean, "answer": a_clean})

    # パターン2: dt/dd 形式
    qa_dl = re.findall(
        r'<dt[^>]*>\s*(.*?)\s*</dt>\s*<dd[^>]*>\s*(.*?)\s*</dd>',
        body, re.DOTALL,
    )
    for q, a in qa_dl:
        q_clean = re.sub(r'<[^>]+>', '', q).strip()
        a_clean = re.sub(r'<[^>]+>', '', a).strip()
        if q_clean and a_clean and len(a_clean) >= 10:
            pairs.append({"question": q_clean, "answer": a_clean})

    # パターン3: 「よくある質問」セクション内の p タグベース Q/A
    faq_section = re.search(
        r'<h2[^>]*>[^<]*(?:よくある質問|FAQ|Q\s*&\s*A)[^<]*</h2>(.*?)(?=<h2|$)',
        body, re.DOTALL | re.IGNORECASE,
    )
    if faq_section:
        section_html = faq_section.group(1)
        # <p><strong>Q.</strong>質問</p><p>回答</p> パターン
        qa_strong = re.findall(
            r'<p[^>]*>\s*(?:<strong>)?\s*Q[\.\s:：]?\s*(?:</strong>)?\s*(.*?)\s*</p>'
            r'\s*<p[^>]*>\s*(?:<strong>)?\s*A[\.\s:：]?\s*(?:</strong>)?\s*(.*?)\s*</p>',
            section_html, re.DOTALL | re.IGNORECASE,
        )
        for q, a in qa_strong:
            q_clean = re.sub(r'<[^>]+>', '', q).strip()
            a_clean = re.sub(r'<[^>]+>', '', a).strip()
            if q_clean and a_clean and len(a_clean) >= 10:
                pairs.append({"question": q_clean, "answer": a_clean})

    # 重複除去（質問テキストベース）
    seen = set()
    unique = []
    for p in pairs:
        if p["question"] not in seen:
            seen.add(p["question"])
            unique.append(p)
    return unique


def generate_faq_schema(faq_pairs: list[dict]) -> dict | None:
    """FAQPage schema を生成する。ペアが無ければ None。"""
    if not faq_pairs:
        return None
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": p["question"],
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": p["answer"],
                },
            }
            for p in faq_pairs
        ],
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. BreadcrumbList Schema
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def generate_breadcrumb_schema(
    title: str,
    url: str = "",
    category_name: str = "K-POP",
    category_slug: str = "kpop",
) -> dict:
    """BreadcrumbList schema を生成する。"""
    items = [
        {
            "@type": "ListItem",
            "position": 1,
            "name": "ホーム",
            "item": SITE_URL,
        },
        {
            "@type": "ListItem",
            "position": 2,
            "name": category_name,
            "item": f"{SITE_URL}/category/{category_slug}/",
        },
        {
            "@type": "ListItem",
            "position": 3,
            "name": title[:60],
        },
    ]
    # 最終アイテムに URL があれば付与
    if url:
        items[-1]["item"] = url

    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": items,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 4. メタディスクリプション最適化
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def optimize_meta_description(
    title: str,
    body_plain: str,
    min_len: int = 110,
    max_len: int = 130,
) -> str:
    """SEO最適化されたメタディスクリプションを生成する。

    ルール:
      - タイトルのコアキーワードを冒頭に含める
      - 本文コピー禁止（meta_desc_copied エラー再発防止）
      - 110-130文字に収める
      - アクション喚起語を含める
    """
    # タイトルからコアキーワード抽出（括弧・記号除去）
    core = re.sub(r'[【】「」『』\[\]（）()｜|]', '', title).strip()
    core_short = core[:30] if len(core) > 30 else core

    # 本文の正規化（改行・連続空白を除去）
    body_plain = re.sub(r'\s+', '', body_plain)

    # 本文から文を抽出
    sentences = [s.strip() for s in re.split(r'(?<=[。！？])', body_plain) if len(s.strip()) >= 10]
    # 冒頭の文はexcerptと被る可能性があるためスキップ
    mid_sentences = sentences[2:8] if len(sentences) > 4 else sentences[1:4]
    if not mid_sentences:
        mid_sentences = sentences[:2]

    # キーワードリッチな文を選ぶ（数字・固有名詞を含むもの優先）
    best_fragment = ""
    for s in mid_sentences:
        if re.search(r'\d', s) or re.search(r'[A-Z]{2,}', s):
            best_fragment = s[:60].rstrip('。！？、')
            break
    if not best_fragment and mid_sentences:
        best_fragment = mid_sentences[0][:60].rstrip('。！？、')
    if not best_fragment:
        best_fragment = body_plain[:60].rstrip('。！？、')

    # 追加フラグメントを準備（best_fragment以外の文）
    extra_fragments = []
    for s in mid_sentences:
        frag = s[:50].rstrip('。！？、')
        if frag and frag != best_fragment:
            extra_fragments.append(frag)
    # mid_sentences 以外からも補充
    for s in sentences:
        frag = s[:50].rstrip('。！？、')
        if frag and frag != best_fragment and frag not in extra_fragments:
            extra_fragments.append(frag)
            if len(extra_fragments) >= 4:
                break

    suffix = "K-POPファン必見の最新情報・詳細をお届けします。"

    # 段階的にパーツを追加して 110-130 文字レンジに収める
    base = f"{core_short}を徹底解説。{best_fragment}"

    # パーツを追加しながらレンジに入るまで積む
    for extra in extra_fragments:
        candidate = f"{base}。{extra}"
        # suffix付きで上限を超えそうなら止める
        if len(candidate) + len(suffix) + 1 > max_len:
            break
        base = candidate

    desc = f"{base}。{suffix}"

    if len(desc) > max_len:
        desc = desc[:max_len - 3] + "..."

    return desc


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 5. Googleニュース対応メタタグ
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def generate_news_meta_tags(
    title: str,
    keywords: list[str] | None = None,
) -> str:
    """Googleニュースに必要なメタタグHTMLを生成する。

    <head>内挿入用（WordPressテーマ/プラグインで挿入想定）ではなく、
    投稿本文の先頭にコメントとして埋め込み、テーマ側のfunctions.phpで読み取る設計。
    """
    kw = keywords or _extract_keywords_from_title(title)
    kw_str = ", ".join(kw[:10])

    return (
        f'<!-- google-news-meta: keywords="{kw_str}" -->'
    )


def generate_news_article_schema(
    title: str,
    url: str = "",
    description: str = "",
    date_published: str = "",
    image_url: str = "",
) -> dict:
    """NewsArticle schema（Googleニュース用）を生成する。"""
    now_iso = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+09:00")
    return {
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "headline": title[:110],
        "name": title,
        "datePublished": date_published or now_iso,
        "dateModified": date_published or now_iso,
        "description": description[:200] if description else "",
        "inLanguage": SITE_LANGUAGE,
        "author": {
            "@type": "Organization",
            "name": SITE_NAME,
            "url": SITE_URL,
        },
        "publisher": {
            "@type": "Organization",
            "name": SITE_NAME,
            "url": SITE_URL,
            "logo": {
                "@type": "ImageObject",
                "url": LOGO_URL,
            },
        },
        "mainEntityOfPage": {
            "@type": "WebPage",
            "@id": url or SITE_URL,
        },
        "image": image_url or "",
    }


def _extract_keywords_from_title(title: str) -> list[str]:
    """タイトルからキーワードを抽出する（簡易版）。"""
    # 括弧内と本体を分離
    keywords = []
    # 【】内
    brackets = re.findall(r'[【「『](.*?)[】」』]', title)
    for b in brackets:
        keywords.extend(re.split(r'[・/／]', b))
    # 本体部分のキーワード
    main = re.sub(r'[【】「」『』\[\]（）()]', ' ', title)
    # 英字の固有名詞（2文字以上）
    keywords.extend(re.findall(r'[A-Za-z]{2,}', main))
    # カタカナ連続（3文字以上）
    keywords.extend(re.findall(r'[\u30A0-\u30FF]{3,}', main))
    # 重複除去
    seen = set()
    unique = []
    for k in keywords:
        k = k.strip()
        if k and k not in seen:
            seen.add(k)
            unique.append(k)
    return unique


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 統合: HTML本文に全構造化データを挿入
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def inject_structured_data(
    body: str,
    title: str,
    url: str = "",
    slug: str = "",
    category_name: str = "K-POP",
    category_slug: str = "kpop",
    description: str = "",
    image_url: str = "",
    is_news: bool = False,
) -> tuple[str, list[str]]:
    """本文HTMLの末尾に構造化データ（JSON-LD）を一括挿入する。

    既に挿入済み（schema.org を含むscriptタグがある）の場合はスキップ。

    Returns:
        (body, log_messages)
    """
    log = []

    # 既存の構造化データチェック
    if 'application/ld+json' in body:
        log.append("構造化データ: 既存JSON-LDあり → スキップ")
        return body, log

    schemas = []

    # 1. Article or NewsArticle schema
    if is_news:
        schemas.append(generate_news_article_schema(
            title=title, url=url, description=description, image_url=image_url,
        ))
        log.append("✅ NewsArticle schema 生成")
    else:
        schemas.append(generate_article_schema(
            title=title, url=url, description=description, image_url=image_url,
        ))
        log.append("✅ Article schema 生成")

    # 2. FAQ schema（本文にFAQがあれば）
    faq_pairs = extract_faq_pairs(body)
    if faq_pairs:
        faq_schema = generate_faq_schema(faq_pairs)
        if faq_schema:
            schemas.append(faq_schema)
            log.append(f"✅ FAQPage schema 生成 ({len(faq_pairs)}問)")

    # 3. Breadcrumb schema
    schemas.append(generate_breadcrumb_schema(
        title=title, url=url,
        category_name=category_name, category_slug=category_slug,
    ))
    log.append("✅ BreadcrumbList schema 生成")

    # 4. Googleニュースメタタグ
    news_meta = generate_news_meta_tags(title)

    # JSON-LD scriptタグを生成
    ld_blocks = []
    for schema in schemas:
        ld_json = json.dumps(schema, ensure_ascii=False, indent=None, separators=(',', ':'))
        ld_blocks.append(f'<script type="application/ld+json">{ld_json}</script>')

    structured_html = "\n".join(ld_blocks)

    # 本文末尾に挿入
    body = body.rstrip() + "\n" + news_meta + "\n" + structured_html + "\n"

    return body, log


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# カテゴリ推定ヘルパー
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# タイトルからカテゴリを推定するマッピング
CATEGORY_MAP = {
    "BTS": ("BTS", "bts"),
    "防弾少年団": ("BTS", "bts"),
    "BLACKPINK": ("BLACKPINK", "blackpink"),
    "ブラックピンク": ("BLACKPINK", "blackpink"),
    "TWICE": ("TWICE", "twice"),
    "トゥワイス": ("TWICE", "twice"),
    "aespa": ("aespa", "aespa"),
    "エスパ": ("aespa", "aespa"),
    "NewJeans": ("NewJeans", "newjeans"),
    "ニュージーンズ": ("NewJeans", "newjeans"),
    "SEVENTEEN": ("SEVENTEEN", "seventeen"),
    "セブチ": ("SEVENTEEN", "seventeen"),
    "Stray Kids": ("Stray Kids", "stray-kids"),
    "スキズ": ("Stray Kids", "stray-kids"),
    "IVE": ("IVE", "ive"),
    "アイヴ": ("IVE", "ive"),
    "LE SSERAFIM": ("LE SSERAFIM", "le-sserafim"),
    "ルセラフィム": ("LE SSERAFIM", "le-sserafim"),
    "ILLIT": ("ILLIT", "illit"),
    "ENHYPEN": ("ENHYPEN", "enhypen"),
    "エナイプン": ("ENHYPEN", "enhypen"),
    "NCT": ("NCT", "nct"),
    "ATEEZ": ("ATEEZ", "ateez"),
    "TREASURE": ("TREASURE", "treasure"),
    "EXO": ("EXO", "exo"),
}


def guess_category_from_title(title: str) -> tuple[str, str]:
    """タイトルからカテゴリ名とスラッグを推定する。"""
    for keyword, (name, slug) in CATEGORY_MAP.items():
        if keyword.lower() in title.lower():
            return name, slug
    return "K-POP", "kpop"
