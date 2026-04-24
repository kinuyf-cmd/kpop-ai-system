#!/usr/bin/env python3
"""
auto_thumbnail.py — 投稿後アイキャッチ画像自動設定

投稿時にfeatured_mediaが未設定の記事に対し、
タイトルからアーティスト名・ジャンルを推定して
サムネイルを自動生成・WPにアップロード・featured_media設定を行う。

Usage:
  python3 lib/auto_thumbnail.py --post-id 3235
  python3 lib/auto_thumbnail.py --post-id 3235 --dry-run
  python3 lib/auto_thumbnail.py --pending  # featured_media=0の直近記事を一括処理
"""
import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
import urllib.error
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "lib"))

WP_DOMAIN = "https://www.kpopjournal.tokyo"
WP_AUTH = str(Path.home() / ".wp_auth")

# アーティスト名推定マップ（タイトルに含まれるキーワード → 表示名）
ARTIST_MAP = {
    "bts": "BTS", "blackpink": "BLACKPINK", "twice": "TWICE",
    "aespa": "AESPA", "newjeans": "NewJeans", "seventeen": "SEVENTEEN",
    "ive": "IVE", "le sserafim": "LE SSERAFIM", "stray kids": "Stray Kids",
    "enhypen": "ENHYPEN", "nct": "NCT", "txt": "TXT",
    "illit": "ILLIT", "treasure": "TREASURE", "ateez": "ATEEZ",
    "exo": "EXO", "bigbang": "BIGBANG", "g-dragon": "G-Dragon",
    "itzy": "ITZY", "babymonster": "BABYMONSTER", "riize": "RIIZE",
    "nmixx": "NMIXX", "red velvet": "Red Velvet",
}

GENRE_MAP = {
    "コスメ": "beauty", "美容": "beauty", "スキンケア": "beauty",
    "ライブ": "event", "公演": "event", "ツアー": "event", "コンサート": "event",
    "カムバック": "comeback", "新曲": "comeback", "アルバム": "comeback",
    "チャート": "chart", "ランキング": "ranking", "TOP": "ranking",
    "速報": "news", "最新情報": "news", "まとめ": "summary",
}


def detect_artist(title: str) -> str:
    title_lower = title.lower()
    for kw, name in ARTIST_MAP.items():
        if kw in title_lower:
            return name
    return "K-POP"


def detect_genre(title: str) -> str:
    for kw, genre in GENRE_MAP.items():
        if kw in title:
            return genre
    return "analysis"


def extract_thumb_copy(title: str) -> str:
    """タイトルからサムネイルコピー（2行・各8文字以内）を生成"""
    # パイプ区切りの場合、前半を使用
    parts = re.split(r'[｜|]', title)
    main = parts[0].strip()

    # 括弧内を除去
    main = re.sub(r'[【】\[\]（）()]', '', main)

    # 15文字以内に収める（2行構成）
    if len(main) > 15:
        # 中点・句読点で分割
        split_chars = ['・', '、', '　', ' ', '—', '──', '｜']
        for sc in split_chars:
            if sc in main:
                p = main.split(sc, 1)
                line1 = p[0].strip()[:8]
                line2 = p[1].strip()[:8]
                return f"{line1}\n{line2}"
        # 分割できない場合は前半・後半
        mid = len(main) // 2
        return f"{main[:8]}\n{main[8:16]}"

    return main


def get_post(post_id: int) -> dict | None:
    """WP APIから記事情報を取得"""
    url = f"{WP_DOMAIN}/wp-json/wp/v2/posts/{post_id}?_fields=id,title,featured_media,slug,link"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "auto-thumb/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"  [error] WP API: {e}")
        return None


def get_pending_posts(hours: int = 24) -> list[dict]:
    """featured_media=0の直近記事を取得"""
    from datetime import datetime, timezone, timedelta
    after = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S")
    url = f"{WP_DOMAIN}/wp-json/wp/v2/posts?after={after}&per_page=20&_fields=id,title,featured_media,slug"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "auto-thumb/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            posts = json.loads(resp.read().decode("utf-8"))
        return [p for p in posts if p.get("featured_media", 0) == 0]
    except Exception as e:
        print(f"  [error] WP API: {e}")
        return []


