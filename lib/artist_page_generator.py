#!/usr/bin/env python3
"""artist_page_generator.py -- アーティスト別まとめページ自動生成

WP REST API でアーティストカテゴリの記事を取得し、
プロフィール + 最新ニュース一覧のまとめページ(固定ページ)HTML を生成する。

使い方:
  python3 lib/artist_page_generator.py --artist bts
  python3 lib/artist_page_generator.py --artist bts --publish
  python3 lib/artist_page_generator.py --all --dry-run
  python3 lib/artist_page_generator.py --list
"""
from __future__ import annotations

import argparse
import base64
import html
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

# ---------- 定数 ----------
BASE = Path(__file__).resolve().parent.parent
PROFILES_JSON = BASE / "config" / "artist_profiles.json"
CATEGORY_MAP = BASE / "config" / "artist_category_map.json"
LOGS = BASE / "logs"
LOG_FILE = LOGS / "artist_page_generation.jsonl"

WP_URL = "https://www.kpopjournal.tokyo"
WP_API = f"{WP_URL}/wp-json/wp/v2"
WP_AUTH_FILE = Path.home() / ".wp_auth"
JST = timezone(timedelta(hours=9))

# 対象アーティスト (要件で指定された16組)
TARGET_ARTISTS = [
    "bts", "blackpink", "aespa", "twice", "ive", "newjeans",
    "le_sserafim", "stray_kids", "seventeen", "enhypen",
    "itzy", "nmixx", "babymonster", "exo", "nct", "bigbang",
]

LATEST_ARTICLES_COUNT = 5


# ---------- 認証 ----------
def _build_auth_header() -> str:
    """WP_USER / WP_PASS 環境変数から Basic 認証ヘッダ値を生成。
    フォールバックで ~/.wp_auth も参照する。"""
    user = os.environ.get("WP_USER", "")
    passwd = os.environ.get("WP_PASS", "")
    if user and passwd:
        token = base64.b64encode(f"{user}:{passwd}".encode()).decode()
        return f"Basic {token}"
    # フォールバック: ~/.wp_auth
    if WP_AUTH_FILE.exists():
        import re
        for line in WP_AUTH_FILE.read_text().splitlines():
            m = re.match(
                r'header\s*=\s*"Authorization:\s*Basic\s+([^"\\n]+)"?',
                line.strip(),
            )
            if m:
                return f"Basic {m.group(1)}"
    return ""


# ---------- WP API (subprocess curl) ----------
def wp_api_get(endpoint: str, params: dict[str, Any] | None = None) -> Any:
    """WP REST API を subprocess.run(['curl',...]) で GET する。"""
    url = f"{WP_API}/{endpoint}"
    if params:
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{url}?{qs}"

    auth = _build_auth_header()
    cmd = ["curl", "-s", "-X", "GET", url]
    if auth:
        cmd += ["-H", f"Authorization: {auth}"]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"curl failed: {result.stderr}")
    return json.loads(result.stdout)


def wp_api_post(endpoint: str, payload: dict) -> Any:
    """WP REST API を subprocess.run(['curl',...]) で POST する。"""
    url = f"{WP_API}/{endpoint}"
    auth = _build_auth_header()
    if not auth:
        raise RuntimeError("WP認証情報が見つかりません (WP_USER/WP_PASS または ~/.wp_auth)")

    body = json.dumps(payload, ensure_ascii=False)
    cmd = [
        "curl", "-s", "-X", "POST", url,
        "-H", f"Authorization: {auth}",
        "-H", "Content-Type: application/json",
        "--data-binary", body,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"curl POST failed: {result.stderr}")
    return json.loads(result.stdout)


