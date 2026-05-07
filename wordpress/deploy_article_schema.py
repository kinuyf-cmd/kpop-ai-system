#!/usr/bin/env python3
"""
deploy_article_schema.py — Article (NewsArticle) JSON-LD を functions.php に追記

WordPress テーマエディタ経由で Cocoon子テーマの functions.php に
NewsArticle 構造化データの自動出力コードを追加する。

FAQ schema (cocoon-child-faq-schema.php) と同じ wp_footer フックパターン。

Usage:
  python3 wordpress/deploy_article_schema.py             # デプロイ
  python3 wordpress/deploy_article_schema.py --dry-run    # 確認のみ
  python3 wordpress/deploy_article_schema.py --check      # 状態確認のみ
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
SCRIPT_DIR = Path(__file__).resolve().parent

# .env 読み込み
env_file = BASE / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

SITE_URL = os.environ.get("SITE_URL", "https://www.kpopjournal.tokyo")
WP_USER = os.environ.get("WP_USER", "")
WP_PASS = os.environ.get("WP_PASS", "")

MARKER_START = "// ━━━ KPJ Article Schema START ━━━"
MARKER_END = "// ━━━ KPJ Article Schema END ━━━"


def build_php_snippet() -> str:
    """functions.php に追記する Article schema PHP コードを生成"""
    php_path = SCRIPT_DIR / "cocoon-child-article-schema.php"
    if not php_path.exists():
        print(f"  ERROR: {php_path} が見つかりません")
        sys.exit(1)

    code = php_path.read_text("utf-8").strip()
    # <?php タグがあれば除去
    code = code.replace("<?php", "").strip()

    return f"""{MARKER_START}
{code}
{MARKER_END}"""


def detect_login_url(opener: urllib.request.OpenerDirector) -> str:
    """カスタムログインURL（SiteGuard等）を自動検出"""
    req = urllib.request.Request(f"{SITE_URL}/wp-admin/")
    try:
        resp = opener.open(req, timeout=15)
        if "login" in resp.url or "wp-login" in resp.url:
            parsed = urllib.parse.urlparse(resp.url)
            return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    except urllib.error.HTTPError as e:
        location = e.headers.get("Location", "")
        if location:
            parsed = urllib.parse.urlparse(location)
            return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    except Exception:
        pass
    return f"{SITE_URL}/wp-login.php"


def wp_cookie_login(opener: urllib.request.OpenerDirector) -> bool:
    """WordPress Cookie認証でログイン"""
    login_url = detect_login_url(opener)
    print(f"  Login URL: {login_url}")
    data = urllib.parse.urlencode({
        "log": WP_USER,
        "pwd": WP_PASS,
        "wp-submit": "Log In",
        "redirect_to": f"{SITE_URL}/wp-admin/",
        "testcookie": "1",
    }).encode("utf-8")

    req = urllib.request.Request(login_url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("Cookie", "wordpress_test_cookie=WP+Cookie+check")

    try:
        resp = opener.open(req, timeout=30)
        body = resp.read().decode("utf-8", errors="replace")
        if "login_error" in body or "wp-login.php" in resp.url:
            return False
        return True
    except Exception as e:
        print(f"  Login error: {e}")
        return False


def get_theme_editor_page(opener: urllib.request.OpenerDirector) -> tuple[str, str, str]:
    """テーマエディタから functions.php の内容と nonce, theme を取得"""
    url = f"{SITE_URL}/wp-admin/theme-editor.php?file=functions.php"
    req = urllib.request.Request(url)
    try:
        resp = opener.open(req, timeout=30)
        html = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  Theme editor access error: {e}")
        return "", "", ""

    nonce_match = re.search(r'name="_wpnonce"\s+value="([^"]+)"', html)
    if not nonce_match:
        nonce_match = re.search(r"_wpnonce['\"]?\s*[:=]\s*['\"]([a-f0-9]+)['\"]", html)
    nonce = nonce_match.group(1) if nonce_match else ""

    theme_match = re.search(r'name="theme"\s+value="([^"]+)"', html)
    theme = theme_match.group(1) if theme_match else ""

    textarea_match = re.search(
        r'<textarea[^>]*id="newcontent"[^>]*>(.*?)</textarea>',
        html, re.DOTALL
    )
    content = ""
    if textarea_match:
        content = textarea_match.group(1)
        content = content.replace("&lt;", "<").replace("&gt;", ">")
        content = content.replace("&amp;", "&").replace("&quot;", '"')
        content = content.replace("&#039;", "'")

    return content, nonce, theme


def save_functions_php(
    opener: urllib.request.OpenerDirector,
    new_content: str,
    nonce: str,
    theme: str,
) -> bool:
    """テーマエディタ経由で functions.php を保存"""
    url = f"{SITE_URL}/wp-admin/theme-editor.php"
    data = urllib.parse.urlencode({
        "_wpnonce": nonce,
        "_wp_http_referer": f"/wp-admin/theme-editor.php?file=functions.php&theme={theme}",
        "newcontent": new_content,
        "action": "update",
        "file": "functions.php",
        "theme": theme,
        "scrollto": "0",
        "docs-list": "",
        "submit": "Update File",
    }).encode("utf-8")

    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        resp = opener.open(req, timeout=60)
        body = resp.read().decode("utf-8", errors="replace")
        if any(s in body for s in [
            "updated", "File edited successfully",
            "ファイルの編集に成功しました", "ファイルを更新しました"
        ]):
            return True

        if "wp_scrape_nonce" in body:
            print("  WP構文チェッカーが発動しました。")
            scrape_key_match = re.search(r'name="wp_scrape_key"\s+value="([^"]+)"', body)
            scrape_nonce_match = re.search(r'name="wp_scrape_nonce"\s+value="([^"]+)"', body)
            if scrape_key_match and scrape_nonce_match:
                print("  構文チェック承認中...")
                data2 = urllib.parse.urlencode({
                    "_wpnonce": nonce,
                    "_wp_http_referer": f"/wp-admin/theme-editor.php?file=functions.php&theme={theme}",
                    "newcontent": new_content,
                    "action": "update",
                    "file": "functions.php",
                    "theme": theme,
                    "scrollto": "0",
                    "wp_scrape_key": scrape_key_match.group(1),
                    "wp_scrape_nonce": scrape_nonce_match.group(1),
                    "submit": "Update File",
                }).encode("utf-8")
                req2 = urllib.request.Request(url, data=data2, method="POST")
                req2.add_header("Content-Type", "application/x-www-form-urlencoded")
                resp2 = opener.open(req2, timeout=60)
                body2 = resp2.read().decode("utf-8", errors="replace")
                if "fatal" in body2.lower() or "Parse error" in body2:
                    print("  PHP構文エラーが検出されました")
                    return False
                return True
            return False

        error_match = re.search(r'class="error"[^>]*>(.*?)</div>', body, re.DOTALL)
        if error_match:
            print(f"  Error: {re.sub(r'<[^>]+>', '', error_match.group(1)).strip()}")
            return False
        return True
    except Exception as e:
        print(f"  Save error: {e}")
        return False


def check_article_schema():
    """任意の記事ページで Article schema が出力されているか確認"""
    try:
        # 最近の記事を1件取得
        import json
        api_url = f"{SITE_URL}/wp-json/wp/v2/posts?per_page=1&_fields=link"
        req = urllib.request.Request(api_url, headers={"User-Agent": "KPJ-Deploy/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            posts = json.loads(resp.read().decode("utf-8"))
        if not posts:
            print("  記事が見つかりません")
            return

        post_url = posts[0]["link"]
        print(f"  確認対象: {post_url}")

        req = urllib.request.Request(post_url, headers={"User-Agent": "KPJ-Deploy/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")

        if "KPJ Article Schema" in html:
            print("  Article schema 出力確認済み")
            # JSON-LD 内容を抽出して表示
            ld_match = re.search(
                r'<!-- KPJ Article Schema -->\s*<script type="application/ld\+json">\s*(.*?)\s*</script>',
                html, re.DOTALL
            )
            if ld_match:
                try:
                    schema = json.loads(ld_match.group(1))
                    print(f"    @type: {schema.get('@type')}")
                    print(f"    headline: {schema.get('headline', '')[:50]}...")
                    print(f"    datePublished: {schema.get('datePublished', '')}")
                    print(f"    image: {'あり' if schema.get('image') else 'なし'}")
                except Exception:
                    pass
        else:
            print("  Article schema 未出力")
            if "application/ld+json" in html:
                ld_count = html.count("application/ld+json")
                print(f"  (他の JSON-LD が {ld_count} 個あり)")
    except Exception as e:
        print(f"  Check error: {e}")


def main():
    parser = argparse.ArgumentParser(description="Article schema → functions.php デプロイ")
    parser.add_argument("--dry-run", action="store_true", help="変更せずに確認のみ")
    parser.add_argument("--check", action="store_true", help="現在の状態確認のみ")
    args = parser.parse_args()

    print("=" * 56)
    print(" Article (NewsArticle) JSON-LD → functions.php デプロイ")
    print("=" * 56)

    if args.check:
        print("\n--- 現在の状態 ---")
        check_article_schema()
        return

    if not WP_USER or not WP_PASS:
        print("  .env に WP_USER / WP_PASS が未設定です")
        sys.exit(1)

    print(f"  Site: {SITE_URL}")
    print(f"  User: {WP_USER}")
    print()

    # PHP スニペット生成
    print("[1/4] PHPスニペット生成...")
    snippet = build_php_snippet()
    snippet_lines = snippet.count("\n") + 1
    print(f"  生成完了: {snippet_lines}行")
    print()

    # Cookie認証でログイン
    print("[2/4] WordPress Cookie認証ログイン...")
    cj = CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cj),
        urllib.request.HTTPRedirectHandler(),
    )
    opener.addheaders = [
        ("User-Agent", "Mozilla/5.0 (KPJ-Deploy/1.0)"),
    ]

    if not wp_cookie_login(opener):
        print("  WordPress ログイン失敗")
        sys.exit(1)
    print(f"  ログイン成功（Cookie: {len(cj)}個）")
    print()

    # テーマエディタから functions.php 取得
    print("[3/4] functions.php 取得...")
    current_content, nonce, theme = get_theme_editor_page(opener)
    if not current_content:
        print("  functions.php の取得に失敗しました")
        print("  テーマエディタが無効化されている可能性があります")
        sys.exit(1)
    if not nonce:
        print("  nonceの取得に失敗しました")
        sys.exit(1)

    print(f"  テーマ: {theme}")
    print(f"  nonce: {nonce[:8]}...")
    print(f"  現在の行数: {current_content.count(chr(10)) + 1}")

    # 既存マーカー確認
    if MARKER_START in current_content:
        print(f"  既存の Article schema コードを検出 → 置換します")
        pattern = re.escape(MARKER_START) + r".*?" + re.escape(MARKER_END)
        current_content = re.sub(pattern, "", current_content, flags=re.DOTALL).rstrip()

    # スニペット追記
    new_content = current_content.rstrip() + "\n\n" + snippet + "\n"
    new_lines = new_content.count("\n") + 1
    print(f"  更新後の行数: {new_lines}")
    print()

    if args.dry_run:
        print("[DRY-RUN] 変更は行いません")
        out_path = SCRIPT_DIR / "_functions_php_article_schema_preview.php"
        out_path.write_text("<?php\n" + snippet + "\n", encoding="utf-8")
        print(f"  プレビュー保存: {out_path}")
        return

    # 保存
    print("[4/4] functions.php 保存...")
    if save_functions_php(opener, new_content, nonce, theme):
        print("  functions.php 更新成功")
    else:
        print("  functions.php 更新に問題が発生した可能性があります")
        print("  サイトの動作を確認してください")
    print()

    # 動作確認
    print("=" * 56)
    print(" 動作確認")
    print("=" * 56)
    check_article_schema()
    print()
    print("=" * 56)


if __name__ == "__main__":
    main()
