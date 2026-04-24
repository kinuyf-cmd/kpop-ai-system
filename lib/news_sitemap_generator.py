#!/usr/bin/env python3
"""
news_sitemap_generator.py — Googleニュースサイトマップ生成（AIOSEO Pro不要）

AIOSEOの無料版にはニュースサイトマップ機能がないため、
WordPress REST API から直近48時間の記事を取得し、
Google News Sitemap 仕様に準拠した XML を生成する。

2つの動作モード:
  1. --upload : 生成したXMLをWordPressにアップロード（REST APIのメディアエンドポイント経由）
  2. --local  : ローカルに保存のみ（デバッグ用）

cron 登録例（1時間ごとに更新）:
  0 * * * * cd ~/kpop-ai-system && python3 lib/news_sitemap_generator.py --upload >> logs/news_sitemap.log 2>&1

Google News Sitemap 仕様:
  - 直近48時間以内に公開された記事のみ含める
  - 最大1000件
  - news:publication に媒体名と言語コード
  - news:publication_date は W3C Datetime 形式
  - news:title にタイトル（HTMLエンティティ不可）
"""

import json
import os
import re
import sys
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "lib"))

# ── 設定 ──

SITE_URL = os.environ.get("SITE_URL", "https://www.kpopjournal.tokyo")
WP_API = f"{SITE_URL}/wp-json/wp/v2"
PUBLICATION_NAME = "KPOP JOURNAL"
LANGUAGE = "ja"
NEWS_WINDOW_HOURS = 48  # Googleニュース: 48時間以内の記事
MAX_URLS = 1000
OUTPUT_DIR = BASE_DIR / "static"
OUTPUT_FILE = OUTPUT_DIR / "news-sitemap.xml"
JST = timezone(timedelta(hours=9))

# ── カテゴリマッピング（キーワードベース） ──

KEYWORD_SECTIONS = {
    "bts": "BTS", "blackpink": "BLACKPINK", "twice": "TWICE",
    "aespa": "aespa", "newjeans": "NewJeans", "seventeen": "SEVENTEEN",
    "ive": "IVE", "le-sserafim": "LE SSERAFIM", "stray-kids": "Stray Kids",
    "enhypen": "ENHYPEN", "nct": "NCT", "txt": "TXT",
    "illit": "ILLIT", "treasure": "TREASURE", "ateez": "ATEEZ",
    "exo": "EXO", "bigbang": "BIGBANG",
}


def _wp_auth_header() -> dict:
    """~/.wp_auth から Authorization ヘッダを読み取る。"""
    wp_auth_path = os.path.expanduser("~/.wp_auth")
    if os.path.exists(wp_auth_path):
        with open(wp_auth_path) as f:
            for line in f:
                m = re.match(
                    r'header\s*=\s*"(Authorization:\s*Basic\s+[^\s"]+)"?',
                    line.strip(),
                )
                if m:
                    auth_val = m.group(1)
                    parts = auth_val.split(": ", 1)
                    return {"Authorization": parts[1] if len(parts) == 2 else auth_val}

    # フォールバック: 環境変数
    import base64
    user = os.environ.get("WP_USER", "")
    passwd = os.environ.get("WP_PASS", "")
    if user and passwd:
        token = base64.b64encode(f"{user}:{passwd}".encode()).decode()
        return {"Authorization": f"Basic {token}"}

    return {}


def fetch_recent_posts(hours: int = NEWS_WINDOW_HOURS) -> list[dict]:
    """WordPress REST API から直近 N 時間以内の公開記事を取得する。"""
    after = datetime.now(timezone.utc) - timedelta(hours=hours)
    after_iso = after.strftime("%Y-%m-%dT%H:%M:%S")

    posts = []
    page = 1
    per_page = 100

    while len(posts) < MAX_URLS:
        params = urllib.parse.urlencode({
            "after": after_iso,
            "per_page": per_page,
            "page": page,
            "status": "publish",
            "orderby": "date",
            "order": "desc",
            "_fields": "id,title,link,date_gmt,modified_gmt,slug,categories",
        })
        url = f"{WP_API}/posts?{params}"

        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "news-sitemap-gen/1.0",
                **_wp_auth_header(),
            })
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if not data:
                    break
                posts.extend(data)
                # X-WP-TotalPages ヘッダで最終ページ判定
                total_pages = int(resp.headers.get("X-WP-TotalPages", 1))
                if page >= total_pages:
                    break
                page += 1
        except urllib.error.HTTPError as e:
            if e.code == 400:
                # ページ範囲外
                break
            print(f"  [warn] WP API error: {e.code} {e.reason}", file=sys.stderr)
            break
        except Exception as e:
            print(f"  [warn] WP API fetch error: {e}", file=sys.stderr)
            break

    return posts[:MAX_URLS]


