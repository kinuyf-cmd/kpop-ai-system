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


def _slug(name: str) -> str:
    """Normalize artist name to filesystem-safe slug."""
    return re.sub(r"[^a-zA-Z0-9_]+", "_", name.lower()).strip("_")[:40]


def _download(url: str, dest: str, timeout: int = 15) -> bool:
    """Download a URL to a local file. Returns True on success."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "KpopJournalBot/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            if len(data) < 5000:  # Too small, likely an error page
                return False
            with open(dest, "wb") as f:
                f.write(data)
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


def resolve_youtube(artist_name: str) -> dict | None:
    """Get YouTube MV thumbnail (maxresdefault) for official videos."""
    if not artist_name:
        return None

    accounts = _load_official_accounts()
    artist_key = _slug(artist_name)
    account = accounts.get(artist_key, {})
    video_ids = account.get("youtube_video_ids", [])

    if not video_ids:
        return None

    for vid in video_ids[:3]:  # Try up to 3 videos
        url = f"https://img.youtube.com/vi/{vid}/maxresdefault.jpg"
        dest = str(CACHE_DIR / f"yt_{artist_key}_{vid[:8]}.jpg")
        if os.path.exists(dest):
            return {
                "image_path": dest,
                "source": "youtube_official",
                "source_url": f"https://www.youtube.com/watch?v={vid}",
                "license": "YouTube embed (fair use for editorial thumbnail)",
                "attribution": f"YouTube: {account.get('channel_name', artist_name)}",
            }
        if _download(url, dest):
            return {
                "image_path": dest,
                "source": "youtube_official",
                "source_url": f"https://www.youtube.com/watch?v={vid}",
                "license": "YouTube embed (fair use for editorial thumbnail)",
                "attribution": f"YouTube: {account.get('channel_name', artist_name)}",
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

    # Shuffle to get a different image each time
    random.shuffle(candidates)

    for img_path in candidates:
        return {
            "image_path": img_path,
            "source": "fallback_cache",
            "source_url": "",
            "license": "Cached (original license applies)",
            "attribution": f"Cached image for {artist_name}",
        }

    return None


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

def resolve(artist_name: str, genre: str = "", post_id: str = "",
            article_type: str = "concrete") -> dict:
    """
    Resolve the best available image source for a thumbnail.

    Args:
        artist_name: Primary artist/subject name
        genre: Genre key for query tuning
        post_id: Post ID for source logging
        article_type: "concrete" or "abstract" (from article_topic_classifier)

    Returns dict with keys: image_path, source, source_url, license, attribution
    If no source available, returns a fallback dict with source='gradient_fallback'.
    """
    result = None

    if article_type == "concrete":
        # v2 concrete priority: YouTube → Wikimedia → Unsplash → Fallback cache → AI prompt

        # Priority 1: YouTube official MV thumbnail
        result = resolve_youtube(artist_name)
        if result:
            _log_source(post_id, result)
            return result

        # Priority 2: Wikimedia Commons
        result = resolve_wikimedia(artist_name)
        if result:
            _log_source(post_id, result)
            return result

        # Priority 3: Unsplash/Pexels real photos
        query_terms = {"beauty": "korean beauty skincare", "live": "kpop concert live",
                       "travel": "seoul korea", "fashion": "korean fashion"}
        q = query_terms.get(genre, f"kpop {artist_name}" if artist_name else "kpop music")
        result = resolve_unsplash(q)
        if result:
            _log_source(post_id, result)
            return result

        # Priority 4: Fallback real photo (JUDGE_Q1=B)
        result = resolve_fallback_photo(artist_name)
        if result:
            _log_source(post_id, result)
            return result

        # Priority 5: AI prompt as last resort for concrete
        result = resolve_ai_prompt(topic_context=artist_name, genre=genre)
        _log_source(post_id, result)
        return result

    else:
        # v2 abstract priority: Unsplash real photos → AI prompt

        # Priority 1: Unsplash/Pexels real photos
        query_terms = {"beauty": "korean beauty skincare", "live": "kpop concert live",
                       "travel": "seoul korea", "fashion": "korean fashion"}
        q = query_terms.get(genre, "kpop music korean culture")
        result = resolve_unsplash(q)
        if result:
            _log_source(post_id, result)
            return result

        # Priority 2: AI image prompt (Korean documentary style)
        result = resolve_ai_prompt(topic_context=genre or "K-POP culture", genre=genre)
        _log_source(post_id, result)
        return result


def _log_source(post_id: str, source_info: dict):
    """Append source metadata to thumbnail_sources.jsonl."""
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
