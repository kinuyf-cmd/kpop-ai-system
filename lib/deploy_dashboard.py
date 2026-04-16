"""
ダッシュボード公開デプロイスクリプト (deploy_dashboard.py)

dashboard.html を WordPress固定ページ (slug: kpop-admin-dashboard) に
パスワード保護付きで投稿/更新する。

URL: https://www.kpopjournal.tokyo/kpop-admin-dashboard/
認証: WPページパスワード保護

【パスワード管理】
  閲覧パスワードは ~/.dashboard_password ファイルに記載（パーミッション 600 推奨）。
  ファイルが存在しない場合は環境変数 DASHBOARD_PASSWORD を参照。
  どちらも未設定の場合は起動を中止し、設定案内を表示する。
  平文パスワードをコードや公開ログに残さない方針。

  設定方法:
    echo '任意の強固なパスワード' > ~/.dashboard_password
    chmod 600 ~/.dashboard_password

動作:
  - 初回: 固定ページを新規作成
  - 2回目以降: 既存ページをPUT更新 (slug維持)
"""
import json
import os
import re
import sys
import urllib.request
import urllib.error
from pathlib import Path

BASE_DIR       = Path(__file__).parent.parent
DASHBOARD_HTML = BASE_DIR / "dashboard.html"
WP_BASE        = "https://www.kpopjournal.tokyo/wp-json/wp/v2"
WP_AUTH_FILE   = Path.home() / ".wp_auth"
PAGE_SLUG      = "kpop-admin-dashboard"
DEPLOY_LOG     = BASE_DIR / "logs" / "dashboard_deploy.log"
_PASS_FILE     = Path.home() / ".dashboard_password"


def _load_dash_password() -> str:
    """
    閲覧パスワードを安全に取得する。
    優先順位: ~/.dashboard_password > 環境変数 DASHBOARD_PASSWORD
    どちらも未設定の場合は ValueError を送出する（平文デフォルト値は持たない）。
    """
    # 1. ファイルから読む
    if _PASS_FILE.exists():
        try:
            pw = _PASS_FILE.read_text(encoding="utf-8").strip()
            if pw:
                return pw
        except Exception:
            pass
    # 2. 環境変数から読む
    pw = os.environ.get("DASHBOARD_PASSWORD", "").strip()
    if pw:
        return pw
    # 3. どちらもない → 明示的にエラー
    raise ValueError(
        "ダッシュボード閲覧パスワードが未設定です。\n"
        "設定方法: echo '強固なパスワード' > ~/.dashboard_password && chmod 600 ~/.dashboard_password\n"
        "または: export DASHBOARD_PASSWORD='強固なパスワード'"
    )


DASH_PASSWORD = _load_dash_password()


def log(msg):
    import datetime
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(DEPLOY_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def get_auth_header():
    if not WP_AUTH_FILE.exists():
        return None, "AUTH_FAIL: ~/.wp_auth が存在しない"
    try:
        content = WP_AUTH_FILE.read_text()
        m = re.search(r'Authorization:\s*(Basic\s+\S+)', content, re.IGNORECASE)
        if m:
            return m.group(1), None
        token = content.strip().split()[-1]
        return f"Basic {token}", None
    except Exception as e:
        return None, f"AUTH_FAIL: {e}"


def wp_request(method, path, data=None):
    auth, err = get_auth_header()
    if err:
        return None, err
    url = f"{WP_BASE}{path}"
    headers = {
        "Authorization": auth,
        "Content-Type": "application/json",
        "User-Agent": "kpop-dashboard-deploy/1.0",
    }
    body = json.dumps(data, ensure_ascii=False).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8")), None
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")[:400]
        return None, f"HTTP {e.code}: {body_text}"
    except Exception as e:
        return None, str(e)


def extract_dashboard_content():
    """dashboard.html から <style> + <body> 内容を抽出し、WPページ用HTMLを生成"""
    if not DASHBOARD_HTML.exists():
        return None, "dashboard.html が見つからない"

    html = DASHBOARD_HTML.read_text(encoding="utf-8")

    # <style> タグ全部抽出
    styles = re.findall(r'(<style[^>]*>.*?</style>)', html, re.DOTALL)
    style_block = "\n".join(styles)

    # <body> 内容を抽出
    m = re.search(r'<body[^>]*>(.*)</body>', html, re.DOTALL)
    if not m:
        return None, "bodyタグが見つからない"
    body_content = m.group(1)

    # <script> タグも抽出（bodyの外にある場合）
    # head内のscriptは既にbody内に統合されているのでbody_contentで十分

    # WPのheader/footerを隠すスタイルを追加
    wp_override = """<style>
/* WPヘッダー・フッター非表示（ダッシュボード専用） */
#header, #footer, .site-header, .site-footer,
.navi, .navi-in, #breadcrumb, .entry-title,
.wp-block-group, #wpadminbar { display: none !important; }
body { margin: 0 !important; padding: 0 !important; background: #0a0f1e !important; }
.entry-content { max-width: 100% !important; padding: 0 !important; margin: 0 !important; }
#content, #main, .content-area { max-width: 100% !important; padding: 0 !important; }
</style>"""

    content = f"{wp_override}\n{style_block}\n{body_content}"
    return content, None


def find_existing_page():
    """既存のダッシュボードページIDを検索"""
    resp, err = wp_request("GET", f"/pages?slug={PAGE_SLUG}&per_page=1")
    if err:
        return None, err
    if resp and len(resp) > 0:
        return resp[0].get("id"), None
    return None, None


def create_or_update_page(content):
    """ページ作成または更新"""
    page_data = {
        "title": "KPOP JOURNAL AI Dashboard",
        "content": content,
        "status": "publish",
        "slug": PAGE_SLUG,
        "password": DASH_PASSWORD,
        "comment_status": "closed",
        "ping_status": "closed",
    }

    # 既存ページ検索
    existing_id, err = find_existing_page()
    if err:
        return None, f"ページ検索失敗: {err}"

    if existing_id:
        # 更新
        resp, err = wp_request("POST", f"/pages/{existing_id}", page_data)
        if err:
            return None, f"ページ更新失敗: {err}"
        return resp, "updated"
    else:
        # 新規作成
        resp, err = wp_request("POST", "/pages", page_data)
        if err:
            return None, f"ページ作成失敗: {err}"
        return resp, "created"


def run():
    log("=== ダッシュボードデプロイ開始 ===")

    # コンテンツ抽出
    content, err = extract_dashboard_content()
    if err:
        log(f"❌ コンテンツ抽出失敗: {err}")
        return False

    content_size = len(content)
    log(f"コンテンツサイズ: {content_size:,} bytes")

    # WPページ作成/更新
    resp, action = create_or_update_page(content)
    if resp is None:
        log(f"❌ デプロイ失敗: {action}")
        return False

    page_id   = resp.get("id")
    page_link = resp.get("link", "")
    log(f"✅ ダッシュボード{action}: ID={page_id}")
    log(f"   URL: {page_link}")
    log(f"   パスワード保護: 有効")
    log(f"   閲覧URL: https://www.kpopjournal.tokyo/{PAGE_SLUG}/")

    return True


if __name__ == "__main__":
    ok = run()
    sys.exit(0 if ok else 1)
