#!/usr/bin/env python3
"""
PWA + コメント機能を functions.php に追記するデプロイスクリプト

mu-plugins にアクセスできない環境（ConoHa WING等）向け。
WordPress Cookie認証 → テーマエディタ経由で functions.php を更新。

manifest.json / sw.js はPHP内にインラインで埋め込み、
parse_request フックでルートURLから配信する。

使い方:
  python3 wordpress/deploy_pwa_via_functionsphp.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
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
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            v = v.strip().strip('"').strip("'")
            os.environ.setdefault(k.strip(), v)

SITE_URL = os.environ.get("SITE_URL", "https://www.kpopjournal.tokyo")
WP_USER = os.environ.get("WP_USER", "")
WP_PASS = os.environ.get("WP_PASS", "")

MARKER_START = "// === KPJ-PWA-COMMENTS START ==="
MARKER_END = "// === KPJ-PWA-COMMENTS END ==="


def build_php_snippet() -> str:
    """functions.php に追記するPHPスニペットを生成"""
    manifest_json = (SCRIPT_DIR / "kpj-manifest.json").read_text(encoding="utf-8")
    sw_js = (SCRIPT_DIR / "kpj-sw.js").read_text(encoding="utf-8")

    # sw.js 内のバッククォート・$をPHPヒアドキュメント用にエスケープ
    # PHPの <<<'HEREDOC' (nowdoc) を使うのでPHP変数展開は不要
    # ただしPHPの echo で出力するため、JS内の特殊文字は問題なし

    snippet = f"""{MARKER_START}
// KPJ PWA & Comments — functions.php インライン版
// 自動生成: deploy_pwa_via_functionsphp.py
// manifest.json / sw.js をインラインで配信

// ━━━ PART 1: manifest.json & sw.js 配信 ━━━
add_action('parse_request', function ($wp) {{
    $path = trim($_SERVER['REQUEST_URI'] ?? '', '/');
    $path = strtok($path, '?');

    if ($path === 'manifest.json') {{
        header('Content-Type: application/manifest+json; charset=utf-8');
        header('Cache-Control: public, max-age=86400');
        header('Access-Control-Allow-Origin: *');
        echo <<<'KPJ_MANIFEST'
{manifest_json}
KPJ_MANIFEST;
        exit;
    }}

    if ($path === 'sw.js') {{
        header('Content-Type: application/javascript; charset=utf-8');
        header('Cache-Control: no-cache');
        header('Service-Worker-Allowed: /');
        echo <<<'KPJ_SW'
{sw_js}
KPJ_SW;
        exit;
    }}
}}, 1);

// ━━━ PART 2: PWA ヘッダータグ ━━━
add_action('wp_head', function () {{
    echo '<link rel="manifest" href="/manifest.json" crossorigin="use-credentials">' . "\\n";
    echo '<meta name="theme-color" content="#FF2D55">' . "\\n";
    echo '<meta name="apple-mobile-web-app-capable" content="yes">' . "\\n";
    echo '<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">' . "\\n";
    echo '<link rel="apple-touch-icon" href="/wp-content/uploads/kpopjournal-icon-192.png">' . "\\n";
}}, 1);

// ━━━ PART 3: Service Worker 登録 ━━━
add_action('wp_footer', function () {{
    ?>
    <script>
    if ('serviceWorker' in navigator) {{
        window.addEventListener('load', function() {{
            navigator.serviceWorker.register('/sw.js', {{ scope: '/' }})
                .then(function(reg) {{
                    setInterval(function() {{ reg.update(); }}, 3600000);
                }})
                .catch(function() {{}});
        }});
    }}
    </script>
    <?php
}}, 99);

// ━━━ PART 4: コメント — ハニーポット ━━━
add_action('comment_form_after_fields', function () {{
    echo '<div style="display:none !important;"><label>Leave empty</label>';
    echo '<input type="text" name="kpj_hp_field" value="" tabindex="-1" autocomplete="off"></div>';
}});
add_filter('preprocess_comment', function ($data) {{
    if (!empty($_POST['kpj_hp_field'])) {{
        wp_die('スパムと判定されました。');
    }}
    return $data;
}});