# ---------- プロフィール読み込み ----------
def load_profiles() -> dict[str, dict]:
    """config/artist_profiles.json を読み込む。"""
    if not PROFILES_JSON.exists():
        print(f"ERROR: {PROFILES_JSON} が見つかりません", file=sys.stderr)
        sys.exit(1)
    with open(PROFILES_JSON, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("profiles", {})


def load_category_map() -> dict[str, int]:
    """config/artist_category_map.json を読み込む。"""
    if not CATEGORY_MAP.exists():
        return {}
    with open(CATEGORY_MAP, encoding="utf-8") as f:
        return json.load(f)


# ---------- WP記事取得 ----------
def fetch_articles_by_category(category_id: int, count: int = LATEST_ARTICLES_COUNT) -> list[dict]:
    """WP REST API でカテゴリの最新記事を取得する。"""
    try:
        posts = wp_api_get("posts", {
            "categories": category_id,
            "per_page": count,
            "orderby": "date",
            "order": "desc",
            "status": "publish",
            "_fields": "id,title,link,date,excerpt",
        })
        if isinstance(posts, list):
            return posts
    except Exception as e:
        print(f"  WARNING: 記事取得失敗 (category={category_id}): {e}", file=sys.stderr)
    return []


# ---------- まとめページ HTML 生成 ----------
def build_summary_page(artist_id: str, profile: dict, articles: list[dict]) -> dict:
    """アーティスト別まとめページの HTML を生成する。

    Returns:
        dict with keys: title, content, slug, category_id
    """
    name = profile["display_name"]
    name_en = profile.get("name_en", "")
    agency = profile.get("agency", "不明")
    debut_year = profile.get("debut_year", "不明")
    members = profile.get("members", [])
    description = profile.get("description", "")
    category_id = profile.get("wp_category_id", 1)
    category_slug = profile.get("category_slug", artist_id)

    today = datetime.now(JST).strftime("%Y年%m月%d日")

    # --- HTML 構築 ---
    parts: list[str] = []

    # プロフィールセクション
    parts.append(f'<h2>{name} プロフィール</h2>')
    parts.append('<div class="artist-profile-card">')
    parts.append("<table>")
    parts.append(f"<tr><th>グループ名</th><td>{html.escape(name)}</td></tr>")
    if name_en:
        parts.append(f"<tr><th>英語名</th><td>{html.escape(name_en)}</td></tr>")
    parts.append(f"<tr><th>所属事務所</th><td>{html.escape(agency)}</td></tr>")
    parts.append(f"<tr><th>デビュー年</th><td>{debut_year}年</td></tr>")
    if members:
        members_str = "、".join(html.escape(m) for m in members)
        parts.append(f"<tr><th>メンバー</th><td>{members_str}</td></tr>")
        parts.append(f"<tr><th>人数</th><td>{len(members)}人</td></tr>")
    parts.append("</table>")
    parts.append("</div>")

    if description:
        parts.append(f"<p>{html.escape(description)}</p>")

    # 最新ニュースセクション
    parts.append(f'<h2>{name} 最新ニュース</h2>')
    if articles:
        parts.append("<ul>")
        for post in articles:
            title_text = post.get("title", {}).get("rendered", "無題")
            link = post.get("link", "#")
            date_str = post.get("date", "")
            if date_str:
                try:
                    dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                    date_label = dt.strftime("%Y/%m/%d")
                except (ValueError, TypeError):
                    date_label = ""
            else:
                date_label = ""
            date_prefix = f"<span class=\"post-date\">{date_label}</span> " if date_label else ""
            parts.append(
                f'  <li>{date_prefix}<a href="{html.escape(link)}">{title_text}</a></li>'
            )
        parts.append("</ul>")
    else:
        parts.append(f"<p>{name}の最新記事はまだありません。</p>")

    # もっと見るリンク
    category_url = f"{WP_URL}/category/{category_slug}/"
    parts.append(
        f'<p class="more-link"><a href="{category_url}">'
        f'{name}の記事をもっと見る &raquo;</a></p>'
    )

    # 更新日
    parts.append(f'<p class="last-updated">最終更新: {today}</p>')

    content_html = "\n".join(parts)
    title = f"{name}まとめ｜プロフィール・メンバー・最新ニュース"
    slug = f"{artist_id.replace('_', '-')}-matome"

    return {
        "title": title,
        "content": content_html,
        "slug": slug,
        "category_id": category_id,
    }


# ---------- WP投稿 ----------
def publish_to_wp(page_data: dict, post_type: str = "pages", status: str = "draft") -> dict:
    """生成したまとめページを WP に投稿する (固定ページ)。"""
    payload = {
        "title": page_data["title"],
        "content": page_data["content"],
        "slug": page_data["slug"],
        "status": status,
    }
    try:
        result = wp_api_post(post_type, payload)
        if isinstance(result, dict) and result.get("id"):
            return {
                "success": True,
                "post_id": result["id"],
                "url": result.get("link", ""),
            }
        error_msg = result.get("message", str(result)) if isinstance(result, dict) else str(result)
        return {"success": False, "error": error_msg}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ---------- ログ ----------
def log_result(artist_id: str, action: str, detail: dict):
    LOGS.mkdir(exist_ok=True)
    entry = {
        "timestamp": datetime.now(JST).isoformat(),
        "artist": artist_id,
        "action": action,
        **detail,
    }
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ---------- メイン処理 ----------
def process_artist(
    artist_id: str,
    profiles: dict[str, dict],
    category_map: dict[str, int],
    *,
    dry_run: bool = False,
    publish: bool = False,
) -> dict:
    """1アーティスト分のまとめページ生成処理。"""
    profile = profiles.get(artist_id)
    if not profile:
        return {"status": "error", "error": f"プロフィール未定義: {artist_id}"}

    # カテゴリID の解決 (category_map > profile)
    cat_id = category_map.get(profile.get("name_en", ""), 0) or profile.get("wp_category_id", 0)
    if not cat_id:
        return {"status": "error", "error": f"カテゴリID不明: {artist_id}"}

    # 記事取得
    if dry_run:
        articles = []
        print(f"  [DRY-RUN] カテゴリ {cat_id} の記事取得をスキップ")
    else:
        articles = fetch_articles_by_category(cat_id, LATEST_ARTICLES_COUNT)
        print(f"  取得記事数: {len(articles)}")

    # HTML 生成
    page_data = build_summary_page(artist_id, profile, articles)
    print(f"  タイトル: {page_data['title']}")
    print(f"  スラッグ: {page_data['slug']}")
    print(f"  HTML長: {len(page_data['content'])} chars")

    # 出力ファイル保存 (常に)
    out_dir = LOGS / "artist_pages"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{artist_id}_matome.html"
    out_file.write_text(
        f"<!-- title: {page_data['title']} -->\n"
        f"<h1>{html.escape(profile['display_name'])}</h1>\n"
        f"{page_data['content']}",
        encoding="utf-8",
    )
    print(f"  ファイル保存: {out_file}")

    # WP投稿
    if publish and not dry_run:
        wp_result = publish_to_wp(page_data, post_type="pages", status="draft")
        if wp_result.get("success"):
            print(f"  WP投稿完了: ID={wp_result['post_id']} URL={wp_result['url']}")
            log_result(artist_id, "published", wp_result)
        else:
            print(f"  WP投稿失敗: {wp_result.get('error', '')}")
            log_result(artist_id, "publish_failed", wp_result)
        return {"status": "published" if wp_result.get("success") else "publish_failed", **wp_result}

    log_result(artist_id, "generated", {"file": str(out_file), "articles": len(articles)})
    return {"status": "generated", "file": str(out_file), "articles": len(articles)}


def main():
    parser = argparse.ArgumentParser(description="アーティスト別まとめページ生成")
    parser.add_argument("--artist", help="アーティストID（例: bts, blackpink, le_sserafim）")
    parser.add_argument("--all", action="store_true", help="全対象アーティスト一括生成")
    parser.add_argument("--list", action="store_true", help="対象アーティスト一覧を表示")
    parser.add_argument("--dry-run", action="store_true", help="WP API呼び出しをスキップ")
    parser.add_argument("--publish", action="store_true",
                        help="生成した固定ページをWPにdraft投稿する")
    args = parser.parse_args()

    profiles = load_profiles()
    category_map = load_category_map()

    if args.list:
        print(f"=== 対象アーティスト ({len(TARGET_ARTISTS)}組) ===")
        for aid in TARGET_ARTISTS:
            p = profiles.get(aid, {})
            name = p.get("display_name", aid)
            cat = category_map.get(p.get("name_en", ""), 0) or p.get("wp_category_id", 0)
            print(f"  {aid:20s} {name:25s} category_id={cat}")
        return

    targets: list[str] = []
    if args.artist:
        if args.artist not in profiles:
            print(f"ERROR: '{args.artist}' はプロフィール未定義です", file=sys.stderr)
            print(f"対象: {', '.join(TARGET_ARTISTS)}", file=sys.stderr)
            sys.exit(1)
        targets = [args.artist]
    elif args.all:
        targets = TARGET_ARTISTS
    else:
        parser.print_help()
        sys.exit(1)

    print(f"=== アーティスト別まとめページ生成 ===")
    print(f"対象: {len(targets)}組 / dry-run: {args.dry_run} / publish: {args.publish}")
    print()

    stats = {"generated": 0, "published": 0, "error": 0}

    for i, aid in enumerate(targets, 1):
        print(f"[{i}/{len(targets)}] {aid}")
        result = process_artist(
            aid, profiles, category_map,
            dry_run=args.dry_run, publish=args.publish,
        )
        status = result.get("status", "error")
        if status in ("generated", "published"):
            stats[status if status == "published" else "generated"] += 1
        else:
            stats["error"] += 1
        print()

        # レート制限回避
        if not args.dry_run and i < len(targets):
            time.sleep(2)

    print("=== 完了 ===")
    print(f"  生成: {stats['generated']} / 投稿: {stats['published']} / エラー: {stats['error']}")


if __name__ == "__main__":
    main()
