#!/usr/bin/env python3
"""resolve_featured_image.py — Phase 3 アイキャッチ画像リゾルバ

モデルサイト（kstyle/daebak）方式に寄せるため、サムネ画像の供給元を階層化する:
  1. 記事本文内の最初の <img src="..."> を使用
  2. 無ければ Wikimedia Commons でアーティスト名検索（CC-BY系ライセンスのみ）
  3. 無ければ WP Media API でアーティスト名検索し最新1枚を使用
  4. それも無ければ空を返す（呼び出し側で make_thumbnail.py の生成にフォールバック）

返す画像は 1200x630 にセンタークロップし WebP/JPG で保存。
描画時のキャプション合成は呼び出し側（make_thumbnail.py --bg-image）が行う。

使い方（CLI）:
  python3 lib/resolve_featured_image.py \
    --title "記事タイトル" \
    --body-file reports/final_post.md \
    --out /tmp/featured.webp
  stdout: "body_img:/tmp/featured.webp" or "wp_media:/tmp/featured.webp" or "none:"

使い方（モジュール）:
  from resolve_featured_image import resolve
  path, source = resolve(body_text, title)
"""
from __future__ import annotations
import argparse
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"
WP_DOMAIN = "https://www.kpopjournal.tokyo"
WP_AUTH = str(Path.home() / ".wp_auth")

# make_thumbnail.py の ARTISTS_TIER1 と同じ主要リスト（読み込み依存を避けるためローカル保持）
ARTISTS = [
    "BTS", "BLACKPINK", "BIGBANG", "TWICE", "NEWJEANS", "NewJeans",
    "STRAYKIDS", "Stray Kids", "STRAY KIDS",
    "ITZY", "aespa", "AESPA", "IVE", "SEVENTEEN", "ENHYPEN",
    "LE SSERAFIM", "LESSERAFIM", "LeSserafim",
    "TXT", "ATEEZ", "NCT", "NMIXX", "RIIZE", "ZEROBASEONE", "ZB1",
    "EXO", "SHINee", "SHINEE", "GOT7",
    "ILLIT", "BABYMONSTER", "KISS OF LIFE",
    "RED VELVET", "MAMAMOO", "(G)I-DLE",
    "T.O.P", "G-DRAGON", "IU",
    "ジミン", "ジョングク", "テヒョン", "ソクジン", "ナムジュン", "ホソク", "ユンギ",
    "ジス", "ジェニー", "ロゼ", "リサ",
    "カリナ", "ジゼル", "ウィンター", "ニンニン",
    "ウォニョン", "ユジン", "レイ", "リズ", "ガウル", "イソ",
    "チェウォン", "カズハ", "サクラ", "ユンジン",
    "ミンジ", "ハニ", "ダニエル", "ヘイン", "ヘリン",
]

IMG_TAG_RE = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)
MD_IMG_RE = re.compile(r'!\[[^\]]*\]\(([^)\s]+)')

# 自サイトのパイプライン生成サムネのファイル名パターン。これを背景に使うと二重描画になるので除外する。
# Wikimediaの /thumb/ パスは画像バリアント経路なので除外対象外（別パターン）
# マッチ条件（自サイト内の既知の生成物パターン）:
#   - kpop-YYYYMMDD_HHMMSS.webp/jpg/png
#   - /wp-content/ 配下の thumbnail*.webp/jpg/png
#   - /wp-content/ 配下の thumb_<数字>....webp/jpg/png
#   - /wp-content/ 配下の thumb-r\d+-<数字>-*.webp/jpg/png (kpop_chart_pipeline 生成)
#   - /wp-content/ 配下の *_profile*.webp/jpg/png (プロフィール系生成サムネ)
GENERATED_THUMB_RE = re.compile(
    r'(kpop-\d{8}_\d{6}\.(?:webp|jpg|png)'
    r'|/wp-content/.*?/thumbnail[^/]*\.(?:webp|jpg|png)'
    r'|/wp-content/.*?/thumb[_.-]\d+[^/]*\.(?:webp|jpg|png)'
    r'|/wp-content/.*?/thumb-r\d+-\d+[^/]*\.(?:webp|jpg|png)'
    r'|/wp-content/.*?/[^/]*_profile[^/]*\.(?:webp|jpg|png))',
    re.IGNORECASE
)


