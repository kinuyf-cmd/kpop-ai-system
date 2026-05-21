"""
既存投稿の修復スクリプト

修復内容:
1. Claude CLI JSONメタデータ除去
2. AdSense scriptタグ削除（プラグインの動的挿入に任せる）
3. URL-encoded日本語slug → 適切なslugに置換
4. 連続改行整理

Usage:
  python3 lib/repair_post.py 2095
  python3 lib/repair_post.py 2095 --dry-run
  python3 lib/repair_post.py --all-encoded-slugs   # 全エンコードslug投稿を一括修復
"""
import json
import os
import re
import sys
import urllib.parse
import urllib.request

API = "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts"

# slug.py を import
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from slug import make_slug


def _wp_auth_header() -> str:
    """~/.wp_auth (curl config形式) から Authorization ヘッダ値を読む。
    フォールバック: WP_USER / WP_PASS 環境変数から生成。
    戻り値: 'Authorization: Basic xxxx' の文字列。
    """
    import re as _re
    import base64
    wp_auth_path = os.path.expanduser("~/.wp_auth")
    if os.path.exists(wp_auth_path):
        with open(wp_auth_path) as f:
            for line in f:
                m = _re.match(r'header\s*=\s*"(Authorization:\s*Basic\s+[^"\\n]+)"?', line.strip())
                if m:
                    return m.group(1)
    # フォールバック: 環境変数
    user = os.environ.get("WP_USER", "")
    passwd = os.environ.get("WP_PASS", "")
    token = base64.b64encode(f"{user}:{passwd}".encode()).decode()
    return f"Authorization: Basic {token}"


def basic_auth_header():
    _auth = _wp_auth_header()
    return _auth.split(": ", 1)[1] if ": " in _auth else _auth


def fetch_post(post_id):
    req = urllib.request.Request(
        f"{API}/{post_id}?context=edit",
        headers={"Authorization": basic_auth_header()},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def update_post(post_id, payload):
    req = urllib.request.Request(
        f"{API}/{post_id}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": basic_auth_header(),
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def clean_content(content):
    """本文をクリーニング"""
    fixes = []

    # [1] Claude CLI JSON結果除去
    new = re.sub(r'\{"type"\s*:\s*"result".*?"terminal_reason"\s*:\s*"[^"]*"[^}]*\}', '', content, flags=re.DOTALL)
    if new != content:
        fixes.append("Claude CLI JSON除去")
        content = new

    new = re.sub(r'"modelUsage"\s*:\s*\{.*?"costUSD"\s*:\s*[\d.]+[^}]*\}[^}]*\}', '', content, flags=re.DOTALL)
    if new != content:
        fixes.append("modelUsage除去")
        content = new

    # [2] AdSense scriptブロック除去（プラグインの動的挿入に任せる）
    # <div id="kpopj-XXXXX">...</div> ブロック全体を削除
    new = re.sub(
        r'<div\s+id="kpopj-\d+"[^>]*>.*?</div>',
        '',
        content,
        flags=re.DOTALL,
    )
    if new != content:
        fixes.append("AdSense kpopj-ブロック除去")
        content = new

    # 単独の adsbygoogle script も除去
    new = re.sub(
        r'<script[^>]*googlesyndication[^>]*></script>',
        '',
        content,
    )
    new = re.sub(
        r'<ins\s+class="adsbygoogle"[^>]*></ins>',
        '',
        new,
    )
    new = re.sub(
        r'<script>(<br\s*/?>\s*)*\(adsbygoogle.*?\.push\(\{\}\);(<br\s*/?>\s*)*</script>',
        '',
        new,
        flags=re.DOTALL,
    )
    if new != content:
        fixes.append("AdSense script/ins除去")
        content = new

    # [3] 連続改行整理
    new = re.sub(r'\n{3,}', '\n\n', content)
    if new != content:
        fixes.append("連続改行整理")
        content = new

    # [4] HTMLコメント除去（<!-- 見出し3 --> 等）
    new = re.sub(r'<!--[^>]*-->', '', content)
    if new != content:
        fixes.append("HTMLコメント除去")
        content = new

    return content.strip(), fixes


def needs_slug_fix(slug):
    """slugがエンコード日本語かどうか"""
    if not slug:
        return True
    if re.search(r'%[0-9a-fA-F]{2}', slug):
        return True
    if not all(ord(c) < 128 for c in slug):
        return True
    return False


def repair(post_id, dry_run=False):
    print(f"=== Repair post {post_id} ===")
    post = fetch_post(post_id)
    title = post.get("title", {}).get("raw", "") or post.get("title", {}).get("rendered", "")
    content = post.get("content", {}).get("raw", "") or post.get("content", {}).get("rendered", "")
    slug = post.get("slug", "")

    print(f"Title : {title[:60]}")
    print(f"Slug  : {slug[:60]}")
    print(f"Content: {len(content)} chars")

    payload = {}
    fix_log = []

    # 本文クリーニング
    new_content, fixes = clean_content(content)
    if fixes:
        payload["content"] = new_content
        fix_log.extend(fixes)
        print(f"  content: {len(content)} → {len(new_content)} chars, fixes: {fixes}")

    # slug 修復
    if needs_slug_fix(slug):
        new_slug = make_slug(title)
        payload["slug"] = new_slug
        fix_log.append(f"slug: {slug[:30]}... → {new_slug}")
        print(f"  slug: {new_slug}")

    if not payload:
        print("  → 修復不要")
        return

    if dry_run:
        print(f"  [DRY-RUN] 適用しない: {fix_log}")
        return

    print(f"  → 適用: {len(fix_log)} fixes")
    result = update_post(post_id, payload)
    print(f"  ✅ updated: {result.get('link', '')}")


def find_encoded_slug_posts():
    """全投稿からエンコードslugを持つものを抽出"""
    page = 1
    found = []
    while True:
        req = urllib.request.Request(
            f"{API}?per_page=50&page={page}&orderby=id&order=desc",
            headers={"Authorization": basic_auth_header()},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                posts = json.loads(r.read())
        except Exception as e:
            print(f"page {page} fetch error: {e}")
            break
        if not posts:
            break
        for p in posts:
            if needs_slug_fix(p.get("slug", "")):
                found.append((p["id"], p.get("slug", "")[:60], p.get("title", {}).get("rendered", "")[:50]))
        if len(posts) < 50:
            break
        page += 1
    return found


def main():
    if not basic_auth_header():
        print("ERROR: WP credentials not found (~/.wp_auth or WP_USER/WP_PASS)")
        sys.exit(1)

    args = sys.argv[1:]
    dry = "--dry-run" in args
    args = [a for a in args if a != "--dry-run"]

    if "--all-encoded-slugs" in args:
        print("Searching for posts with encoded slugs...")
        posts = find_encoded_slug_posts()
        print(f"Found {len(posts)} posts with encoded slugs:")
        for pid, slug, title in posts:
            print(f"  {pid}: {slug} | {title}")
        if not dry:
            print("\nUse --dry-run to preview without applying. Re-run without --dry-run to actually repair.")
        return

    if not args:
        print(__doc__)
        sys.exit(1)

    for pid in args:
        repair(int(pid), dry_run=dry)


if __name__ == "__main__":
    main()