def generate_and_set_thumbnail(post_id: int, title: str, slug: str, dry_run: bool = False) -> bool:
    """サムネイルを生成してWPに設定"""
    artist = detect_artist(title)
    genre = detect_genre(title)
    copy_text = extract_thumb_copy(title)

    print(f"  アーティスト: {artist}")
    print(f"  ジャンル: {genre}")
    print(f"  コピー: {copy_text!r}")

    if dry_run:
        print("  [dry-run] サムネイル生成・アップロードをスキップ")
        return True

    # make_thumbnail.py で生成
    try:
        cmd = [
            sys.executable, str(BASE / "make_thumbnail.py"),
            "--layout", "v4",
            "--artist", artist,
            "--copy", copy_text,
            "--genre", genre,
            "--output", str(thumb_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, cwd=str(BASE))
        if result.returncode != 0:
            print(f"  [warn] サムネイル生成失敗: {result.stderr[:200]}")
            return False
    except FileNotFoundError:
        print("  [warn] make_thumbnail.py が見つかりません")
        return False
    except Exception as e:
        print(f"  [warn] サムネイル生成エラー: {e}")
        return False

    # make_thumbnail.py は thumbnail.webp/jpg を cwd に生成する
    thumb_webp = BASE / "thumbnail.webp"
    thumb_jpg = BASE / "thumbnail.jpg"
    actual_thumb = thumb_webp if thumb_webp.exists() else thumb_jpg
    if not actual_thumb.exists():
        print("  [warn] サムネイルファイルが生成されませんでした")
        return False

    # WP Media APIにアップロード
    try:
        import time
        unique_name = f"kpop-auto-{int(time.time())}_{post_id}.webp" if actual_thumb.suffix == ".webp" else f"kpop-auto-{int(time.time())}_{post_id}.jpg"
        content_type = "image/webp" if actual_thumb.suffix == ".webp" else "image/jpeg"
        upload_cmd = [
            "curl", "-s", "-X", "POST",
            f"{WP_DOMAIN}/wp-json/wp/v2/media",
            "-K", WP_AUTH,
            "-H", f"Content-Disposition: attachment; filename={unique_name}",
            "-H", f"Content-Type: {content_type}",
            "--data-binary", f"@{actual_thumb}",
        ]
        upload_result = subprocess.run(upload_cmd, capture_output=True, text=True, timeout=30)
        media = json.loads(upload_result.stdout)
        media_id = media.get("id")
        if not media_id:
            print(f"  [warn] メディアアップロード失敗: {upload_result.stdout[:200]}")
            return False
        print(f"  メディアID: {media_id}")
    except Exception as e:
        print(f"  [error] アップロード失敗: {e}")
        return False

    # alt_text を設定
    try:
        alt_text = re.sub(r'[【】「」『』|｜]', ' ', title).strip()
        alt_text = re.sub(r'\s+', ' ', alt_text)[:100]
        alt_cmd = [
            "curl", "-s", "-X", "POST",
            f"{WP_DOMAIN}/wp-json/wp/v2/media/{media_id}",
            "-K", WP_AUTH,
            "-H", "Content-Type: application/json",
            "-d", json.dumps({"alt_text": alt_text}),
        ]
        subprocess.run(alt_cmd, capture_output=True, text=True, timeout=15)
    except Exception:
        pass

    # featured_media を設定
    try:
        set_cmd = [
            "curl", "-s", "-X", "POST",
            f"{WP_DOMAIN}/wp-json/wp/v2/posts/{post_id}",
            "-K", WP_AUTH,
            "-H", "Content-Type: application/json",
            "-d", json.dumps({"featured_media": media_id}),
        ]
        set_result = subprocess.run(set_cmd, capture_output=True, text=True, timeout=15)
        resp = json.loads(set_result.stdout)
        if resp.get("featured_media") == media_id:
            print(f"  ✅ featured_media設定完了: post_id={post_id} media_id={media_id}")
            return True
        else:
            print(f"  [warn] featured_media設定確認できず")
            return False
    except Exception as e:
        print(f"  [error] featured_media設定失敗: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="投稿後アイキャッチ画像自動設定")
    parser.add_argument("--post-id", type=int, help="特定の記事ID")
    parser.add_argument("--pending", action="store_true", help="featured_media=0の直近記事を一括処理")
    parser.add_argument("--hours", type=int, default=24, help="対象期間（--pending時）")
    parser.add_argument("--dry-run", action="store_true", help="生成のみ・アップロードなし")
    args = parser.parse_args()

    if args.post_id:
        post = get_post(args.post_id)
        if not post:
            print(f"❌ 記事ID {args.post_id} が見つかりません")
            sys.exit(1)
        title = post.get("title", {})
        title = title.get("rendered", "") if isinstance(title, dict) else str(title)
        slug = post.get("slug", "")
        fm = post.get("featured_media", 0)

        print(f"=== auto_thumbnail: ID={args.post_id} ===")
        print(f"  タイトル: {title[:50]}")
        print(f"  現在のfeatured_media: {fm}")

        if fm > 0 and not args.dry_run:
            print("  ✅ アイキャッチ画像は既に設定済み。スキップします。")
            return

        success = generate_and_set_thumbnail(args.post_id, title, slug, args.dry_run)
        sys.exit(0 if success else 1)

    elif args.pending:
        print(f"=== auto_thumbnail: 直近{args.hours}時間のfeatured_media未設定記事 ===")
        posts = get_pending_posts(args.hours)
        print(f"  対象: {len(posts)}件")

        for post in posts:
            pid = post["id"]
            title = post.get("title", {})
            title = title.get("rendered", "") if isinstance(title, dict) else str(title)
            slug = post.get("slug", "")
            print(f"\n--- ID:{pid} {title[:40]}... ---")
            generate_and_set_thumbnail(pid, title, slug, args.dry_run)

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
