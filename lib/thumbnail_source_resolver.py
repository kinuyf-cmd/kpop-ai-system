#!/usr/bin/env python3
"""
Thumbnail Source Resolver v2.0 — Multi-source image acquisition for K-POP Journal thumbnails.

v2 priority order (concrete articles):
  1. YouTube MV thumbnail (for concrete articles with artists)
  2. Wikipedia/Wikimedia Commons (CC BY-SA, cached locally)
  3. Unsplash/Pexels stock photos (commercial license)
  4. Fallback real photo (JUDGE_Q1=B): same artist alt image from cache
  5. AI image generation (abstract topics only, or when all real photos fail)

v2 priority order (abstract articles):
  1. Unsplash/Pexels real stock photos
  2. AI image generation (Korean documentary style prompt)

Each source returns metadata for copyright tracking (data/thumbnail_sources.jsonl).
"""

import glob as globmod
import json
import os
import random
import re
import sys
import tempfile
import hashlib
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CACHE_DIR = BASE_DIR / "assets" / "artist_cache"
CACHE_INDEX = CACHE_DIR / "index.json"
OFFICIAL_ACCOUNTS = BASE_DIR / "config" / "official_accounts.json"
SOURCES_LOG = BASE_DIR / "data" / "thumbnail_sources.jsonl"
BLOCKED_VIDEO_IDS_FILE = BASE_DIR / "config" / "blocked_video_ids.json"
MEMBER_TO_GROUP_FILE = BASE_DIR / "config" / "member_to_group.json"
USED_IMAGES_FILE = BASE_DIR / "data" / "thumbnail_used_images.json"

# ── 使用済み画像追跡（同日中の重複防止）──

