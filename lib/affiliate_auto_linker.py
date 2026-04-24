#!/usr/bin/env python3
"""
アフィリエイトリンク自動挿入エンジン

機能:
  1. Amazon アソシエイト: アルバム・グッズ・コスメ・食品の自動リンク挿入
  2. A8.net: 美容・ファッション・旅行・ライフスタイルの自動リンク
  3. Qoo10: K-POPグッズ・コスメ・韓国食品の自動リンク
  4. 記事のキーワード検出 → 最適ASPマッチング → リンク生成

使い方:
  python3 lib/affiliate_auto_linker.py inject [--limit 30] [--dry-run]
  python3 lib/affiliate_auto_linker.py inject-single POST_ID [--dry-run]
  python3 lib/affiliate_auto_linker.py report

パイプライン統合:
  post_to_wp.py 投稿後に inject-single で自動挿入（既存パイプラインに組込済み）
"""
from __future__ import annotations
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"
CONFIG = BASE / "config"

AFFILIATE_LOG = LOGS / "affiliate_links.jsonl"
REVENUE_CONFIG = CONFIG / "revenue_config.json"

WP = "https://www.kpopjournal.tokyo"
WP_AUTH = str(Path.home() / ".wp_auth")
JST = timezone(timedelta(hours=9))

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# アフィリエイト設定
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

AMAZON_TAG = os.environ.get("AMAZON_ASSOCIATE_TAG", "amazon0d7a-22")
A8NET_SITE_ID = os.environ.get("A8NET_SITE_ID", "")
QOO10_AFF_ID = os.environ.get("QOO10_AFFILIATE_ID", "")

# キーワード→商品カテゴリマッピング
AMAZON_KEYWORD_MAP = {
    "album": {
        "keywords": ["アルバム", "ミニアルバム", "フルアルバム", "EP", "リリース", "新曲", "CD", "初回限定"],
        "search_template": "https://www.amazon.co.jp/s?k={query}+CD+アルバム&tag={tag}",
        "cta_text": "🎵 Amazonでアルバムをチェック",
        "cta_description": "初回限定盤・特典付きはお早めに",
    },
    "photobook": {
        "keywords": ["写真集", "フォトブック", "PHOTOBOOK", "ファーストフォトブック"],
        "search_template": "https://www.amazon.co.jp/s?k={query}+写真集&tag={tag}",
        "cta_text": "📸 写真集をAmazonでチェック",
        "cta_description": "限定カバー・特典付きバージョンも",
    },
    "goods": {
        "keywords": ["グッズ", "公式グッズ", "ペンライト", "フォトカード", "トレカ", "ライトスティック"],
        "search_template": "https://www.amazon.co.jp/s?k={query}+公式グッズ&tag={tag}",
        "cta_text": "🎁 公式グッズをAmazonで探す",
        "cta_description": "公式ストア品・正規品を確認",
    },
    "dvd_bluray": {
        "keywords": ["DVD", "Blu-ray", "ブルーレイ", "コンサートDVD", "ライブDVD"],
        "search_template": "https://www.amazon.co.jp/s?k={query}+DVD+Blu-ray&tag={tag}",
        "cta_text": "📀 ライブDVD/Blu-rayをチェック",
        "cta_description": "ライブ映像を自宅で何度でも",
    },
    "cosme": {
        "keywords": ["コスメ", "化粧品", "スキンケア", "美容液", "ファンデーション", "リップ",
                     "クッションファンデ", "韓国コスメ", "Kビューティ", "保湿", "美白",
                     "CICA", "ナイアシンアミド", "レチノール"],
        "search_template": "https://www.amazon.co.jp/s?k={query}+韓国コスメ&tag={tag}",
        "cta_text": "💄 Amazonで韓国コスメをチェック",
        "cta_description": "人気の韓国コスメをお得に購入",
    },
    "food": {
        "keywords": ["韓国食品", "韓国料理", "韓国お菓子", "ラーメン", "トッポギ", "キムチ",
                     "チョコ", "チョコレート", "スナック", "お土産", "食品"],
        "search_template": "https://www.amazon.co.jp/s?k={query}+韓国&tag={tag}",
        "cta_text": "🍫 Amazonで韓国食品をチェック",
        "cta_description": "話題の韓国グルメをお取り寄せ",
    },
}

