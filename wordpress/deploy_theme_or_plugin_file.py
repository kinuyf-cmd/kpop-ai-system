#!/usr/bin/env python3
"""WP theme/plugin ファイルを admin Cookie 認証 + theme-editor / plugin-editor 経由で
全置換 deploy する汎用スクリプト。

deploy_pwa_via_functionsphp.py の追記専用ロジックを「全置換 + 任意ファイル + theme/plugin
両対応」に汎用化したもの。

Usage:
  python3 wordpress/deploy_theme_or_plugin_file.py \\
    --target-type theme \\
    --target-file functions.php \\
    --local-file wordpress/kpopjournal-theme/functions.php \\
    [--dry-run]

  python3 wordpress/deploy_theme_or_plugin_file.py \\
    --target-type plugin \\
    --target-plugin-slug kpj-headless-api \\
    --target-file kpj-headless-api.php \\
    --local-file wordpress/kpj-headless-api/kpj-headless-api.php
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
env_file = BASE / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

SITE_URL = os.environ.get("SITE_URL", "https://www.kpopjournal.tokyo")
WP_USER = os.environ.get("WP_USER", "")
WP_PASS = os.environ.get("WP_PASS", "")


def _build_opener() -> urllib.request.OpenerDirector:
    cj = CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cj),
        urllib.request.HTTPRedirectHandler(),
    )
    opener.addheaders = [("User-Agent", "Mozilla/5.0 (kpj-deploy)")]
    return opener


def wp_cookie_login(opener) -> bool:
    login_url = f"{SITE_URL}/wp-login.php"
    data = urllib.parse.urlencode({
        "log": WP_USER, "pwd": WP_PASS, "wp-submit": "Log In",
        "redirect_to": f"{SITE_URL}/wp-admin/", "testcookie": "1",
    }).encode()
    req = urllib.request.Request(login_url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("Cookie", "wordpress_test_cookie=WP+Cookie+check")
    try:
        resp = opener.open(req, timeout=30)
        body = resp.read().decode("utf-8", errors="replace")
        if "login_error" in body or "wp-login.php" in resp.url:
            m = re.search(r'<div id="login_error"[^>]*>(.*?)</div>', body, re.DOTALL)
            if m: print(f"  login error: {re.sub(r'<[^>]+>', '', m.group(1)).strip()}")
            return False
        return True
    except Exception as e:
        print(f"  login err: {e}")
        return False


def _get_editor_page(opener, editor_url: str) -> tuple[str, str, str, str]:
    """editor 画面取得し (content, nonce, theme/plugin id, scrape_key) を返す"""
    req = urllib.request.Request(editor_url)
    try:
        resp = opener.open(req, timeout=30)
        html = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  editor access err: {e}")
        return "", "", "", ""

    nonce = ""
    for pat in [r'name="_wpnonce"\s+value="([^"]+)"', r"_wpnonce['\"]?\s*[:=]\s*['\"]([a-f0-9]+)['\"]"]:
        m = re.search(pat, html)
        if m:
            nonce = m.group(1); break

    # theme name or plugin file
    target_id = ""
    for pat in [r'name="theme"\s+value="([^"]+)"', r'name="plugin"\s+value="([^"]+)"']:
        m = re.search(pat, html)
        if m:
            target_id = m.group(1); break

    content = ""
    m = re.search(r'<textarea[^>]*id="newcontent"[^>]*>(.*?)</textarea>', html, re.DOTALL)
    if m:
        content = m.group(1)
        content = (content.replace("&lt;", "<").replace("&gt;", ">")
                          .replace("&amp;", "&").replace("&quot;", '"').replace("&#039;", "'"))

    return content, nonce, target_id, html


def _post_save(opener, editor_url: str, fields: dict) -> tuple[bool, str]:
    data = urllib.parse.urlencode(fields).encode("utf-8")
    req = urllib.request.Request(editor_url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        resp = opener.open(req, timeout=60)
        body = resp.read().decode("utf-8", errors="replace")
        url_final = resp.url
    except Exception as e:
        return False, f"req err: {e}"
    if "updated" in url_final or "liveupdate=1" in body or "ファイルを更新" in body or "File edited successfully" in body:
        return True, "OK"
    if "wp_scrape_nonce" in body:
        return False, "syntax_check_required"
    em = re.search(r'class="error"[^>]*>(.*?)</div>', body, re.DOTALL)
    if em:
        return False, f"error: {re.sub(r'<[^>]+>', '', em.group(1)).strip()[:200]}"
    return False, f"unknown (url={url_final})"


def deploy_theme_file(opener, theme_file: str, new_content: str, dry_run: bool):
    editor_url = f"{SITE_URL}/wp-admin/theme-editor.php?file={urllib.parse.quote(theme_file)}"
    cur, nonce, theme, _ = _get_editor_page(opener, editor_url)
    if not nonce or not theme:
        print(f"  ERROR: nonce/theme 取得失敗 (nonce={bool(nonce)} theme={theme!r})")
        return False
    print(f"  theme={theme} file={theme_file} cur_size={len(cur)} new_size={len(new_content)}")
    if cur.strip() == new_content.strip():
        print(f"  SKIP: 内容差分なし")
        return True
    if dry_run:
        print(f"  DRY-RUN: would update theme file {theme_file}")
        return True
    fields = {
        "_wpnonce": nonce,
        "_wp_http_referer": f"/wp-admin/theme-editor.php?file={theme_file}&theme={theme}",
        "newcontent": new_content,
        "action": "update",
        "file": theme_file,
        "theme": theme,
        "scrollto": "0",
        "docs-list": "",
        "submit": "Update File",
    }
    ok, msg = _post_save(opener, f"{SITE_URL}/wp-admin/theme-editor.php", fields)
    print(f"  → {'OK' if ok else 'FAIL'}: {msg}")
    return ok


def deploy_plugin_file(opener, plugin_slug: str, plugin_file: str, new_content: str, dry_run: bool):
    # plugin-editor.php?file=<slug>/<file>
    plugin_path = f"{plugin_slug}/{plugin_file}"
    editor_url = f"{SITE_URL}/wp-admin/plugin-editor.php?file={urllib.parse.quote(plugin_path)}"
    cur, nonce, target_id, _ = _get_editor_page(opener, editor_url)
    if not nonce:
        print(f"  ERROR: nonce 取得失敗")
        return False
    print(f"  plugin_path={plugin_path} cur_size={len(cur)} new_size={len(new_content)}")
    if cur.strip() == new_content.strip():
        print(f"  SKIP: 内容差分なし")
        return True
    if dry_run:
        print(f"  DRY-RUN: would update plugin file {plugin_path}")
        return True
    fields = {
        "_wpnonce": nonce,
        "_wp_http_referer": f"/wp-admin/plugin-editor.php?file={plugin_path}",
        "newcontent": new_content,
        "action": "update",
        "file": plugin_path,
        "plugin": target_id or plugin_path,
        "scrollto": "0",
        "docs-list": "",
        "submit": "Update File",
    }
    ok, msg = _post_save(opener, f"{SITE_URL}/wp-admin/plugin-editor.php", fields)
    print(f"  → {'OK' if ok else 'FAIL'}: {msg}")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target-type", choices=["theme", "plugin"], required=True)
    ap.add_argument("--target-file", required=True,
                    help="theme: WP上のテーマファイル名 (functions.php / sidebar.php 等)。"
                         " plugin: プラグイン内のファイル名 (kpj-headless-api.php 等)")
    ap.add_argument("--target-plugin-slug", default="",
                    help="plugin の場合のプラグインスラッグ (kpj-headless-api 等)")
    ap.add_argument("--local-file", required=True, help="ローカルの該当ファイル絶対 path")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not (WP_USER and WP_PASS):
        print("ERROR: WP_USER / WP_PASS が .env に未設定")
        sys.exit(2)

    local = Path(args.local_file)
    if not local.exists():
        print(f"ERROR: local file 不在: {local}")
        sys.exit(2)
    new_content = local.read_text(encoding="utf-8")

    opener = _build_opener()
    print(f"=== login {WP_USER}@{SITE_URL} ===")
    if not wp_cookie_login(opener):
        print("login 失敗")
        sys.exit(3)
    print(f"=== deploy {args.target_type}: {args.target_file} ===")
    if args.target_type == "theme":
        ok = deploy_theme_file(opener, args.target_file, new_content, args.dry_run)
    else:
        if not args.target_plugin_slug:
            print("ERROR: --target-plugin-slug 必須 (plugin の場合)")
            sys.exit(2)
        ok = deploy_plugin_file(opener, args.target_plugin_slug, args.target_file,
                                new_content, args.dry_run)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