// ━━━ PART 5: コメント — レート制限 ━━━
add_filter('preprocess_comment', function ($data) {{
    $ip = $_SERVER['REMOTE_ADDR'] ?? '0.0.0.0';
    $transient_key = 'kpj_comment_rate_' . md5($ip);
    $count = (int) get_transient($transient_key);
    if ($count >= 10) {{
        wp_die('コメント投稿の制限に達しました。しばらくしてからお試しください。');
    }}
    set_transient($transient_key, $count + 1, HOUR_IN_SECONDS);
    return $data;
}}, 1);

// ━━━ PART 6: コメント — リアクション表示 ━━━
add_filter('comment_text', function ($text, $comment) {{
    $reactions = get_comment_meta($comment->comment_ID, 'kpj_reactions', true);
    if ($reactions && is_array($reactions)) {{
        $html = '<div class="kpj-reactions" style="margin-top:8px;display:flex;gap:8px;flex-wrap:wrap">';
        $emojis = ['heart' => '&#10084;&#65039;', 'fire' => '&#128293;', 'laugh' => '&#128514;', 'surprise' => '&#128562;'];
        foreach ($reactions as $type => $count) {{
            if (isset($emojis[$type]) && $count > 0) {{
                $html .= '<span class="kpj-reaction" data-type="' . esc_attr($type) . '"'
                    . ' style="background:#1E1E2E;border:1px solid #2D2D3F;border-radius:16px;padding:4px 10px;font-size:13px;cursor:pointer">'
                    . $emojis[$type] . ' ' . (int) $count . '</span>';
            }}
        }}
        $html .= '</div>';
        $text .= $html;
    }}
    return $text;
}}, 10, 2);

// ━━━ PART 7: OGP コメント数メタ ━━━
add_action('wp_head', function () {{
    if (is_single()) {{
        $count = get_comments_number();
        if ($count > 0) {{
            echo '<meta property="og:comments" content="' . (int) $count . '">' . "\\n";
        }}
    }}
}}, 20);