def _log(msg: str) -> None:
    # stderrに進捗。stdoutは結果のみ（パイプライン受け取り用）
    print(f"[resolve_featured_image] {msg}", file=sys.stderr)


def _extract_first_body_img(body: str) -> str | None:
    """本文の最初の <img> or ![]() を返す。ただしパイプライン生成サムネは除外。"""
    if not body:
        return None
    # すべての候補を列挙して、生成サムネでない最初のものを返す
    candidates = []
    for m in IMG_TAG_RE.finditer(body):
        candidates.append(m.group(1).strip())
    for m in MD_IMG_RE.finditer(body):
        candidates.append(m.group(1).strip())
    for url in candidates:
        if GENERATED_THUMB_RE.search(url):
            _log(f"skip generated thumb in body: {url[:80]}")
            continue
        return url
    return None


def _extract_artist_from_title(title: str) -> str | None:
    """タイトルから主要アーティスト名を抽出（長い順にマッチ）"""
    if not title:
        return None
    for a in sorted(ARTISTS, key=len, reverse=True):
        if a.lower() in title.lower():
            return a
    return None


def _download_image(url: str, dest: str, timeout: int = 20) -> bool:
    """remote URL を dest にダウンロード。成功すれば True"""
    try:
        # 自サイトのURLなら認証付きで取得
        if url.startswith(WP_DOMAIN):
            subprocess.check_call(
                ["curl", "-sSL", "-K", WP_AUTH, "-o", dest, url],
                timeout=timeout,
            )
        else:
            req = urllib.request.Request(
                url, headers={"User-Agent": "KpopJournal/1.0"}
            )
            with urllib.request.urlopen(req, timeout=timeout) as r:
                with open(dest, "wb") as f:
                    f.write(r.read())
        if os.path.getsize(dest) < 1024:
            # 1KB 未満はエラーレスポンスの可能性
            return False
        return True
    except Exception as e:
        _log(f"download fail {url}: {e}")
        return False


def _wp_media_search(query: str, limit: int = 10) -> list[dict]:
    """WP Media API で画像検索。title/alt/slug/filename に query を含むものが返る"""
    path = (f"/wp-json/wp/v2/media"
            f"?search={urllib.parse.quote(query)}"
            f"&media_type=image&per_page={limit}"
            f"&orderby=date&order=desc")
    try:
        out = subprocess.check_output(
            ["curl", "-s", f"{WP_DOMAIN}{path}", "-K", WP_AUTH],
            timeout=30
        ).decode()
        data = json.loads(out)
        return data if isinstance(data, list) else []
    except Exception as e:
        _log(f"wp_media_search fail: {e}")
        return []


def _is_generic_thumbnail(item: dict) -> bool:
    """自動生成されたテンプレサムネを除外（artist-matchの意味がないため）"""
    title = (item.get("title", {}).get("rendered") or "").lower()
    slug = (item.get("slug") or "").lower()
    src = (item.get("source_url") or "").lower()
    # パイプライン生成サムネ全般をGENERATED_THUMB_REで弾く
    if GENERATED_THUMB_RE.search(src):
        return True
    if GENERATED_THUMB_RE.search(slug):
        return True
    # title/slug に "thumbnail" のみ含まれる
    if slug in ("thumbnail", "thumb") or title in ("thumbnail", "thumb"):
        return True
    return False


def _resize_to_thumbnail(src: str, dst: str, W: int = 1200, H: int = 630) -> bool:
    """画像を 1200x630 にセンタークロップして WebP/JPG で保存"""
    try:
        from PIL import Image
        im = Image.open(src).convert("RGB")
        iw, ih = im.size
        if iw < 300 or ih < 200:
            _log(f"image too small {iw}x{ih}")
            return False
        scale = max(W / iw, H / ih)
        new_w, new_h = int(iw * scale), int(ih * scale)
        im = im.resize((new_w, new_h), Image.LANCZOS)
        left = (new_w - W) // 2
        top = (new_h - H) // 2
        im = im.crop((left, top, left + W, top + H))
        im.save(dst, "WEBP", quality=85)
        im.save(dst.replace(".webp", ".jpg"), "JPEG", quality=92)
        return True
    except Exception as e:
        _log(f"resize fail: {e}")
        return False


