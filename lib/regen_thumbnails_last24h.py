#!/usr/bin/env python3
"""過去24時間の記事サムネを v4 レイアウトで再生成し featured_media を差し替える

手動キュレーション方式: 25記事の artist/copy/genre を明示マップで指定。
各記事について:
  1. resolve_featured_image.py で Wikimedia 画像を取得（アー名不明なら None）
  2. make_thumbnail.py --layout v4 で v4 サムネ生成（写真あり/写真なし自動分岐）
  3. WP Media API にアップロード → 新しい media_id を取得
  4. 記事の featured_media を新 media_id に更新

実行:
  source .venv/bin/activate
  python3 lib/regen_thumbnails_last24h.py --dry-run  # 生成のみ
  python3 lib/regen_thumbnails_last24h.py            # アップロード＋差し替え
"""
from __future__ import annotations
from lib.thumbnail_guard import safe_update_featured_media as _guard_update
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
WP_DOMAIN = "https://www.kpopjournal.tokyo"
WP_AUTH = str(Path.home() / ".wp_auth")
TMP_DIR = BASE / "logs" / "thumb_regen_20260417"
TMP_DIR.mkdir(parents=True, exist_ok=True)

# ── 手動キュレーションマップ ──
# (post_id, artist, copy(≤15字), genre)
ARTICLES = [
    (2967, "K-POP",     "ペンライト同期ゼロ問題",   "buzz"),
    (2861, "AESPA",     "2026年全展開予測",       "analysis"),
    (2860, "AESPA",     "人気曲TOP15総覧",        "ranking"),
    (2859, "AESPA",     "初心者30分入門",         "beginner"),
    (2858, "AESPA",     "4人関係性相関図",        "analysis"),
    (2857, "AESPA",     "4人メンバー経歴総覧",    "analysis"),
    (2856, "BLACKPINK", "2026年4人復帰予測",      "analysis"),
    (2855, "BLACKPINK", "人気曲TOP15総覧",        "ranking"),
    (2854, "BLACKPINK", "BLINKデビュー入門",      "beginner"),
    (2853, "BLACKPINK", "4人関係性YG裏史",        "analysis"),
    (2852, "BLACKPINK", "4人メンバー経歴総覧",    "analysis"),
    (2851, "BTS",       "2026下半期全予測",       "analysis"),
    (2850, "BTS",       "人気曲TOP15総覧",        "ranking"),
    (2849, "BTS",       "ARMY入門30分講座",       "beginner"),
    (2848, "BTS",       "7人関係性SOPE相関図",    "analysis"),
    (2847, "BTS",       "7人メンバー経歴総覧",    "analysis"),
    (2826, "K-POP",     "聖地巡礼2026激変マップ", "travel"),
    (2809, "DEMON HUNTERS", "続編考察3つの伏線",   "analysis"),
    (2808, "DEMON HUNTERS", "OST全12曲完全解説",   "analysis"),
    (2807, "DEMON HUNTERS", "全10話ネタバレ総覧",  "analysis"),
    (2806, "DEMON HUNTERS", "相関図5人組全整理",   "analysis"),
    (2805, "DEMON HUNTERS", "声優5人経歴総覧",     "analysis"),
    (2798, "K-POP",     "韓国コスメ真似100%",     "beauty"),
    (2797, "K-POP",     "音楽サブスク4社比較",    "analysis"),
    (2647, "TWICE",     "サナMV3000万回突破",    "breaking"),
]


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def get_post_title(post_id: int) -> str:
    url = f"{WP_DOMAIN}/wp-json/wp/v2/posts/{post_id}?_fields=title"
    r = run(["curl", "-s", "-K", WP_AUTH, url], timeout=20)
    try:
        return json.loads(r.stdout).get("title", {}).get("rendered", "")
    except Exception:
        return ""


def fetch_wikimedia_photo(artist: str) -> str | None:
    """Wikimedia からアーティスト写真を取得（Tier1 アー名のみ許可）"""
    if not artist:
        return None
    # make_thumbnail.py と同じ ARTISTS_TIER1 をインポートして照合
    try:
        sys.path.insert(0, str(BASE))
        from make_thumbnail import _ARTISTS_TIER1_LOOKUP
        if artist.upper().replace(" ", "") not in _ARTISTS_TIER1_LOOKUP:
            return None  # Tier1 以外は写真を探さない（誤画像の温床）
    except Exception:
        return None
    try:
        sys.path.insert(0, str(BASE / "lib"))
        from wikimedia import fetch_safe_image
        cache_dir = str(BASE / "assets" / "artist_cache")
        p = fetch_safe_image(artist, cache_dir)
        return p if p and os.path.exists(p) else None
    except Exception as e:
        print(f"  [wikimedia] fail {artist}: {e}", file=sys.stderr)
        return None