A8NET_KEYWORD_MAP = {
    "beauty": {
        "keywords": ["コスメ", "化粧品", "スキンケア", "美容液", "ファンデーション", "リップ",
                     "クッションファンデ", "韓国コスメ", "Kビューティ", "保湿", "美白",
                     "CICA", "ナイアシンアミド", "レチノール", "美容", "メイク"],
        "url_template": "https://px.a8.net/svt/ejp?a8mat={site_id}&query={query}",
        "cta_text": "💄 話題の韓国コスメを詳しく見る",
        "cta_description": "人気ブランドのスキンケア・メイクアイテム",
    },
    "fashion": {
        "keywords": ["ファッション", "着用", "コーデ", "私服", "ストリートスナップ",
                     "韓国ファッション", "K-FASHION", "トレンド"],
        "url_template": "https://px.a8.net/svt/ejp?a8mat={site_id}&query={query}",
        "cta_text": "👗 韓国ファッションをチェック",
        "cta_description": "アイドル着用ブランド・最新トレンド",
    },
    "travel": {
        "keywords": ["旅行", "ソウル", "韓国旅行", "渡韓", "ホテル", "航空券",
                     "聖地巡礼", "弘大", "明洞", "江南"],
        "url_template": "https://px.a8.net/svt/ejp?a8mat={site_id}&query={query}",
        "cta_text": "✈️ 韓国旅行プランをチェック",
        "cta_description": "聖地巡礼・ソウル旅行のお得なプラン",
    },
    "lifestyle": {
        "keywords": ["ライフスタイル", "インテリア", "雑貨", "韓国雑貨", "カフェ",
                     "ダイエット", "健康", "ヨガ", "ピラティス", "韓方"],
        "url_template": "https://px.a8.net/svt/ejp?a8mat={site_id}&query={query}",
        "cta_text": "🏠 韓国ライフスタイルグッズを見る",
        "cta_description": "韓国で人気のライフスタイルアイテム",
    },
}