def _load_used_images() -> dict:
    """使用済み画像パスを日付キーで管理 {"2026-05-02": ["/path/to/img1.jpg", ...]}"""
    if not USED_IMAGES_FILE.exists():
        return {}
    try:
        with open(USED_IMAGES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_used_images(data: dict):
    """使用済み画像を保存（3日分のみ保持）"""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    # 3日より古いエントリを削除
    keys_to_remove = [k for k in data if k < today[:8]]  # rough cleanup
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%d")
    keys_to_remove = [k for k in data if k < cutoff]
    for k in keys_to_remove:
        del data[k]
    USED_IMAGES_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(USED_IMAGES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def _is_image_used_today(image_path: str) -> bool:
    """画像が今日既に使われたかチェック"""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    used = _load_used_images()
    return image_path in used.get(today, [])


def _mark_image_used(image_path: str):
    """画像を使用済みとして記録"""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    used = _load_used_images()
    if today not in used:
        used[today] = []
    if image_path not in used[today]:
        used[today].append(image_path)
    _save_used_images(used)


def _load_member_to_group() -> dict:
    """メンバー名→グループ名マッピングをロード（ソロ記事のグループ画像フォールバック用）"""
    if not MEMBER_TO_GROUP_FILE.exists():
        return {}
    try:
        with open(MEMBER_TO_GROUP_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _load_blocked_video_ids() -> set:
    """NG判定された動画IDをロード"""
    if not BLOCKED_VIDEO_IDS_FILE.exists():
        return set()
    try:
        with open(BLOCKED_VIDEO_IDS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return set(data.get("blocked", []))
    except Exception:
        return set()


def _slug(name: str) -> str:
    """Normalize artist name to filesystem-safe slug."""
    return re.sub(r"[^a-zA-Z0-9_]+", "_", name.lower()).strip("_")[:40]


def _is_shorts_thumbnail(image_path: str) -> bool:
    """YouTube Shortsの縦長サムネ検出

    Shortsは縦長動画を16:9に埋める際、中央に動画+左右にブラー拡張で埋める。
    Logo/単色背景画像との識別が重要:
      - Shorts: 左右stdが低い (ブラー) + 左右colorrangeあり (色変化あり、ただし弱い)
      - Logo:  左右stdが低い + 左右colorrangeほぼゼロ (完全単色)
      - 普通の写真: 左右stdが中央と同等
    """
    try:
        from PIL import Image
        import numpy as np
        img = Image.open(image_path).convert('RGB')
        if img.width < 600:
            return False
        arr = np.array(img.resize((600, int(600 * img.height / img.width))))
        w = arr.shape[1]
        left = arr[:, :w//4].astype(float)
        center = arr[:, w//4:w*3//4].astype(float)
        right = arr[:, w*3//4:].astype(float)
        cs = float(center.std())
        ss = float((left.std() + right.std()) / 2)
        if cs <= 0:
            return False
        ratio = ss / cs
        # 中央が高std、左右が中央の20-50%程度ならShortsの可能性
        if ratio >= 0.55 or ratio < 0.10:
            return False  # legit写真 or 単色logo
        # Side color rangeで Shorts vs その他 を識別:
        # - 真Shorts: 30-150 (ブラー拡張で限定的color range)
        # - Logo: <30 (完全単色)
        # - text design/legit写真: 255 (full color range)
        side = np.concatenate([left, right], axis=1)
        side_range = float(side.max(axis=(0,1)).mean() - side.min(axis=(0,1)).mean())
        if side_range < 30:
            return False  # 単色logo
        if side_range > 150:
            return False  # text design / legit photo (KCON/2PM等のFP対策)
        # 左右の輝度差が大きい → 異なる被写体 → 普通の写真
        side_brightness_diff = abs(float(left.mean()) - float(right.mean()))
        if side_brightness_diff > 30:
            return False  # 左右非対称な普通の写真
        return True
    except Exception:
        return False


def _download(url: str, dest: str, timeout: int = 15) -> bool:
    """Download a URL to a local file. Returns True on success.

    2026-05-10: Shorts/縦長コンテンツ検出を追加 (uePW57oH/Y8mML3Zp事案)
    左右ブラーパディング付きの縦長サムネはダウンロード後に判定して破棄。
    """
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "KpopJournalBot/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            if len(data) < 5000:
                return False
            with open(dest, "wb") as f:
                f.write(data)
            # Shorts pattern判定: 縦長コンテンツの左右ブラー検出
            if _is_shorts_thumbnail(dest):
                sys.stderr.write(f"[resolver] REJECT Shorts pattern: {dest}\n")
                try:
                    os.remove(dest)
                except Exception:
                    pass
                return False
            return True
    except Exception as e:
        sys.stderr.write(f"[resolver] download failed {url}: {e}\n")
        return False


# ── Source 1: Wikimedia Commons ──

def resolve_wikimedia(artist_name: str) -> dict | None:
    """Check local cache first, then fetch from Wikimedia Commons API."""
    if not artist_name:
        return None
    slug = _slug(artist_name)

    # Check local cache
    if CACHE_INDEX.exists():
        try:
            idx = json.loads(CACHE_INDEX.read_text(encoding="utf-8"))
            entry = idx.get(slug)
            if entry and entry.get("files"):
                img_path = CACHE_DIR / entry["files"][0]
                if img_path.exists():
                    source_info = entry.get("sources", [{}])[0] if entry.get("sources") else {}
                    return {
                        "image_path": str(img_path),
                        "source": "wikimedia",
                        "source_url": source_info.get("url", ""),
                        "license": source_info.get("license", "CC BY-SA 4.0"),
                        "attribution": f"Wikimedia Commons: {source_info.get('wikimedia_title', artist_name)}",
                    }
        except Exception:
            pass

    # Fetch from Wikimedia API
    try:
        _lib = str(BASE_DIR / "lib")
        if _lib not in sys.path:
            sys.path.insert(0, _lib)
        from wikimedia import fetch_safe_image
        img_path = fetch_safe_image(artist_name, str(CACHE_DIR))
        if img_path and os.path.exists(img_path):
            return {
                "image_path": img_path,
                "source": "wikimedia",
                "source_url": "",
                "license": "CC BY-SA 4.0",
                "attribution": f"Wikimedia Commons: {artist_name}",
            }
    except Exception as e:
        sys.stderr.write(f"[resolver] wikimedia fetch failed for {artist_name}: {e}\n")

    return None


# ── Source 2: YouTube official MV thumbnail ──

def _load_official_accounts() -> dict:
    """Load official YouTube channel/video IDs."""
    if not OFFICIAL_ACCOUNTS.exists():
        return {}
    try:
        return json.loads(OFFICIAL_ACCOUNTS.read_text(encoding="utf-8"))
    except Exception:
        return {}


_YT_QUOTA_EXHAUSTED_UNTIL = None  # quota超過時に日付を記録しAPIスキップ


def _fetch_youtube_videos(channel_id: str, order: str = "date", max_results: int = 3) -> list:
    """YouTube Data API v3 で公式チャネルから動画リストを取得

    2026-05-10 (19311/19452事案): order='date'(最新)はShorts/Vlog/コラボを優先するため
    MV以外の無関係画像が選ばれる。下記フィルタで非MVを除外:
    - title に Shorts/ep.([0-9]+)/vlog/behind/reaction/fancam/interview/live cam等を含む動画を排除
    """
    global _YT_QUOTA_EXHAUSTED_UNTIL
    yt_key = os.environ.get("YOUTUBE_API_KEY", "")
    if not yt_key or not channel_id:
        return []

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if _YT_QUOTA_EXHAUSTED_UNTIL == today:
        return []

    # 非MVキーワード — タイトルにこれらを含む動画はサムネ候補から除外
    NON_MV_PATTERNS = [
        '#shorts', 'shorts', 'short ver', 'short ver.',
        'ep.', 'episode ', 'vlog', 'vlogs',
        'behind', 'making', 'bts cam', 'cam ver',
        'reaction', 'react ', 'reacting',
        'fancam', 'fan cam', 'live clip', 'live cam',
        'interview', 'q&a', 'practice', 'rehearsal',
        'unboxing', 'cover ',
        # 2026-05-10: variety series追加 (3992 RUN BTS事案)
        'run bts', 'run! bts', 'go!', 'go se', 'gose',
        'workdol', 'babymonster house', 'le play',
        'itzy?itzy!', 'itzy? itzy!', 'sf9 official',
        'aespa world', 'inkigayo', 'show champion',
        'happening', 'realityshow', 'reality show',
        '하루의', '오늘의', 'eps ',  # 韓国語の番組タイトル
    ]

    try:
        import urllib.parse
        # max_resultsは8に増やしてフィルタ後に十分な選択肢を確保
        api_max = max(8, max_results * 3)
        params = urllib.parse.urlencode({
            "key": yt_key, "channelId": channel_id, "type": "video",
            "order": order, "maxResults": api_max, "part": "snippet",
        })
        url = f"https://www.googleapis.com/youtube/v3/search?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "KpopJournalBot/1.0"})
        data = json.loads(urllib.request.urlopen(req, timeout=15).read())
        all_videos = [
            {"video_id": item["id"]["videoId"], "title": item["snippet"]["title"]}
            for item in data.get("items", [])
            if item.get("id", {}).get("videoId")
        ]
        # フィルタ: 非MVを除外
        filtered = []
        for v in all_videos:
            title_lower = v.get("title", "").lower()
            if any(pat in title_lower for pat in NON_MV_PATTERNS):
                sys.stderr.write(f"[resolver] SKIP non-MV video: '{v['title'][:50]}'\n")
                continue
            filtered.append(v)
        return filtered[:max_results]
    except urllib.error.HTTPError as e:
        if e.code == 403:
            _YT_QUOTA_EXHAUSTED_UNTIL = today
            sys.stderr.write(f"[resolver] YouTube API quota超過 → 本日中はAPIスキップ、キャッシュ使用\n")
        else:
            sys.stderr.write(f"[resolver] YouTube API error: {e.code} {e.reason}\n")
        return []
    except Exception as e:
        sys.stderr.write(f"[resolver] YouTube API error: {e}\n")
        return []


def _resolve_channel_id(artist_name: str, accounts: dict) -> str:
    """channel_id を解決 (設定値のみ — API検索フォールバック廃止)

    再発防止: YouTube API検索は関係ないチャンネルを返すリスクがあるため、
    official_accounts.json に登録済みのchannel_idのみを使用する。
    未登録アーティストはYouTubeソースをスキップし、次の優先度(Wikimedia等)へ。
    """
    artist_key = _slug(artist_name)
    account = accounts.get(artist_key, {})
    ch_id = account.get("channel_id", "") or account.get("youtube_channel_id", "")
    if ch_id:
        return ch_id
    # 未登録アーティスト: YouTube検索に頼らず空文字を返す（誤チャンネル防止）
    sys.stderr.write(
        f"[resolver] WARN: '{artist_name}' (key='{artist_key}') は "
        f"official_accounts.json 未登録のためYouTubeソースをスキップ\n"
    )
    return ""


def _resolve_channel_id_DEPRECATED(artist_name: str, accounts: dict) -> str:
    """[廃止] API検索フォールバック — 誤チャンネル取得の根本原因"""
    artist_key = _slug(artist_name)
    account = accounts.get(artist_key, {})
    ch_id = account.get("channel_id", "")
    if ch_id:
        return ch_id
    yt_key = os.environ.get("YOUTUBE_API_KEY", "")
    if not yt_key:
        return ""
    ch_name = account.get("channel_name", artist_name)
    try:
        import urllib.parse
        params = urllib.parse.urlencode({
            "key": yt_key, "q": f"{ch_name} official", "type": "channel", "maxResults": 1, "part": "snippet",
        })
        url = f"https://www.googleapis.com/youtube/v3/search?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "KpopJournalBot/1.0"})
        data = json.loads(urllib.request.urlopen(req, timeout=15).read())
        items = data.get("items", [])
        if items:
            ch_id = items[0]["id"]["channelId"]
            account["channel_id"] = ch_id
            accounts[artist_key] = account
            try:
                json.dump(accounts, open(str(OFFICIAL_ACCOUNTS), "w"), ensure_ascii=False, indent=2)
            except:
                pass
            return ch_id
    except:
        pass
    return ""


def resolve_youtube(artist_name: str, prefer: str = "popular",
                    prefer_keywords: list | None = None) -> dict | None:
    """Get YouTube MV thumbnail — 最新MV or 高再生MVから自動取得

    prefer: "popular" = 高再生数優先(default), "latest" = 最新動画, "static" = 固定リストのみ
    prefer_keywords: 動画タイトルに含まれていたら優先採用するキーワード (例: 曲名)
      2026-05-12 追加: 記事タイトルの曲名 (例: WDA) と動画タイトルの曲名が一致する
      動画を最優先採用。aespa の WDA 記事に THIRSTY MV サムネが付いた事故への
      root cause 対策。
    2026-05-10: defaultを latest → popular に変更。最新動画はShorts/Vlog/コラボが
    K-pop公式チャンネルで日次投稿されるため Shorts汚染が多発した。人気順なら
    アイコニックなMVサムネが安定して取得できる。
    """
    if not artist_name:
        return None

    accounts = _load_official_accounts()
    artist_key = _slug(artist_name)
    account = accounts.get(artist_key, {})

    # Step 1: YouTube Data API で動的取得 (latest or popular)
    if prefer != "static":
        channel_id = _resolve_channel_id(artist_name, accounts)
        if channel_id:
            order = "date" if prefer == "latest" else "viewCount"
            blocked_ids = _load_blocked_video_ids()
            # prefer_keywords 指定時は候補を多めに取って曲名 match を上位 sort
            _fetch_n = 10 if prefer_keywords else 3
            videos = _fetch_youtube_videos(channel_id, order=order, max_results=_fetch_n)
            if prefer_keywords and videos:
                def _kw_score(v):
                    t = (v.get("title", "") or "").lower()
                    return sum(1 for kw in prefer_keywords if kw and kw.lower() in t)
                videos = sorted(videos, key=lambda v: -_kw_score(v))
                if videos and _kw_score(videos[0]) > 0:
                    sys.stderr.write(
                        f"[resolver] 曲名match優先: '{videos[0].get('title','')[:50]}' "
                        f"(keywords={prefer_keywords[:3]})\n"
                    )
            videos = videos[:3]
            for v in videos:
                vid = v["video_id"]
                if vid in blocked_ids:
                    sys.stderr.write(f"[resolver] BLOCKED video_id={vid} (blocked_video_ids.json)\n")
                    continue
                # maxresdefault → hqdefault fallback
                for quality in ["maxresdefault", "hqdefault"]:
                    url = f"https://img.youtube.com/vi/{vid}/{quality}.jpg"
                    dest = str(CACHE_DIR / f"yt_{artist_key}_{vid[:8]}_{quality[:3]}.jpg")
                    if os.path.exists(dest) and os.path.getsize(dest) > 5000:
                        # 2026-05-10完璧化: cache読込時にもShorts判定 (古い汚染cache遮断)
                        if _is_shorts_thumbnail(dest):
                            sys.stderr.write(f"[resolver] PURGE Shorts cache: {dest}\n")
                            try: os.remove(dest)
                            except: pass
                            continue
                        if _is_image_used_today(dest):
                            sys.stderr.write(f"[resolver] SKIP used today: {dest}\n")
                            continue
                        return {
                            "image_path": dest,
                            "source": "youtube_official",
                            "source_url": f"https://www.youtube.com/watch?v={vid}",
                            "license": "YouTube embed (fair use for editorial thumbnail)",
                            "attribution": f"YouTube: {account.get('channel_name', artist_name)}",
                            "video_title": v.get("title", ""),
                            "fetch_mode": prefer,
                        }
                    if _download(url, dest):
                        if _is_image_used_today(dest):
                            sys.stderr.write(f"[resolver] SKIP used today: {dest}\n")
                            continue
                        return {
                            "image_path": dest,
                            "source": "youtube_official",
                            "source_url": f"https://www.youtube.com/watch?v={vid}",
                            "license": "YouTube embed (fair use for editorial thumbnail)",
                            "attribution": f"YouTube: {account.get('channel_name', artist_name)}",
                            "video_title": v.get("title", ""),
                            "fetch_mode": prefer,
                        }

    # Step 2: Fallback to static video_ids list
    video_ids = account.get("youtube_video_ids", [])
    for vid in video_ids[:3]:
        url = f"https://img.youtube.com/vi/{vid}/maxresdefault.jpg"
        dest = str(CACHE_DIR / f"yt_{artist_key}_{vid[:8]}.jpg")
        if os.path.exists(dest):
            # 2026-05-10完璧化: 静的cache読込時もShorts判定で汚染遮断
            if _is_shorts_thumbnail(dest):
                sys.stderr.write(f"[resolver] PURGE Shorts static cache: {dest}\n")
                try: os.remove(dest)
                except: pass
            else:
                return {
                    "image_path": dest,
                    "source": "youtube_official",
                    "source_url": f"https://www.youtube.com/watch?v={vid}",
                    "license": "YouTube embed (fair use for editorial thumbnail)",
                    "attribution": f"YouTube: {account.get('channel_name', artist_name)}",
                    "fetch_mode": "static",
                }
        if _download(url, dest):
            return {
                "image_path": dest,
                "source": "youtube_official",
                "source_url": f"https://www.youtube.com/watch?v={vid}",
                "license": "YouTube embed (fair use for editorial thumbnail)",
                "attribution": f"YouTube: {account.get('channel_name', artist_name)}",
                "fetch_mode": "static",
            }

    return None


# ── Source 3: Unsplash stock photos ──

def resolve_unsplash(query: str) -> dict | None:
    """Get a stock photo from Unsplash API (requires UNSPLASH_ACCESS_KEY)."""
    api_key = os.environ.get("UNSPLASH_ACCESS_KEY", "")
    if not api_key:
        return None

    search_terms = f"kpop {query}" if query else "kpop concert"
    encoded = urllib.request.quote(search_terms)
    url = f"https://api.unsplash.com/search/photos?query={encoded}&per_page=1&orientation=landscape"

    try:
        req = urllib.request.Request(url, headers={
            "Authorization": f"Client-ID {api_key}",
            "Accept-Version": "v1",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            results = data.get("results", [])
            if not results:
                return None

            photo = results[0]
            img_url = photo["urls"].get("regular", photo["urls"]["small"])
            photo_id = photo["id"]
            dest = str(CACHE_DIR / f"unsplash_{photo_id[:12]}.jpg")

            if os.path.exists(dest) or _download(img_url, dest):
                return {
                    "image_path": dest,
                    "source": "unsplash",
                    "source_url": photo["links"]["html"],
                    "license": "Unsplash License",
                    "attribution": f"Photo by {photo['user']['name']} on Unsplash",
                }
    except Exception as e:
        sys.stderr.write(f"[resolver] unsplash failed: {e}\n")

    return None


# ── Source 4: Fallback real photo from cache (JUDGE_Q1=B) ──

def resolve_fallback_photo(artist_name: str) -> dict | None:
    """
    Look in assets/artist_cache/ for ANY file matching the artist slug.
    Returns an alternate image if the primary was already used.
    Implements JUDGE_Q1=B: same artist different image, or same group different member.
    """
    if not artist_name:
        return None

    slug = _slug(artist_name)
    cache_dir = str(CACHE_DIR)

    # Find all cached files matching this artist slug
    patterns = [
        os.path.join(cache_dir, f"*{slug}*.*"),
        os.path.join(cache_dir, f"*{slug.replace('_', '')}*.*"),
    ]
    candidates = []
    for pat in patterns:
        for f in globmod.glob(pat):
            if os.path.isfile(f) and os.path.getsize(f) > 5000:
                ext = os.path.splitext(f)[1].lower()
                if ext in (".jpg", ".jpeg", ".png", ".webp"):
                    candidates.append(f)

    # Also check the cache index for group members / related artists
    if CACHE_INDEX.exists():
        try:
            idx = json.loads(CACHE_INDEX.read_text(encoding="utf-8"))
            entry = idx.get(slug, {})
            files = entry.get("files", [])
            for fname in files:
                fpath = str(CACHE_DIR / fname)
                if os.path.exists(fpath) and fpath not in candidates:
                    candidates.append(fpath)
        except Exception:
            pass

    if not candidates:
        return None

    # 使用済みでない画像を優先選択（重複回避）
    random.shuffle(candidates)
    unused = [c for c in candidates if not _is_image_used_today(c)]
    if unused:
        selected = unused[0]
    elif len(set(candidates)) <= 1:
        # Only 1 unique image and already used today → force fallback to next source
        sys.stderr.write(f"[resolver] cache exhausted for '{artist_name}' (1 image, already used) → skip to next source\n")
        return None
    else:
        selected = candidates[0]

    return {
        "image_path": selected,
        "source": "fallback_cache",
        "source_url": "",
        "license": "Cached (original license applies)",
        "attribution": f"Cached image for {artist_name}",
    }


# ── Source 5: AI image generation (prompt only) ──

def resolve_ai_prompt(topic_context: str = "", genre: str = "") -> dict:
    """
    Generate an AI image prompt (Korean documentary style).
    Does NOT call an API — saves the prompt for external generation.
    Returns a dict with source='ai_prompt' and the prompt text.
    """
    prompt_config_path = BASE_DIR / "config" / "ai_image_prompt_template.json"
    try:
        with open(prompt_config_path, "r", encoding="utf-8") as f:
            tpl = json.load(f)
    except Exception:
        tpl = {
            "positive_template": "Korean documentary photo, Seoul, {topic_context}",
            "location_pool": ["Seoul street"],
            "gender_patterns": {"neutral": "natural appearance"},
            "negative_prompt": "",
        }

    location = random.choice(tpl.get("location_pool", ["Seoul street"]))
    gender_desc = tpl.get("gender_patterns", {}).get("neutral", "natural appearance")
    positive = tpl["positive_template"].format(
        gender_desc=gender_desc,
        location=location,
        topic_context=topic_context or genre or "K-POP culture",
    )
    negative = tpl.get("negative_prompt", "")

    return {
        "image_path": "",
        "source": "ai_prompt",
        "source_url": "",
        "license": "AI-generated (to be created)",
        "attribution": "AI-generated documentary style",
        "ai_positive_prompt": positive,
        "ai_negative_prompt": negative,
    }


# ── Main resolver ──

def resolve_source_og_image(source_url: str, post_id: str = "") -> dict | None:
    """ソース記事から og:image を抽出し、portrait/極小をrejectして source_og_image dictを返す。

    2026-05-11 規定: artist photo より先に毎回試行 (memory: feedback_artist_photo_absolute_rule)。
    """
    if not source_url or not source_url.startswith('http'):
        return None
    try:
        import urllib.request
        req = urllib.request.Request(source_url, headers={'User-Agent': 'KPJ-OG/1.0'})
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read()
        html = raw.decode('utf-8', errors='ignore') if isinstance(raw, (bytes, bytearray)) else str(raw)
    except Exception:
        return None
    m = re.search(r'<meta\s+(?:property|name)=["\']og:image(?::secure_url)?["\']\s+content=["\']([^"\']+)["\']', html)
    if not m:
        m = re.search(r'<meta\s+content=["\']([^"\']+)["\']\s+(?:property|name)=["\']og:image["\']', html)
    if not m:
        return None
    og_url = m.group(1)
    if not og_url.startswith('http'):
        return None
    dest = tempfile.NamedTemporaryFile(suffix='.jpg', delete=False).name
    if not _download(og_url, dest):
        try: os.unlink(dest)
        except Exception: pass
        return None
    if _check_portrait(dest):
        try: os.unlink(dest)
        except Exception: pass
        return None
    # 2026-05-14: 22606/22663 事故への根治 (匿名シルエット / placeholder reject)
    if _check_low_quality_og(dest):
        try: os.unlink(dest)
        except Exception: pass
        return None
    return {
        'image_path': dest,
        'source': 'source_og_image',
        'source_url': og_url,
        'license': 'source_attribution',
        'attribution': source_url,
    }


def resolve(artist_name: str, genre: str = "", post_id: str = "",
            article_type: str = "concrete", source_url: str = "",
            theme: str = "", theme_config: dict | None = None,
            article_title: str = "") -> dict:
    """
    Resolve the best available image source for a thumbnail.

    Args:
        artist_name: Primary artist/subject name
        genre: Genre key for query tuning
        post_id: Post ID for source logging
        article_type: "concrete" or "abstract" (from article_topic_classifier)
        theme: Article theme key (comeback/concert/chart/variety/award/fashion/personal/debut/general)
        theme_config: Theme-specific config dict with youtube_order, unsplash_query, dalle_prompt
        article_title: 記事タイトル (2026-05-12 追加: 曲名 (WDA/THIRSTY 等) match で
          MV サムネ選定を改善するため。aespa の WDA 記事に THIRSTY MV を出した
          事故への対策)

    Returns dict with keys: image_path, source, source_url, license, attribution
    If no source available, returns a fallback dict with source='gradient_fallback'.
    """
    tc = theme_config or {}
    yt_order = tc.get("youtube_order", "viewCount")  # 2026-05-10: date → viewCount
    unsplash_q = tc.get("unsplash_query", "")
    dalle_prompt = tc.get("dalle_prompt", "")
    dalle_negative = tc.get("dalle_negative", "")
    result = None

    # article_title から曲名キーワードを抽出 (「」内の固有名詞 + 英字大文字3-15字)
    song_keywords = []
    if article_title:
        import re as _re_kw
        # 「」または『』内の語
        song_keywords.extend(_re_kw.findall(r'[「『]([^」』]{1,15})[」』]', article_title))
        # 英字大文字 3-15字 (例: WDA, THIRSTY, BUTTER)
        for w in _re_kw.findall(r'\b[A-Z][A-Z0-9]{2,14}\b', article_title):
            # アーティスト名や一般語は除外
            if w.lower() not in (artist_name.lower(), 'BTS', 'IVE', 'TXT', 'NCT',
                                 'KPOP', 'JPOP', 'OST', 'MV', 'JST', 'KST', 'EP',
                                 'CEO', 'AKA'):
                song_keywords.append(w)

    def _tag(r):
        """結果dictにテーマ情報を付与"""
        if r:
            r["theme"] = theme
        return r

    def _resolve_artist_sources(artist: str) -> dict | None:
        """アーティスト本人画像を解決 (YouTube → Wikimedia → グループフォールバック → cache)"""
        r = resolve_youtube(artist, prefer=yt_order, prefer_keywords=song_keywords or None)
        if r:
            attr = (r.get("attribution", "") or "").lower()
            artist_lower = artist.lower()
            if artist_lower and artist_lower not in attr and _slug(artist) not in attr:
                sys.stderr.write(
                    f"[resolver] BLOCK: YouTube attribution不一致 → スキップ\n"
                )
            else:
                return r

        r = resolve_wikimedia(artist)
        if r:
            return r

        # アーティスト本人のキャッシュ画像 (solo cache を group fallback より先に試行)
        r = resolve_fallback_photo(artist)
        if r:
            return r

        # メンバー→グループフォールバック
        member_map = _load_member_to_group()
        group_name = member_map.get(artist, "")
        if group_name and group_name != artist:
            sys.stderr.write(
                f"[resolver] メンバー '{artist}' → グループ '{group_name}' にフォールバック\n"
            )
            r = resolve_youtube(group_name, prefer=yt_order, prefer_keywords=song_keywords or None)
            if r:
                return r
            r = resolve_wikimedia(group_name)
            if r:
                return r
            r = resolve_fallback_photo(group_name)
            if r:
                return r

        return None

    if article_type == "concrete":
        # ── concrete記事: og:image最優先 → アーティスト本人写真 → fallback ──
        # 2026-05-11 規定 (memory: feedback_artist_photo_absolute_rule):
        #   og:image > artist photo > Unsplash > DALL-E
        # source_url がある全 concrete 記事で og:image 取得を試行する
        if source_url:
            result = resolve_source_og_image(source_url, post_id)
            if result:
                _log_source(post_id, _tag(result))
                return result

        if artist_name:
            sys.stderr.write(
                f"[resolver] テーマ={theme}: アーティスト写真最優先 (artist={artist_name})\n"
            )

            result = _resolve_artist_sources(artist_name)
            if result:
                _log_source(post_id, _tag(result))
                return result

            sys.stderr.write(
                f"[resolver] アーティスト '{artist_name}' の写真なし → テーマ別フォールバック\n"
            )

        # アーティスト写真が取得できなかった場合のみテーマ別画像
        # Unsplash (テーマ別クエリ)
        q = unsplash_q
        if not q:
            query_terms = {"beauty": "korean beauty skincare", "live": "kpop concert live",
                           "travel": "seoul korea", "fashion": "korean fashion"}
            q = query_terms.get(genre, f"kpop {artist_name}" if artist_name else "kpop music")
        result = resolve_unsplash(q)
        if result:
            _log_source(post_id, _tag(result))
            return result

        # 最終フォールバック: DALL-E (テーマ別プロンプト)
        # Include artist + theme for more diverse generation when cache was exhausted
        if not dalle_prompt:
            parts = [p for p in [artist_name, theme] if p]
            topic_ctx = " ".join(parts) if parts else ""
        else:
            topic_ctx = ""
        result = resolve_ai_prompt(topic_context=topic_ctx, genre=genre)
        if dalle_prompt:
            result["ai_positive_prompt"] = dalle_prompt
        if dalle_negative:
            result["ai_negative_prompt"] = dalle_negative
        _log_source(post_id, _tag(result))
        return result

    else:
        # ── abstract記事: テーマ別画像優先 ──
        # Unsplash (テーマ別クエリ) → DALL-E (テーマ別プロンプト)
        q = unsplash_q
        if not q:
            query_terms = {"beauty": "korean beauty skincare", "live": "kpop concert live",
                           "travel": "seoul korea", "fashion": "korean fashion"}
            q = query_terms.get(genre, "kpop music korean culture")
        result = resolve_unsplash(q)
        if result:
            _log_source(post_id, _tag(result))
            return result

        result = resolve_ai_prompt(topic_context=genre or "K-POP culture", genre=genre)
        if dalle_prompt:
            result["ai_positive_prompt"] = dalle_prompt
        if dalle_negative:
            result["ai_negative_prompt"] = dalle_negative
        _log_source(post_id, _tag(result))
        return result


def _check_portrait(image_path: str) -> bool:
    """画像が縦長(portrait)かチェック。縦長ならTrue (2026-05-01追加)"""
    if not image_path or not os.path.exists(image_path):
        return False
    try:
        from PIL import Image
        im = Image.open(image_path)
        if im.height > im.width * 1.3:
            sys.stderr.write(f"[resolver] REJECT portrait: {im.width}x{im.height} {image_path}\n")
            return True
    except Exception:
        pass
    return False


def _check_low_quality_og(image_path: str, min_bytes: int = 5120) -> bool:
    """og:image の品質ガード (2026-05-14 追加)。
    True を返したら reject (採用しない)。
    - file size < 5KB → low-quality placeholder (アイコン/匿名シルエット等)
    - 画像中央 80% のグレースケール分散が非常に低い → near-monochrome
      (topstarnews の「?」匿名シルエット 22606 事故への対策)
    """
    if not image_path or not os.path.exists(image_path):
        return True
    try:
        size = os.path.getsize(image_path)
        if size < min_bytes:
            sys.stderr.write(f"[resolver] REJECT og:image too small {size}B: {image_path}\n")
            return True
    except Exception:
        return True
    try:
        from PIL import Image, ImageStat
        with Image.open(image_path) as im:
            w, h = im.size
            crop = im.crop((w // 10, h // 10, w - w // 10, h - h // 10)).convert('L')
            stddev = ImageStat.Stat(crop).stddev[0]
            if stddev < 15.0:
                sys.stderr.write(
                    f"[resolver] REJECT og:image near-monochrome stddev={stddev:.1f}\n")
                return True
    except Exception:
        pass
    return False


def _validate_and_log(post_id: str, result: dict) -> dict | None:
    """結果の画像品質を検証してからログ記録。縦長ならNone返却 (2026-05-01追加)"""
    if not result:
        return None
    img_path = result.get('image_path', result.get('path', ''))
    if img_path and _check_portrait(img_path):
        return None  # 縦長→次のソースへフォールスルー
    _log_source(post_id, result)
    return result


def _log_source(post_id: str, source_info: dict):
    """Append source metadata to thumbnail_sources.jsonl and mark image as used."""
    record = {
        "post_id": post_id,
        "source": source_info.get("source", ""),
        "source_url": source_info.get("source_url", ""),
        "license": source_info.get("license", ""),
        "attribution": source_info.get("attribution", ""),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        SOURCES_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(SOURCES_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        sys.stderr.write(f"[resolver] log failed: {e}\n")

    # 使用済みとしてマーク（同日中の重複防止）
    img_path = source_info.get("image_path", "")
    if img_path:
        try:
            _mark_image_used(img_path)
        except Exception:
            pass


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Thumbnail Source Resolver v2")
    parser.add_argument("artist", nargs="?", default="", help="Artist name")
    parser.add_argument("--genre", default="", help="Genre key")
    parser.add_argument("--post-id", default="", help="Post ID for logging")
    parser.add_argument("--article-type", default="concrete",
                        choices=["concrete", "abstract"],
                        help="Article type (concrete or abstract)")
    args = parser.parse_args()

    result = resolve(args.artist, args.genre, args.post_id,
                     article_type=args.article_type)
    print(json.dumps(result, ensure_ascii=False, indent=2))