def generate_thumbnail(post_id: int, artist: str, copy: str, genre: str,
                        title: str) -> Path | None:
    """サムネ生成 → tmp パスを返す"""
    # 写真取得（アー名がTier1 or "K-POP"以外）
    photo = fetch_wikimedia_photo(artist)

    cmd = [
        "python3", str(BASE / "make_thumbnail.py"),
        f"{artist}\n{copy}",
        "--layout", "v4",
        "--genre", genre,
        "--title", title,
        "--artist", artist,
        "--copy", copy,
    ]
    if photo:
        cmd += ["--bg-image", photo]

    r = run(cmd, cwd=str(BASE), timeout=60)
    if r.returncode != 0:
        print(f"  [gen] FAIL post_id={post_id}: {r.stderr[:200]}", file=sys.stderr)
        return None

    src_jpg = BASE / "thumbnail.jpg"
    src_webp = BASE / "thumbnail.webp"
    if not src_jpg.exists():
        print(f"  [gen] missing thumbnail.jpg for post_id={post_id}", file=sys.stderr)
        return None

    dst_jpg = TMP_DIR / f"post_{post_id}.jpg"
    dst_webp = TMP_DIR / f"post_{post_id}.webp"
    shutil.copy(src_jpg, dst_jpg)
    if src_webp.exists():
        shutil.copy(src_webp, dst_webp)
    return dst_jpg


def upload_media(jpg_path: Path, slug_hint: str, alt_text: str = '') -> int | None:
    """WP Media API に JPG をアップロード → media_id を返す

    alt_text が指定されない場合、slug_hint からalt を自動生成する。
    """
    url = f"{WP_DOMAIN}/wp-json/wp/v2/media"
    fname = f"kpop-v4-{slug_hint}.jpg"
    cmd = [
        "curl", "-s", "-K", WP_AUTH,
        "-X", "POST", url,
        "-H", f"Content-Disposition: attachment; filename={fname}",
        "-H", "Content-Type: image/jpeg",
        "--data-binary", f"@{jpg_path}",
    ]
    r = run(cmd, timeout=60)
    try:
        data = json.loads(r.stdout)
        mid = data.get("id")
        if mid:
            mid = int(mid)
            # alt_text 自動設定 (2026-05-06追加: alt空再発防止)
            _alt = alt_text or f"{slug_hint.replace('-', ' ').replace('thumb ', '').strip()}のサムネイル画像"
            _alt_cmd = [
                "curl", "-s", "-K", WP_AUTH,
                "-X", "POST", f"{WP_DOMAIN}/wp-json/wp/v2/media/{mid}",
                "-H", "Content-Type: application/json",
                "-d", json.dumps({"alt_text": _alt}),
            ]
            run(_alt_cmd, timeout=15)
            return mid
        print(f"  [upload] FAIL: {r.stdout[:300]}", file=sys.stderr)
    except Exception as e:
        print(f"  [upload] parse fail: {e} / {r.stdout[:200]}", file=sys.stderr)
    return None


def update_featured_media(post_id: int, media_id: int) -> bool:
    """post の featured_media を更新"""
    url = f"{WP_DOMAIN}/wp-json/wp/v2/posts/{post_id}"
    body = json.dumps({"featured_media": media_id})
    cmd = [
        "curl", "-s", "-K", WP_AUTH,
        "-X", "POST", url,
        "-H", "Content-Type: application/json",
        "--data", body,
    ]
    r = run(cmd, timeout=30)
    try:
        data = json.loads(r.stdout)
        return int(data.get("featured_media", -1)) == media_id
    except Exception:
        return False


def update_media_alt(media_id: int, alt: str) -> None:
    """alt テキストを設定（サムネalt空回帰防止）"""
    url = f"{WP_DOMAIN}/wp-json/wp/v2/media/{media_id}"
    body = json.dumps({"alt_text": alt})
    cmd = [
        "curl", "-s", "-K", WP_AUTH,
        "-X", "POST", url,
        "-H", "Content-Type: application/json",
        "--data", body,
    ]
    run(cmd, timeout=20)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="生成のみ、アップロードしない")
    ap.add_argument("--limit", type=int, default=0, help="最初のN件のみ実行")
    ap.add_argument("--only", type=int, default=0, help="特定 post_id のみ")
    args = ap.parse_args()

    results = []
    targets = ARTICLES
    if args.only:
        targets = [a for a in ARTICLES if a[0] == args.only]
    if args.limit:
        targets = targets[:args.limit]

    for post_id, artist, copy, genre in targets:
        print(f"\n=== post_id={post_id} artist={artist} copy={copy} genre={genre} ===")
        title = get_post_title(post_id)
        print(f"  title: {title[:60]}")

        jpg_path = generate_thumbnail(post_id, artist, copy, genre, title)
        if not jpg_path:
            results.append({"post_id": post_id, "status": "gen_fail"})
            continue

        if args.dry_run:
            print(f"  [dry-run] generated: {jpg_path}")
            results.append({"post_id": post_id, "status": "dry_run", "jpg": str(jpg_path)})
            continue

        slug = f"{post_id}-{artist.lower().replace(' ', '-')}"
        media_id = upload_media(jpg_path, slug)
        if not media_id:
            results.append({"post_id": post_id, "status": "upload_fail"})
            continue

        alt = f"{artist} {copy}"
        update_media_alt(media_id, alt)

        ok = update_featured_media(post_id, media_id)
        status = "replaced" if ok else "update_fail"
        print(f"  media_id={media_id} featured_media_update={ok}")
        results.append({
            "post_id": post_id, "status": status,
            "new_media_id": media_id, "artist": artist, "copy": copy,
        })

        # rate limit soft pause
        time.sleep(1)

    # ログ保存
    log = TMP_DIR / "regen_log.jsonl"
    with log.open("w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    ok = sum(1 for r in results if r["status"] == "replaced")
    print(f"\n=== SUMMARY: {ok}/{len(results)} replaced ===")
    print(f"log: {log}")


if __name__ == "__main__":
    main()