def extract_keywords_from_slug(slug: str) -> list[str]:
    """スラッグからキーワードを抽出す��。"""
    keywords = []
    slug_lower = slug.lower()
    for kw, label in KEYWORD_SECTIONS.items():
        if kw in slug_lower:
            keywords.append(label)
    # スラッグの単語をキーワードに
    parts = slug.split("-")
    for p in parts:
        if len(p) >= 3 and p not in keywords:
            keywords.append(p)
    return keywords[:5]


def render_title(title_obj) -> str:
    """WP REST API のタイトルオブジェクトからプレーンテキストを取得する。"""
    if isinstance(title_obj, dict):
        raw = title_obj.get("rendered", title_obj.get("raw", ""))
    else:
        raw = str(title_obj)
    # HTMLエンティティをデコード
    import html
    return html.unescape(re.sub(r'<[^>]+>', '', raw)).strip()


def generate_news_sitemap_xml(posts: list[dict]) -> str:
    """Google News Sitemap XML を生成する。"""
    entries = []

    for post in posts:
        link = post.get("link", "")
        if not link:
            continue

        title = render_title(post.get("title", ""))
        if not title:
            continue

        # 日付: W3C Datetime 形式 (UTC → JST変換不要、GMTのまま)
        date_gmt = post.get("date_gmt", "")
        if date_gmt:
            # WP API の日付は "2026-04-17T12:00:00" 形式 (UTC、Zなし)
            pub_date = date_gmt.replace(" ", "T")
            if not pub_date.endswith("Z") and "+" not in pub_date:
                pub_date += "+00:00"
        else:
            pub_date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")

        slug = post.get("slug", "")
        keywords = extract_keywords_from_slug(slug)
        kw_xml = ""
        if keywords:
            kw_xml = f"\n        <news:keywords>{xml_escape(', '.join(keywords))}</news:keywords>"

        entries.append(f"""  <url>
    <loc>{xml_escape(link)}</loc>
    <news:news>
      <news:publication>
        <news:name>{xml_escape(PUBLICATION_NAME)}</news:name>
        <news:language>{LANGUAGE}</news:language>
      </news:publication>
      <news:publication_date>{xml_escape(pub_date)}</news:publication_date>
      <news:title>{xml_escape(title)}</news:title>{kw_xml}
    </news:news>
  </url>""")

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">
{chr(10).join(entries)}
</urlset>"""

    return xml


def upload_to_wordpress(xml_content: str) -> bool:
    """生成したXMLをWordPressにアップロードする。

    2段構え:
      1. カスタムREST APIエンドポイント（mu-plugin設置後に利用可能）
      2. フォールバック: 固定ページ（ID: NEWS_SITEMAP_PAGE_ID）にXMLを保存
         <!-- wp:html --> ブロックでwpautopを回避
    """
    auth = _wp_auth_header()
    if not auth:
        print("  [error] WP認証情報が見つかりません", file=sys.stderr)
        return False

    # 方法1: カスタムREST APIエンドポイント（mu-plugin が設置済みの場合）
    payload = json.dumps({
        "news_sitemap_xml": xml_content,
        "news_sitemap_updated": datetime.now(JST).isoformat(),
    }).encode("utf-8")

    url = f"{SITE_URL}/wp-json/kpopjournal/v1/news-sitemap"
    try:
        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "news-sitemap-gen/1.0", **auth},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            if result.get("success"):
                print(f"  ✅ news-sitemap.xml mu-plugin経由アップロード成功 ({len(xml_content)} bytes)")
                return True
    except urllib.error.HTTPError as e:
        if e.code != 404:
            print(f"  [warn] mu-plugin endpoint error: {e.code}", file=sys.stderr)
    except Exception:
        pass

    # 方法2: 固定ページにXMLを保存（フォールバック）
    print("  → mu-pluginエンドポイント未検出。固定ページ更新にフォールバック...")
    return _update_sitemap_page(xml_content, auth)


# ニュースサイトマップ固定ページ ID（WP REST API で自動検出 → キャッシュ）
NEWS_SITEMAP_PAGE_SLUG = "kpj-news-sitemap-xml"
_page_id_cache = None


def _find_sitemap_page_id(auth: dict) -> int | None:
    """ニュースサイトマップ固定ページのIDを検出する。"""
    global _page_id_cache
    if _page_id_cache:
        return _page_id_cache

    url = f"{WP_API}/pages?slug={NEWS_SITEMAP_PAGE_SLUG}&_fields=id&per_page=1"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "news-sitemap-gen/1.0", **auth})
        with urllib.request.urlopen(req, timeout=15) as resp:
            pages = json.loads(resp.read().decode("utf-8"))
            if pages and isinstance(pages, list) and pages[0].get("id"):
                _page_id_cache = pages[0]["id"]
                return _page_id_cache
    except Exception as e:
        print(f"  [warn] Page lookup failed: {e}", file=sys.stderr)
    return None


def _update_sitemap_page(xml_content: str, auth: dict) -> bool:
    """固定ページにXMLを保存する（wp:htmlブロックでwpautop回避）。"""
    page_id = _find_sitemap_page_id(auth)
    if not page_id:
        print("  [error] 固定ページが見つかりません", file=sys.stderr)
        return False

    # <!-- wp:html --> ブロックで囲んでwpautopによる<br>挿入を防ぐ
    block_content = f"<!-- wp:html -->\n{xml_content}\n<!-- /wp:html -->"
    payload = json.dumps({"content": block_content}).encode("utf-8")

    url = f"{WP_API}/pages/{page_id}"
    try:
        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "news-sitemap-gen/1.0", **auth},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            if result.get("id") == page_id:
                print(f"  ✅ 固定ページ(ID:{page_id})にXML保存成功 ({len(xml_content)} bytes)")
                return True
    except Exception as e:
        print(f"  [error] Page update failed: {e}", file=sys.stderr)
    return False


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Google News Sitemap Generator")
    parser.add_argument("--upload", action="store_true", help="WordPressにアップロード")
    parser.add_argument("--local", action="store_true", help="ローカル保存のみ")
    parser.add_argument("--hours", type=int, default=NEWS_WINDOW_HOURS, help="対象期間（時間）")
    parser.add_argument("--dry-run", action="store_true", help="生成のみ・書き込みなし")
    args = parser.parse_args()

    print("=" * 50)
    print(" Google News Sitemap Generator")
    print(f" 対象: 直近 {args.hours} 時間の記事")
    print("=" * 50)

    # 1. WP REST API から記事取得
    print("\n[1] WordPress REST API から記事取得中...")
    posts = fetch_recent_posts(hours=args.hours)
    print(f"  → {len(posts)} 件取得")

    if not posts:
        print("  ⚠️ 対象記事なし → news-sitemap.xml 生成スキップ")
        # 空のサイトマップを生成（エラー防止）
        xml = generate_news_sitemap_xml([])
    else:
        xml = generate_news_sitemap_xml(posts)

    print(f"\n[2] XML生成完了 ({len(xml)} bytes, {len(posts)} URLs)")

    if args.dry_run:
        print("\n[dry-run] XML内容:")
        print(xml[:2000])
        return

    # 3. 保存
    OUTPUT_DIR.mkdir(exist_ok=True)
    OUTPUT_FILE.write_text(xml, encoding="utf-8")
    print(f"\n[3] ローカル保存: {OUTPUT_FILE}")

    # 3.5. nginx配信先に同期（/var/www/html/ が配信先の場合）
    import shutil
    NGINX_DEST = Path("/var/www/html/news-sitemap.xml")
    try:
        shutil.copy2(str(OUTPUT_FILE), str(NGINX_DEST))
        print(f"  → nginx配信先に同期完了: {NGINX_DEST}")
    except PermissionError:
        print(f"  ⚠️ {NGINX_DEST} への書き込み権限なし（sudo設定 or nginx alias変更が必要）")
    except Exception as e:
        print(f"  ⚠️ 同期失敗: {e}")

    # 4. アップロード（--upload指定時）
    if args.upload and not args.local:
        print("\n[4] WordPressにアップロード中...")
        success = upload_to_wordpress(xml)
        if not success:
            print("  → ローカルファイルのみ保存済み")
            print("  → functions.php でのリライト設定を確認してください")

    print("\n✅ 完了")


if __name__ == "__main__":
    main()
