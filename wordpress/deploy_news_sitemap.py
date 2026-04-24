#!/usr/bin/env python3
"""deploy_news_sitemap.py — REST API経由でニュースサイトマッププラグインをWPに設置

mu-pluginsにファイルを置けない環境（ConoHaファイルマネージャ制限等）向けに、
PHPコードをWP REST API経由で有効なプラグインとしてインストールする。

手法: wp_options テーブルにPHPコードを保存し、子テーマのfunctions.phpから
      動的にロードする仕組みを REST API 経由で構築する。

実際の手法:
  1. kpj-news-sitemap.php の全PHPコードを wp_options に保存
  2. そのコードを eval() で実行するミニローダーをさらに option に保存
  3. テーマカスタマイザー API (wp_css) や既存の仕組みを活用

最終的な実装: Code Snippets プラグインがないため、
  「自己完結型プラグイン」を ZIP にしてアップロードする。
  → WP 5.5+ の POST /wp-json/wp/v2/plugins で ZIP URL からインストール可能

Usage:
  python3 wordpress/deploy_news_sitemap.py
  python3 wordpress/deploy_news_sitemap.py --check   # 状態確認のみ
  python3 wordpress/deploy_news_sitemap.py --remove   # プラグイン無効化
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import sys
import zipfile
from pathlib import Path
from urllib.parse import quote

import requests

BASE = Path(__file__).resolve().parent.parent
WP_URL = "https://www.kpopjournal.tokyo"
PLUGIN_SLUG = "kpj-news-sitemap"
PLUGIN_FILE = f"{PLUGIN_SLUG}/{PLUGIN_SLUG}.php"

# .wp_auth から認証情報を取得
def get_wp_auth() -> tuple[str, str]:
    wp_auth_path = Path.home() / ".wp_auth"
    if wp_auth_path.exists():
        for line in wp_auth_path.read_text().splitlines():
            if "Basic" in line:
                b64 = line.split("Basic")[-1].strip().strip('"')
                decoded = base64.b64decode(b64).decode()
                user, pw = decoded.split(":", 1)
                return user, pw
    # フォールバック
    return os.getenv("WP_USER", ""), os.getenv("WP_PASS", "")


def api(method: str, path: str, **kwargs) -> requests.Response:
    auth = get_wp_auth()
    url = f"{WP_URL}/wp-json{path}"
    return requests.request(method, url, auth=auth, timeout=30, **kwargs)


def check_plugin_status():
    """プラグインの現在の状態を確認"""
    r = api("GET", "/wp/v2/plugins")
    if not r.ok:
        print(f"Plugins API error: {r.status_code} {r.text[:200]}")
        return None
    for p in r.json():
        if PLUGIN_SLUG in p.get("plugin", ""):
            return p
    return None


def check_news_sitemap_response():
    """/news-sitemap.xml の現在のレスポンスを確認"""
    try:
        r = requests.get(f"{WP_URL}/news-sitemap.xml", timeout=10)
        custom = r.headers.get("X-KPJ-News-Sitemap", "")
        url_count = r.text.count("<url>")
        is_empty_aioseo = "<urlset" in r.text and url_count == 0
        return {
            "status": r.status_code,
            "is_custom": bool(custom),
            "custom_version": custom,
            "url_count": url_count,
            "is_empty_aioseo": is_empty_aioseo,
            "size": len(r.text),
        }
    except Exception as e:
        return {"status": 0, "error": str(e)}


def build_plugin_zip() -> bytes:
    """kpj-news-sitemap.php をプラグインZIPとしてパッケージ"""
    php_path = BASE / "wordpress" / "kpj-news-sitemap.php"
    if not php_path.exists():
        print(f"ERROR: {php_path} が見つかりません")
        sys.exit(1)

    php_code = php_path.read_text("utf-8")

    # mu-plugins用のヘッダを通常プラグイン形式に修正
    php_code = php_code.replace(
        "設置場所: wp-content/mu-plugins/kpj-news-sitemap.php",
        "通常プラグインとしてインストール（mu-plugins不要版）"
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{PLUGIN_SLUG}/{PLUGIN_SLUG}.php", php_code)
    return buf.getvalue()


def upload_and_activate():
    """プラグインZIPをアップロードして有効化"""

    # 既存確認
    existing = check_plugin_status()
    if existing:
        status = existing.get("status", "")
        print(f"プラグイン既存: status={status}")
        if status == "active":
            print("既に有効化済み。再デプロイするには --remove 後に再実行してください。")
            return True

    # ZIPを一時的にWebアクセス可能な場所に置く必要がある
    # WP REST API の POST /wp/v2/plugins は "slug" でWordPress.orgからインストールか
    # "upload" パラメータは非対応
    # → 代替策: wp_options に PHP コードを保存し、テーマから動的ロード

    print("\n=== wp_options 経由でのデプロイ ===")
    php_path = BASE / "wordpress" / "kpj-news-sitemap.php"
    php_code = php_path.read_text("utf-8")

    # ABSPATHチェックとPlugin Nameヘッダを除去（option経由で読み込まれるため）
    # 関数定義・add_action/add_filter 部分のみ抽出
    # <?php と if (!defined('ABSPATH')) は不要
    code_body = php_code
    code_body = code_body.replace("<?php", "")
    code_body = code_body.replace("if (!defined('ABSPATH')) {\n    exit;\n}", "")
    # Plugin Name コメントブロックを除去
    import re
    code_body = re.sub(r'/\*\*\s*\n\s*\*\s*Plugin Name:.*?\*/', '', code_body, flags=re.DOTALL)
    code_body = code_body.strip()

    # wp_options に保存
    # option名: kpj_news_sitemap_code
    r = api("POST", "/wp/v2/settings", json={})  # settingsエンドポイント確認
    # settings APIではカスタムoptionは保存できないので、
    # 既存のページのカスタムフィールド経由で保存する

    # 最終手段: テーマの「追加CSS」欄 (wp_css) は PHP 不可
    # → ウィジェットエリアを使う（HTML ウィジェットにPHPを入れる→非対応）
    # → 最も確実: WP管理画面のテーマエディタからfunctions.phpに1行追加

    print("REST API経由での直接プラグインアップロードはWP標準APIでは非対応です。")
    print()
    print("以下の方法で設置してください:")
    print()
    generate_functions_php_snippet(code_body)
    return False


def generate_functions_php_snippet(code_body: str = ""):
    """functions.php に追記する1行スニペットを生成"""
    php_path = BASE / "wordpress" / "kpj-news-sitemap.php"
    php_code = php_path.read_text("utf-8")

    # option経由の動的ロード方式:
    # functions.phpに1行追加 → wp_optionからPHPコードを読んでeval
    # しかしeval()はセキュリティリスクが高い

    # 最もシンプルで安全な方法: functions.php に直接全コードを追記
    # Cocoon子テーマの functions.php は管理画面「テーマエディタ」から編集可能

    # 管理画面操作不要の方法: REST API で固定ページの content に
    # PHP shortcode を入れる → これも不可

    print("=" * 60)
    print("方法: WordPress管理画面 → 外観 → テーマファイルエディタ")
    print("      → cocoon-child-master の functions.php 末尾に以下を貼り付け")
    print("=" * 60)
    print()

    # functions.php用の安全なスニペットを生成
    # 全コードをfunctions.phpに直接書くと長すぎるので、
    # 必要最小限のコード（ニュースサイトマップのコア機能）を出力
    snippet = generate_minimal_snippet()
    print(snippet)
    print()
    print("=" * 60)

    # スニペットをファイルに保存
    out = BASE / "wordpress" / "functions_php_snippet.php"
    out.write_text(snippet, "utf-8")
    print(f"\nスニペットを保存: {out}")
    print("このファイルの内容をfunctions.phpの末尾に貼り付けてください。")


def generate_minimal_snippet() -> str:
    """functions.phpに追記する最小限のスニペット"""
    return '''
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// KPJ News Sitemap — functions.php 版 v1.0
// AIOSEO の空 news-sitemap.xml を上書きし、直近48時間の記事を配信
// 追加日: ''' + __import__('datetime').date.today().isoformat() + '''
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

// AIOSEO の news sitemap を無効化
add_filter('aioseo_sitemap_types', function ($types) {
    return is_array($types) ? array_filter($types, function ($t) { return $t !== 'news'; }) : $types;
}, 1);

// /news-sitemap.xml へのリクエストをインターセプト
add_action('parse_request', function () {
    $path = rtrim(parse_url($_SERVER['REQUEST_URI'] ?? '', PHP_URL_PATH), '/');
    if ($path !== '/news-sitemap.xml') return;
    kpj_ns_serve(); exit;
}, 1);

// send_headers でも補足（キャッシュバイパス対策）
add_action('send_headers', function () {
    $path = rtrim(parse_url($_SERVER['REQUEST_URI'] ?? '', PHP_URL_PATH), '/');
    if ($path !== '/news-sitemap.xml') return;
    kpj_ns_serve(); exit;
}, 1);

function kpj_ns_serve() {
    $xml = get_option('kpj_news_sitemap_xml', '');
    $ts  = get_option('kpj_news_sitemap_updated', '');
    if ($xml && $ts && (time() - strtotime($ts)) < 7200) {
        kpj_ns_out($xml); return;
    }
    $xml = kpj_ns_gen();
    update_option('kpj_news_sitemap_xml', $xml, false);
    update_option('kpj_news_sitemap_updated', current_time('c'), false);
    kpj_ns_out($xml);
}

function kpj_ns_out($xml) {
    status_header(200);
    header('Content-Type: application/xml; charset=UTF-8');
    header('X-Robots-Tag: noindex');
    header('Cache-Control: public, max-age=1800');
    header('X-KPJ-News-Sitemap: custom-v1.0');
    echo $xml;
}

function kpj_ns_gen() {
    $q = new WP_Query([
        'post_type' => 'post', 'post_status' => 'publish',
        'posts_per_page' => 1000, 'orderby' => 'date', 'order' => 'DESC',
        'date_query' => [['after' => '48 hours ago', 'inclusive' => true]],
        'no_found_rows' => true,
    ]);
    $entries = ''; $n = 0;
    while ($q->have_posts()) { $q->the_post();
        $t = htmlspecialchars(wp_strip_all_tags(html_entity_decode(get_the_title(), ENT_XML1, 'UTF-8')), ENT_XML1|ENT_QUOTES, 'UTF-8');
        $u = esc_url(get_permalink()); $d = get_the_date('c');
        $kw = []; foreach (get_the_category() as $c) $kw[] = $c->name;
        $tags = get_the_tags(); if ($tags) foreach ($tags as $tg) $kw[] = $tg->name;
        $kw = array_slice(array_unique($kw), 0, 10);
        $kwx = $kw ? "\\n        <news:keywords>".htmlspecialchars(implode(', ',$kw),ENT_XML1|ENT_QUOTES,'UTF-8')."</news:keywords>" : '';
        $img = ''; $tid = get_post_thumbnail_id();
        if ($tid && ($tu = wp_get_attachment_url($tid)))
            $img = "\\n    <image:image>\\n      <image:loc>".esc_url($tu)."</image:loc>\\n      <image:title>{$t}</image:title>\\n    </image:image>";
        $entries .= "  <url>\\n    <loc>{$u}</loc>\\n    <news:news>\\n      <news:publication>\\n        <news:name>KPOP JOURNAL</news:name>\\n        <news:language>ja</news:language>\\n      </news:publication>\\n      <news:publication_date>{$d}</news:publication_date>\\n      <news:title>{$t}</news:title>{$kwx}\\n    </news:news>{$img}\\n  </url>\\n";
        $n++;
    }
    wp_reset_postdata();
    $now = current_time('c');
    return '<?xml version="1.0" encoding="UTF-8"?>'.
        "\\n<!-- KPJ News Sitemap | {$n} articles | {$now} -->\\n".
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:news="http://www.google.com/schemas/sitemap-news/0.9" xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">'.
        "\\n{$entries}</urlset>";
}

// REST API（パイプラインからのXMLアップロード受付）
add_action('rest_api_init', function () {
    register_rest_route('kpopjournal/v1', '/news-sitemap', [
        ['methods' => 'POST', 'callback' => 'kpj_ns_rest_update',
         'permission_callback' => function () { return current_user_can('manage_options'); }],
        ['methods' => 'GET', 'callback' => 'kpj_ns_rest_status',
         'permission_callback' => function () { return current_user_can('manage_options'); }],
    ]);
});

function kpj_ns_rest_update($req) {
    $xml = $req->get_param('news_sitemap_xml');
    if (empty($xml)) return new WP_REST_Response(['success'=>false,'message'=>'xml required'], 400);
    update_option('kpj_news_sitemap_xml', $xml, false);
    update_option('kpj_news_sitemap_updated', $req->get_param('news_sitemap_updated') ?: current_time('c'), false);
    return new WP_REST_Response(['success'=>true,'size'=>strlen($xml)]);
}

function kpj_ns_rest_status($req) {
    $xml = get_option('kpj_news_sitemap_xml', '');
    return new WP_REST_Response(['has_cache'=>!empty($xml),'updated'=>get_option('kpj_news_sitemap_updated',''),'url_count'=>substr_count($xml,'<url>')]);
}

// robots.txt 修正
add_filter('robots_txt', function ($out, $pub) {
    if (!$pub) return $out;
    $out = preg_replace('/User-agent:\\s*Googlebot-News[^\\n]*\\n(?:[^\\n]*\\n)*?(?=\\s*$|\\s*User-agent:|\\s*Sitemap:)/i', '', $out);
    $out = preg_replace('/^Sitemap:\\s*[^\\n]*news-sitemap\\.xml[^\\n]*$/m', '', $out);
    $out = preg_replace('/\\n{3,}/', "\\n\\n", rtrim($out)) . "\\n";
    $out .= "\\nUser-agent: Googlebot-News\\nAllow: /\\n\\nSitemap: " . home_url('/news-sitemap.xml') . "\\n";
    return $out;
}, 9999, 2);

// AIOSEOサイトマップインデックスにnews-sitemapを追加
add_filter('aioseo_sitemap_indexes', function ($idx) {
    if (!is_array($idx)) return $idx;
    foreach ($idx as $i) if (isset($i['loc']) && strpos($i['loc'], 'news-sitemap') !== false) return $idx;
    $idx[] = ['loc' => home_url('/news-sitemap.xml'), 'lastmod' => current_time('c')];
    return $idx;
}, 10);
// ━━━ KPJ News Sitemap END ━━━
'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="状態確認のみ")
    ap.add_argument("--remove", action="store_true", help="プラグイン無効化")
    args = ap.parse_args()

    print("=== KPJ News Sitemap デプロイツール ===\n")

    # 現在の /news-sitemap.xml 確認
    print("--- /news-sitemap.xml 現在の状態 ---")
    ns = check_news_sitemap_response()
    print(f"  HTTP: {ns.get('status')}")
    print(f"  カスタム版: {ns.get('is_custom', False)}")
    if ns.get('is_custom'):
        print(f"  バージョン: {ns.get('custom_version')}")
    print(f"  記事数: {ns.get('url_count', 0)}")
    print(f"  AIOSEO空XML: {ns.get('is_empty_aioseo', False)}")
    print(f"  サイズ: {ns.get('size', 0)} bytes")

    # プラグイン確認
    print("\n--- プラグイン状態 ---")
    plugin = check_plugin_status()
    if plugin:
        print(f"  {PLUGIN_SLUG}: status={plugin.get('status')}")
    else:
        print(f"  {PLUGIN_SLUG}: 未インストール")

    if args.check:
        return

    if args.remove:
        if plugin and plugin.get("status") == "active":
            r = api("POST", f"/wp/v2/plugins/{quote(PLUGIN_FILE, safe='')}", json={"status": "inactive"})
            print(f"  無効化: {r.status_code}")
        return

    # デプロイ
    if ns.get("is_custom") and ns.get("url_count", 0) > 0:
        print(f"\n既にカスタム版が稼働中（{ns['url_count']}記事）。変更不要です。")
        return

    print("\n--- デプロイ ---")
    upload_and_activate()


if __name__ == "__main__":
    main()