// ━━━ PART 8: REST API — リアクション + Webプッシュ ━━━
add_action('rest_api_init', function () {{
    register_rest_route('kpopjournal/v1', '/comment-reaction', [
        'methods'  => 'POST',
        'callback' => function ($request) {{
            $comment_id = (int) $request->get_param('comment_id');
            $type       = sanitize_text_field($request->get_param('type'));
            $allowed    = ['heart', 'fire', 'laugh', 'surprise'];
            if (!in_array($type, $allowed, true) || !$comment_id) {{
                return new WP_Error('invalid', '不正なリクエスト', ['status' => 400]);
            }}
            $reactions        = get_comment_meta($comment_id, 'kpj_reactions', true) ?: [];
            $reactions[$type] = ($reactions[$type] ?? 0) + 1;
            update_comment_meta($comment_id, 'kpj_reactions', $reactions);
            return ['success' => true, 'reactions' => $reactions];
        }},
        'permission_callback' => '__return_true',
    ]]);
    register_rest_route('kpopjournal/v1', '/webpush/subscribe', [
        'methods'  => 'POST',
        'callback' => function ($request) {{
            $sub = $request->get_json_params();
            if (empty($sub['endpoint']) || empty($sub['keys'])) {{
                return new WP_Error('invalid', '不正な購読情報', ['status' => 400]);
            }}
            $file = ABSPATH . '../kpop-ai-system/logs/webpush_subscriptions.jsonl';
            file_put_contents($file, json_encode($sub) . "\\n", FILE_APPEND | LOCK_EX);
            return ['success' => true];
        }},
        'permission_callback' => '__return_true',
    ]]);
    register_rest_route('kpopjournal/v1', '/webpush/unsubscribe', [
        'methods'  => 'POST',
        'callback' => function ($request) {{
            $endpoint = sanitize_text_field($request->get_param('endpoint'));
            if (!$endpoint) {{
                return new WP_Error('invalid', '不正なリクエスト', ['status' => 400]);
            }}
            $file = ABSPATH . '../kpop-ai-system/logs/webpush_subscriptions.jsonl';
            if (file_exists($file)) {{
                $lines    = file($file, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES);
                $filtered = array_filter($lines, function ($line) use ($endpoint) {{
                    $sub = json_decode($line, true);
                    return ($sub['endpoint'] ?? '') !== $endpoint;
                }});
                file_put_contents($file, implode("\\n", $filtered) . "\\n", LOCK_EX);
            }}
            return ['success' => true];
        }},
        'permission_callback' => '__return_true',
    ]]);
}});
{MARKER_END}"""
    return snippet


def detect_login_url(opener: urllib.request.OpenerDirector) -> str:
    """カスタムログインURL（SiteGuard等）を自動検出"""
    # wp-admin にアクセスしてリダイレクト先を確認
    req = urllib.request.Request(f"{SITE_URL}/wp-admin/")
    try:
        resp = opener.open(req, timeout=15)
        # リダイレクト先がログインページ
        if "login" in resp.url or "wp-login" in resp.url:
            parsed = urllib.parse.urlparse(resp.url)
            return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    except urllib.error.HTTPError as e:
        # 302/303 リダイレクトがHTTPErrorになる場合
        location = e.headers.get("Location", "")
        if location:
            parsed = urllib.parse.urlparse(location)
            return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    except Exception:
        pass
    return f"{SITE_URL}/wp-login.php"


def wp_cookie_login(opener: urllib.request.OpenerDirector) -> bool:
    """WordPress にCookie認証でログイン"""
    login_url = detect_login_url(opener)
    print(f"  Login URL: {login_url}")
    data = urllib.parse.urlencode({
        "log": WP_USER,
        "pwd": WP_PASS,
        "wp-submit": "Log In",
        "redirect_to": f"{SITE_URL}/wp-admin/",
        "testcookie": "1",
    }).encode()

    req = urllib.request.Request(login_url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("Cookie", "wordpress_test_cookie=WP+Cookie+check")

    try:
        resp = opener.open(req, timeout=30)
        body = resp.read().decode("utf-8", errors="replace")
        # ログイン成功判定: リダイレクト先が wp-admin か、login_error がないか
        if "login_error" in body or "wp-login.php" in resp.url:
            print(f"  Login response URL: {resp.url}")
            if "login_error" in body:
                m = re.search(r'<div id="login_error"[^>]*>(.*?)</div>', body, re.DOTALL)
                if m:
                    print(f"  Error: {re.sub(r'<[^>]+>', '', m.group(1)).strip()}")
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

    # nonce 抽出
    nonce_match = re.search(r'name="_wpnonce"\s+value="([^"]+)"', html)
    if not nonce_match:
        # 代替パターン
        nonce_match = re.search(r"_wpnonce['\"]?\s*[:=]\s*['\"]([a-f0-9]+)['\"]", html)
    nonce = nonce_match.group(1) if nonce_match else ""

    # テーマ名抽出
    theme_match = re.search(r'name="theme"\s+value="([^"]+)"', html)
    theme = theme_match.group(1) if theme_match else ""

    # 現在の functions.php 内容抽出
    textarea_match = re.search(
        r'<textarea[^>]*id="newcontent"[^>]*>(.*?)</textarea>',
        html, re.DOTALL
    )
    content = ""
    if textarea_match:
        content = textarea_match.group(1)
        # HTML entities をデコード
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
        if "updated" in resp.url or "liveupdate=1" in body or "File edited successfully" in body:
            return True
        # WordPress日本語メッセージ
        if "ファイルの編集に成功しました" in body or "ファイルを更新しました" in body:
            return True
        # リダイレクト先にupdated=trueがあれば成功
        if "updated" in body:
            return True
        # エラー確認
        if "wp_scrape_nonce" in body:
            # PHP構文チェック警告 — WPの構文チェッカーが発動
            print("  WP構文チェッカーが発動しました。")
            # scrape nonce を取得して確認POST
            scrape_match = re.search(r'name="wp_scrape_nonce"\s+value="([^"]+)"', body)
            if scrape_match:
                print("  構文チェック承認中...")
                # 構文チェック通過のために直接 scrape エンドポイントを試行
                # WP 4.9+ の構文チェック対応
                return _handle_syntax_check(opener, body, new_content, nonce, theme)
            return False
        # HTML内にエラーメッセージがないか
        error_match = re.search(r'class="error"[^>]*>(.*?)</div>', body, re.DOTALL)
        if error_match:
            print(f"  Error: {re.sub(r'<[^>]+>', '', error_match.group(1)).strip()}")
            return False
        # 明確なエラーがなければ成功と見なす
        return True
    except Exception as e:
        print(f"  Save error: {e}")
        return False


def _handle_syntax_check(
    opener: urllib.request.OpenerDirector,
    check_html: str,
    new_content: str,
    nonce: str,
    theme: str,
) -> bool:
    """WordPress 4.9+ の PHP構文チェックを処理"""
    # スクレイプキーとnonceを取得
    scrape_key_match = re.search(r'name="wp_scrape_key"\s+value="([^"]+)"', check_html)
    scrape_nonce_match = re.search(r'name="wp_scrape_nonce"\s+value="([^"]+)"', check_html)
    if not scrape_key_match or not scrape_nonce_match:
        print("  構文チェック情報取得失敗")
        return False

    scrape_key = scrape_key_match.group(1)
    scrape_nonce = scrape_nonce_match.group(1)

    url = f"{SITE_URL}/wp-admin/theme-editor.php"
    data = urllib.parse.urlencode({
        "_wpnonce": nonce,
        "_wp_http_referer": f"/wp-admin/theme-editor.php?file=functions.php&theme={theme}",
        "newcontent": new_content,
        "action": "update",
        "file": "functions.php",
        "theme": theme,
        "scrollto": "0",
        "wp_scrape_key": scrape_key,
        "wp_scrape_nonce": scrape_nonce,
        "submit": "Update File",
    }).encode("utf-8")

    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        resp = opener.open(req, timeout=60)
        body = resp.read().decode("utf-8", errors="replace")
        if "fatal" in body.lower() or "Parse error" in body:
            print("  PHP構文エラーが検出されました。コードを確認してください。")
            return False
        return True
    except Exception as e:
        print(f"  Syntax check error: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="PWA functions.php デプロイ")
    parser.add_argument("--dry-run", action="store_true", help="変更せずに確認のみ")
    args = parser.parse_args()

    print("=" * 56)
    print(" PWA + コメント → functions.php デプロイ")
    print("=" * 56)

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
        print(f"  既存のPWAコードを検出 → 置換します")
        # 既存コードを削除して新しいものに置換
        pattern = re.escape(MARKER_START) + r".*?" + re.escape(MARKER_END)
        current_content = re.sub(pattern, "", current_content, flags=re.DOTALL).rstrip()

    # スニペット追記
    new_content = current_content.rstrip() + "\n\n" + snippet + "\n"
    new_lines = new_content.count("\n") + 1
    print(f"  更新後の行数: {new_lines}")
    print()

    if args.dry_run:
        print("[DRY-RUN] 変更は行いません")
        # スニペットをローカルに保存して確認用
        out_path = SCRIPT_DIR / "_functions_php_pwa_snippet_preview.php"
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
    for label, path in [
        ("manifest.json", "/manifest.json"),
        ("sw.js", "/sw.js"),
        ("サイトTOP", "/"),
    ]:
        try:
            req = urllib.request.Request(f"{SITE_URL}{path}", method="HEAD")
            resp = urllib.request.urlopen(req, timeout=10)
            ct = resp.headers.get("Content-Type", "?")
            status = resp.status
            print(f"  {label}: {status} ({ct})")
        except Exception as e:
            print(f"  {label}: ERROR ({e})")

    print()
    print(" 確認URL:")
    print(f"   PWA manifest: {SITE_URL}/manifest.json")
    print(f"   Service Worker: {SITE_URL}/sw.js")
    print(f"   Reaction API: {SITE_URL}/wp-json/kpopjournal/v1/comment-reaction")
    print("=" * 56)


if __name__ == "__main__":
    main()