QOO10_KEYWORD_MAP = {
    "kpop_goods": {
        "keywords": ["グッズ", "公式グッズ", "ペンライト", "フォトカード", "トレカ",
                     "ライトスティック", "K-POP", "アイドル", "推し活"],
        "search_template": "https://www.qoo10.jp/s/{query}+K-POP+グッズ",
        "cta_text": "🎁 Qoo10でK-POPグッズを探す",
        "cta_description": "公式グッズ・限定アイテムをお得にGET",
    },
    "cosme": {
        "keywords": ["コスメ", "化粧品", "スキンケア", "美容液", "リップ",
                     "クッションファンデ", "韓国コスメ", "Kビューティ"],
        "search_template": "https://www.qoo10.jp/s/{query}+韓国コスメ",
        "cta_text": "💄 Qoo10で韓国コスメをチェック",
        "cta_description": "メガ割でお得に韓国コスメを購入",
    },
    "korean_food": {
        "keywords": ["韓国食品", "韓国料理", "韓国お菓子", "ラーメン", "トッポギ",
                     "キムチ", "チョコ", "チョコレート", "スナック", "食品", "お土産",
                     "開運グッズ", "韓国雑貨"],
        "search_template": "https://www.qoo10.jp/s/{query}+韓国",
        "cta_text": "🛒 Qoo10で韓国アイテムを探す",
        "cta_description": "韓国の人気アイテムをお得に購入",
    },
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# キーワード検出・マッチング
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def extract_artist_name(title: str) -> str:
    """タイトルからアーティスト名を抽出"""
    artists = [
        "BTS", "BLACKPINK", "TWICE", "aespa", "NewJeans", "IVE",
        "LE SSERAFIM", "Stray Kids", "SEVENTEEN", "ENHYPEN", "TXT",
        "NCT", "EXO", "BIGBANG", "G-DRAGON", "ATEEZ", "ITZY",
        "BABYMONSTER", "RIIZE", "ILLIT", "NMIXX", "TREASURE",
        "(G)I-DLE", "Red Velvet", "SHINee", "MAMAMOO", "GOT7",
        "ZEROBASEONE", "BOYNEXTDOOR", "PLAVE", "XG",
    ]
    for artist in artists:
        if artist.lower() in title.lower():
            return artist
    return ""


def detect_affiliate_categories(title: str, content: str) -> list[dict]:
    """記事タイトル+本文からアフィリエイトカテゴリを検出"""
    text = (title + " " + re.sub(r"<[^>]+>", "", content)).lower()
    matches = []

    # Amazon
    for cat_key, cat in AMAZON_KEYWORD_MAP.items():
        hit_count = sum(1 for kw in cat["keywords"] if kw.lower() in text)
        if hit_count >= 1:
            matches.append({
                "provider": "amazon",
                "category": cat_key,
                "hit_count": hit_count,
                "config": cat,
            })

    # A8.net
    for cat_key, cat in A8NET_KEYWORD_MAP.items():
        hit_count = sum(1 for kw in cat["keywords"] if kw.lower() in text)
        if hit_count >= 1:
            matches.append({
                "provider": "a8net",
                "category": cat_key,
                "hit_count": hit_count,
                "config": cat,
            })

    # Qoo10
    for cat_key, cat in QOO10_KEYWORD_MAP.items():
        hit_count = sum(1 for kw in cat["keywords"] if kw.lower() in text)
        if hit_count >= 1:
            matches.append({
                "provider": "qoo10",
                "category": cat_key,
                "hit_count": hit_count,
                "config": cat,
            })

    # ヒット数でソート（最も関連性の高いものを優先）
    matches.sort(key=lambda x: x["hit_count"], reverse=True)
    return matches[:3]  # 最大3種類


def generate_affiliate_html(match: dict, artist: str, title: str) -> str:
    """アフィリエイトCTAブロックのHTML生成"""
    provider = match["provider"]
    config = match["config"]
    query = artist if artist else title[:20]

    if provider == "amazon":
        url = config["search_template"].format(query=query, tag=AMAZON_TAG)
        color = "#FF9900"
        bg = "#FFF8F0"
        border = "#FF9900"
        pr_label = "※Amazon アソシエイトリンクを含みます"
    elif provider == "a8net":
        url = config["url_template"].format(site_id=A8NET_SITE_ID, query=query)
        color = "#00A1E9"
        bg = "#F0F8FF"
        border = "#00A1E9"
        pr_label = "※アフィリエイトリンクを含みます（A8.net）"
    elif provider == "qoo10":
        url = config["search_template"].format(query=query)
        if QOO10_AFF_ID:
            sep = "&" if "?" in url else "?"
            url += f"{sep}af={QOO10_AFF_ID}"
        color = "#E60033"
        bg = "#FFF5F7"
        border = "#E60033"
        pr_label = "※Qoo10 アフィリエイトリンクを含みます"
    else:
        return ""

    return f"""<div class="affiliate-cta affiliate-{provider}" data-affiliate="{provider}-{match['category']}" style="border:2px solid {border};padding:20px 24px;margin:28px 0;border-radius:12px;background:{bg};">
<p style="font-size:1.1em;font-weight:bold;margin:0 0 8px;color:{color};">{config['cta_text']}</p>
<p style="margin:0 0 14px;color:#555;line-height:1.7;">{config['cta_description']}</p>
<a href="{url}" target="_blank" rel="noopener sponsored nofollow" style="display:inline-block;background:{color};color:#fff;padding:11px 28px;border-radius:8px;text-decoration:none;font-weight:bold;font-size:1em;">{config['cta_text'].split(' ', 1)[-1]} →</a>
<p style="font-size:0.75em;color:#999;margin:8px 0 0;">{pr_label}</p>
</div>"""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 記事への挿入
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def has_affiliate_links(content: str) -> bool:
    """既にアフィリエイトCTAが挿入済みか"""
    return "affiliate-cta" in content or f"tag={AMAZON_TAG}" in content or "qoo10.jp" in content or "a8.net" in content


def inject_affiliate_links(content: str, matches: list[dict], artist: str, title: str) -> str:
    """記事本文にアフィリエイトリンクを挿入"""
    if has_affiliate_links(content):
        return content

    if not matches:
        return content

    h2_positions = [m.start() for m in re.finditer(r"<h2\b", content, re.IGNORECASE)]

    insertions = []

    # 最も関連性の高い1つを記事中盤に
    primary_html = generate_affiliate_html(matches[0], artist, title)
    if h2_positions and len(h2_positions) >= 3:
        mid_idx = len(h2_positions) // 2
        insertions.append((h2_positions[mid_idx], primary_html))
    elif h2_positions:
        insertions.append((h2_positions[-1], primary_html))

    # 2番目があれば記事末尾に
    if len(matches) >= 2:
        secondary_html = generate_affiliate_html(matches[1], artist, title)
        insertions.append((len(content), secondary_html))

    # 後ろから挿入
    result = content
    for pos, html in sorted(insertions, key=lambda x: x[0], reverse=True):
        result = result[:pos] + "\n" + html + "\n" + result[pos:]

    return result


def inject_single(post_id: int, dry_run: bool = False) -> bool:
    """単一記事にアフィリエイトリンク挿入"""
    cmd = ["curl", "-s", f"{WP}/wp-json/wp/v2/posts/{post_id}?context=edit", "-K", WP_AUTH]
    try:
        post = json.loads(subprocess.check_output(cmd, timeout=15))
    except Exception as e:
        print(f"  ⚠️ WP取得失敗: {e}")
        return False

    title = post.get("title", {}).get("raw", "") or post.get("title", {}).get("rendered", "")
    content = post.get("content", {}).get("raw", "") or post.get("content", {}).get("rendered", "")

    if has_affiliate_links(content):
        print(f"  → #{post_id} アフィリエイトCTA既存 → スキップ")
        return False

    artist = extract_artist_name(title)
    matches = detect_affiliate_categories(title, content)

    if not matches:
        print(f"  → #{post_id} アフィリエイト対象外")
        return False

    new_content = inject_affiliate_links(content, matches, artist, title)
    if new_content == content:
        return False

    providers = [m["provider"] + "/" + m["category"] for m in matches]
    print(f"  → #{post_id} [{', '.join(providers)}] {title[:40]}...")

    if dry_run:
        print(f"    [DRY-RUN] 挿入予定")
        return True

    update_cmd = [
        "curl", "-s", "-X", "POST",
        f"{WP}/wp-json/wp/v2/posts/{post_id}",
        "-K", WP_AUTH,
        "-H", "Content-Type: application/json",
        "-d", json.dumps({"content": new_content}, ensure_ascii=False),
    ]
    try:
        resp = json.loads(subprocess.check_output(update_cmd, timeout=30))
        if resp.get("id"):
            LOGS.mkdir(exist_ok=True)
            with open(AFFILIATE_LOG, "a") as f:
                f.write(json.dumps({
                    "ts": datetime.now(JST).isoformat(),
                    "post_id": post_id,
                    "title": title[:60],
                    "artist": artist,
                    "providers": providers,
                }, ensure_ascii=False) + "\n")
            return True
    except Exception as e:
        print(f"    ⚠️ 更新失敗: {e}")

    return False


def inject_batch(limit: int = 30, dry_run: bool = False) -> int:
    """バッチでアフィリエイトリンク挿入"""
    print(f"=== アフィリエイトリンク自動挿入 (limit={limit}) ===")

    cmd = ["curl", "-s",
           f"{WP}/wp-json/wp/v2/posts?per_page={limit}&orderby=date&order=desc&_fields=id,title,content,categories",
           "-K", WP_AUTH]
    try:
        posts = json.loads(subprocess.check_output(cmd, timeout=30))
    except Exception as e:
        print(f"  ❌ WP API エラー: {e}")
        return 0

    count = 0
    for post in posts:
        if inject_single(post["id"], dry_run):
            count += 1

    print(f"\n  合計: {count}件{'挿入予定' if dry_run else '挿入完了'}")
    return count


def report():
    """アフィリエイトリンク挿入レポート"""
    print("=== アフィリエイトリンクレポート ===")
    if not AFFILIATE_LOG.exists():
        print("  ⚠️ ログなし")
        return

    from collections import Counter
    provider_count = Counter()
    total = 0

    with open(AFFILIATE_LOG) as f:
        for line in f:
            if not line.strip():
                continue
            entry = json.loads(line)
            total += 1
            for p in entry.get("providers", []):
                provider_count[p] += 1

    print(f"  総挿入数: {total}件")
    print(f"  プロバイダ別:")
    for p, c in provider_count.most_common():
        print(f"    {p}: {c}件")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# メイン
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def main():
    parser = argparse.ArgumentParser(description="アフィリエイト自動リンク挿入")
    sub = parser.add_subparsers(dest="command")

    p_inject = sub.add_parser("inject", help="バッチ挿入")
    p_inject.add_argument("--limit", type=int, default=30)
    p_inject.add_argument("--days", type=int, default=30, help="対象期間（日数）")
    p_inject.add_argument("--dry-run", action="store_true")

    p_single = sub.add_parser("inject-single", help="単一記事挿入")
    p_single.add_argument("post_id", type=int)
    p_single.add_argument("--dry-run", action="store_true")

    sub.add_parser("report", help="レポート")

    args = parser.parse_args()

    if args.command == "inject":
        inject_batch(limit=args.limit, dry_run=args.dry_run)
    elif args.command == "inject-single":
        inject_single(args.post_id, dry_run=args.dry_run)
    elif args.command == "report":
        report()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