def _wikimedia_fetch(artist: str) -> str | None:
    """Wikimedia Commons からアーティスト画像を取得し、ローカルキャッシュパスを返す"""
    try:
        import sys as _sys
        _lib = str(BASE / "lib")
        if _lib not in _sys.path:
            _sys.path.insert(0, _lib)
        from wikimedia import fetch_safe_image
        cache_dir = str(BASE / "assets" / "artist_cache")
        return fetch_safe_image(artist, cache_dir)
    except Exception as e:
        _log(f"wikimedia fetch fail for '{artist}': {e}")
        return None


def resolve(body: str, title: str, out_path: str = "",
            artist_hint: str | None = None) -> tuple[str, str]:
    """返り値: (local_image_path, source)
       source ∈ {'body_img', 'wikimedia', 'wp_media', 'none'}
    """
    work_dir = LOGS / "featured_image_resolver"
    work_dir.mkdir(parents=True, exist_ok=True)

    if not out_path:
        out_path = str(work_dir / "resolved.webp")
    # WebP出力を前提。万が一パスに .webp が無ければ付与
    if not out_path.endswith(".webp"):
        out_path = out_path + ".webp"

    tmp_dir = work_dir / "tmp"
    tmp_dir.mkdir(exist_ok=True)

    # --- 1. 記事本文の最初の <img> ---
    body_url = _extract_first_body_img(body)
    if body_url:
        # プロトコル補完（//example.com → https://example.com）
        if body_url.startswith("//"):
            body_url = "https:" + body_url
        elif body_url.startswith("/"):
            body_url = WP_DOMAIN + body_url
        _log(f"body_img found: {body_url[:80]}")
        tmp = str(tmp_dir / "body_img.bin")
        if _download_image(body_url, tmp) and _resize_to_thumbnail(tmp, out_path):
            _log(f"body_img → {out_path}")
            return out_path, "body_img"
        _log("body_img download/resize fail, falling back")

    artist = artist_hint or _extract_artist_from_title(title)

    # --- 2. Wikimedia Commons アーティスト検索（CC-BY系ライセンスのみ） ---
    if artist:
        _log(f"searching Wikimedia Commons for artist='{artist}'")
        cached = _wikimedia_fetch(artist)
        if cached and os.path.exists(cached):
            if _resize_to_thumbnail(cached, out_path):
                _log(f"wikimedia → {out_path}")
                return out_path, "wikimedia"
            _log("wikimedia: resize fail")
        else:
            _log("wikimedia: no safe image")

    # --- 3. WP Media アーティスト検索（フォールバック） ---
    if artist:
        _log(f"searching WP Media for artist='{artist}'")
        items = _wp_media_search(artist, limit=15)
        items = [it for it in items if not _is_generic_thumbnail(it)]
        _log(f"wp_media candidates: {len(items)}")
        for item in items[:5]:  # 上位5件まで試行
            src = item.get("source_url") or item.get("guid", {}).get("rendered", "")
            if not src:
                continue
            tmp = str(tmp_dir / "wp_media.bin")
            if _download_image(src, tmp) and _resize_to_thumbnail(tmp, out_path):
                _log(f"wp_media id={item.get('id')} → {out_path}")
                return out_path, "wp_media"
        _log("wp_media: no usable image")

    # --- 4. 該当なし（呼び出し側でフォールバック） ---
    return "", "none"


def _read_body_file(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", required=True)
    ap.add_argument("--body-file", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--artist-hint", default="")
    args = ap.parse_args()

    body = _read_body_file(args.body_file) if args.body_file else ""
    path, source = resolve(body, args.title, out_path=args.out,
                           artist_hint=args.artist_hint or None)

    # 実行ログを JSONL で追記（監視用）
    log_file = LOGS / "featured_image_resolver.jsonl"
    try:
        from datetime import datetime, timezone, timedelta
        JST = timezone(timedelta(hours=9))
        with log_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": datetime.now(JST).isoformat(),
                "title": args.title[:100],
                "source": source,
                "out_path": path,
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass

    # stdout: "source:path" (空ならフォールバック)
    print(f"{source}:{path}")


if __name__ == "__main__":
    main()
