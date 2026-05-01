#!/usr/bin/env python3
"""
trend_collector.py -- 軽量トレンドキーワード収集 (Phase 8)

RSS/X API/YouTube からトレンドシグナルを収集し data/trend_signals.jsonl に追記する。
trend_predictor.py がスコアリング・auto_directives注入を担当するため、
本スクリプトは「収集」のみに専念する。

Usage:
  python3 lib/trend_collector.py                  # 全ソース収集
  python3 lib/trend_collector.py --source rss     # RSSのみ
  python3 lib/trend_collector.py --source x       # X(Twitter)のみ
  python3 lib/trend_collector.py --dry-run        # 収集結果表示のみ（書き込みなし）

管轄: ジラーチ（予測）+ ポリゴン（データ収集）
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE = Path(__file__).resolve().parent.parent
CONFIG = BASE / "config" / "content_strategy"
DATA = BASE / "data"
LOGS = BASE / "logs"

# .envから環境変数ロード (YOUTUBE_API_KEY, X_BEARER_TOKEN等)
try:
    from dotenv import load_dotenv
    load_dotenv(BASE / ".env")
except ImportError:
    pass

TREND_SOURCES_PATH = CONFIG / "trend_sources.json"
OUTPUT_PATH = DATA / "trend_signals.jsonl"
COLLECTOR_LOG = LOGS / "trend_collector.log"

JST = timezone(timedelta(hours=9))

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_jst() -> datetime:
    return datetime.now(JST)


def _log(msg: str):
    ts = _now_jst().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    LOGS.mkdir(parents=True, exist_ok=True)
    with open(COLLECTOR_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _load_sources_config() -> dict:
    if not TREND_SOURCES_PATH.exists():
        _log(f"WARN: {TREND_SOURCES_PATH} not found, using defaults")
        return {}
    return json.loads(TREND_SOURCES_PATH.read_text(encoding="utf-8"))


def _write_signals(signals: list[dict]):
    """Append signals to data/trend_signals.jsonl."""
    DATA.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "a", encoding="utf-8") as f:
        for sig in signals:
            f.write(json.dumps(sig, ensure_ascii=False) + "\n")


def _cleanup_old_signals(max_age_days: int = 7):
    """Remove signals older than max_age_days from the JSONL file."""
    if not OUTPUT_PATH.exists():
        return
    cutoff = _now_jst() - timedelta(days=max_age_days)
    kept = []
    with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                ts_str = entry.get("timestamp", "")
                if ts_str:
                    ts = datetime.fromisoformat(ts_str)
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=JST)
                    if ts >= cutoff:
                        kept.append(line)
                else:
                    kept.append(line)
            except (json.JSONDecodeError, ValueError):
                continue
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        for line in kept:
            f.write(line + "\n")


# ---------------------------------------------------------------------------
# RSS Collector
# ---------------------------------------------------------------------------

def collect_rss(config: dict) -> list[dict]:
    """Collect trend signals from RSS feeds."""
    rss_config = config.get("sources", {}).get("rss_feeds", {})
    if not rss_config.get("enabled", False):
        _log("RSS collection disabled")
        return []

    feeds = rss_config.get("feeds", [])
    max_age_hours = rss_config.get("max_age_hours", 24)
    cutoff = _now_jst() - timedelta(hours=max_age_hours)
    signals = []

    for feed_info in feeds:
        feed_url = feed_info.get("url", "")
        feed_id = feed_info.get("id", "unknown")
        if not feed_url:
            continue
        if feed_info.get("enabled") is False:
            _log(f"  Skipping RSS: {feed_id} (disabled)")
            continue

        _log(f"  Fetching RSS: {feed_id} ({feed_url})")
        try:
            req = Request(feed_url, headers={
                "User-Agent": "KPOPJournal-TrendCollector/1.0",
            })
            with urlopen(req, timeout=15) as resp:
                xml_data = resp.read()

            root = ET.fromstring(xml_data)

            # Handle both RSS 2.0 and Atom
            items = root.findall(".//item") or root.findall(
                ".//{http://www.w3.org/2005/Atom}entry"
            )

            count = 0
            for item in items[:20]:  # Limit per feed
                title = _get_xml_text(item, "title") or ""
                link = _get_xml_text(item, "link") or ""
                pub_date = _get_xml_text(item, "pubDate") or ""

                if not title:
                    continue

                # Extract keywords from title
                keywords = _extract_kpop_keywords(title)
                if not keywords:
                    continue

                signals.append({
                    "timestamp": _now_jst().isoformat(),
                    "source": "rss",
                    "source_id": feed_id,
                    "keyword": keywords[0] if keywords else title[:50],
                    "title": title[:200],
                    "url": link,
                    "engagement_score": feed_info.get("priority", "medium") == "high" and 2.0 or 1.0,
                    "language": feed_info.get("language", "en"),
                    "raw_data": {
                        "all_keywords": keywords,
                        "pub_date": pub_date,
                    },
                })
                count += 1

            _log(f"    -> {count} signals from {feed_id}")

        except ET.ParseError as e:
            # Malformed XML fallback: regex-extract <title> and <link> from raw data
            _log(f"    WARN: XML parse failed for {feed_id}: {e} -> trying regex fallback")
            try:
                import re as _re
                text = xml_data.decode("utf-8", errors="replace")
                titles_links = _re.findall(
                    r"<item[^>]*>.*?<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>.*?<link>(.*?)</link>",
                    text, _re.DOTALL
                )
                fb_count = 0
                for t_raw, l_raw in titles_links[:20]:
                    t_raw = _re.sub(r"<[^>]+>", "", t_raw).strip()
                    if not t_raw:
                        continue
                    keywords = _extract_kpop_keywords(t_raw)
                    if not keywords:
                        continue
                    signals.append({
                        "timestamp": _now_jst().isoformat(),
                        "source": "rss",
                        "source_id": feed_id,
                        "keyword": keywords[0],
                        "title": t_raw[:200],
                        "url": l_raw.strip(),
                        "engagement_score": feed_info.get("priority", "medium") == "high" and 2.0 or 1.0,
                        "language": feed_info.get("language", "en"),
                        "raw_data": {"all_keywords": keywords, "pub_date": "", "parser": "regex_fallback"},
                    })
                    fb_count += 1
                _log(f"    -> {fb_count} signals from {feed_id} (regex fallback)")
            except Exception as e2:
                _log(f"    WARN: Regex fallback also failed for {feed_id}: {e2}")
            continue

        except (HTTPError, URLError, OSError) as e:
            _log(f"    WARN: Failed to fetch {feed_id}: {e}")
            continue

    return signals


def _get_xml_text(element: ET.Element, tag: str) -> Optional[str]:
    """Get text from XML element, handling namespaces."""
    child = element.find(tag)
    if child is None:
        # Try Atom namespace
        child = element.find(f"{{http://www.w3.org/2005/Atom}}{tag}")
    if child is not None and child.text:
        return child.text.strip()
    # For Atom links, get href attribute
    if tag == "link" and child is not None:
        return child.get("href", "")
    return None


# K-POP keyword patterns — load from config/trend_keywords.json if available,
# fall back to hardcoded defaults.
_KEYWORDS_CONFIG = BASE / "config" / "trend_keywords.json"

def _load_keyword_lists() -> tuple[list[str], list[str]]:
    """Load keyword lists from config file, with hardcoded fallback."""
    if _KEYWORDS_CONFIG.exists():
        try:
            kw = json.loads(_KEYWORDS_CONFIG.read_text(encoding="utf-8"))
            artists = (
                kw.get("major_artists_en", [])
                + kw.get("major_artists_jp", [])
                + kw.get("agencies", [])
                + kw.get("major_executives", [])
            )
            terms = (
                kw.get("events_keywords", [])
                + kw.get("chart_keywords", [])
            )
            if artists or terms:
                return artists, terms
        except (json.JSONDecodeError, OSError):
            pass

    # Hardcoded fallback
    artists = [
        "BTS", "BLACKPINK", "TWICE", "aespa", "LE SSERAFIM", "NewJeans",
        "Stray Kids", "SEVENTEEN", "NCT", "EXO", "Red Velvet", "ITZY",
        "IVE", "NMIXX", "(G)I-DLE", "ENHYPEN", "TXT", "ATEEZ",
        "BIGBANG", "SHINee", "2NE1", "BABYMONSTER", "RIIZE",
        "TREASURE", "WINNER", "iKON", "MAMAMOO", "Dreamcatcher",
        "BTOB", "MONSTA X", "GOT7", "DAY6", "VIVIZ",
        "ジミン", "テテ", "ジョングク", "ジェニ", "リサ", "ロゼ",
        "ウォニョン", "カリナ", "ミンジ", "ハニ",
    ]
    terms = [
        "K-pop", "K-POP", "kpop", "comeback", "カムバック",
        "debut", "デビュー", "MV", "music video",
        "concert", "コンサート", "tour", "ツアー",
        "fan meeting", "ファンミ",
        "MAMA", "MNET", "Music Bank", "Inkigayo",
    ]
    return artists, terms

_KPOP_ARTISTS, _KPOP_TERMS = _load_keyword_lists()


def _extract_kpop_keywords(text: str) -> list[str]:
    """Extract K-POP related keywords from text."""
    found = []
    text_lower = text.lower()

    for artist in _KPOP_ARTISTS:
        if artist.lower() in text_lower:
            found.append(artist)

    for term in _KPOP_TERMS:
        if term.lower() in text_lower:
            if term not in found:
                found.append(term)

    return found


# ---------------------------------------------------------------------------
# X (Twitter) Collector
# ---------------------------------------------------------------------------

def collect_x_trends(config: dict) -> list[dict]:
    """
    Collect trend signals from X (Twitter) API v2.
    Gracefully skips if credentials are not available.
    """
    x_config = config.get("sources", {}).get("x_twitter", {})
    if not x_config.get("enabled", False):
        _log("X(Twitter) collection disabled")
        return []

    # Check credentials: prefer .env X_BEARER_TOKEN, fallback to credential file
    bearer_token = os.environ.get("X_BEARER_TOKEN", "")
    if not bearer_token:
        cred_path = os.path.expanduser(x_config.get("credential_path", "~/.x_credentials"))
        if os.path.exists(cred_path):
            try:
                with open(cred_path, "r") as f:
                    creds = json.load(f)
                bearer_token = creds.get("bearer_token", "")
            except (json.JSONDecodeError, OSError):
                pass
    if not bearer_token:
        _log("  X bearer_token not found (env/credentials) -> graceful skip")
        return []
    _log(f"  X bearer_token loaded ({len(bearer_token)} chars)")

    hashtags = x_config.get("hashtags", ["#KPOP"])
    min_rt = x_config.get("min_engagement_threshold", {}).get("retweet_count", 50)
    min_like = x_config.get("min_engagement_threshold", {}).get("like_count", 100)
    signals = []

    # Query top 3 hashtags to stay within rate limits
    for tag in hashtags[:3]:
        query = f"{tag} -is:retweet"
        endpoint = (
            f"https://api.twitter.com/2/tweets/search/recent"
            f"?query={_url_encode(query)}"
            f"&max_results=10"
            f"&tweet.fields=public_metrics,created_at"
        )

        try:
            req = Request(endpoint, headers={
                "Authorization": f"Bearer {bearer_token}",
                "User-Agent": "KPOPJournal-TrendCollector/1.0",
            })
            with urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())

            for tweet in data.get("data", []):
                metrics = tweet.get("public_metrics", {})
                rt = metrics.get("retweet_count", 0)
                likes = metrics.get("like_count", 0)

                if rt >= min_rt or likes >= min_like:
                    text = tweet.get("text", "")
                    keywords = _extract_kpop_keywords(text)

                    signals.append({
                        "timestamp": _now_jst().isoformat(),
                        "source": "x_twitter",
                        "source_id": tag,
                        "keyword": keywords[0] if keywords else tag,
                        "title": text[:200],
                        "url": f"https://x.com/i/status/{tweet.get('id', '')}",
                        "engagement_score": (rt * 2 + likes) / 100,
                        "language": "ja",
                        "raw_data": {
                            "retweet_count": rt,
                            "like_count": likes,
                            "reply_count": metrics.get("reply_count", 0),
                            "created_at": tweet.get("created_at", ""),
                            "all_keywords": keywords,
                        },
                    })

            _log(f"    -> {tag}: {len(data.get('data', []))} tweets checked")

        except (HTTPError, URLError, OSError) as e:
            _log(f"    WARN: X API error for {tag}: {e}")
            continue

    return signals


def _url_encode(s: str) -> str:
    """Simple URL encoding."""
    from urllib.parse import quote
    return quote(s, safe="")


# ---------------------------------------------------------------------------
# YouTube Collector
# ---------------------------------------------------------------------------

def collect_youtube(config: dict) -> list[dict]:
    """
    Collect trend signals from YouTube Data API v3.
    Gracefully skips if API key is not available.
    """
    yt_config = config.get("sources", {}).get("youtube", {})
    if not yt_config.get("enabled", False):
        _log("YouTube collection disabled")
        return []

    api_key = os.environ.get(yt_config.get("credential_env", "YOUTUBE_API_KEY"), "")
    if not api_key:
        _log("  YOUTUBE_API_KEY not set -> graceful skip")
        return []

    queries = yt_config.get("search_queries", ["K-POP MV 2026"])
    region = yt_config.get("region_code", "JP")
    max_results = yt_config.get("max_results_per_query", 10)
    signals = []

    for query in queries:
        endpoint = (
            f"https://www.googleapis.com/youtube/v3/search"
            f"?part=snippet"
            f"&q={_url_encode(query)}"
            f"&type=video"
            f"&regionCode={region}"
            f"&maxResults={max_results}"
            f"&order=viewCount"
            f"&publishedAfter={(_now_jst() - timedelta(days=3)).strftime('%Y-%m-%dT00:00:00Z')}"
            f"&key={api_key}"
        )

        try:
            req = Request(endpoint, headers={
                "User-Agent": "KPOPJournal-TrendCollector/1.0",
            })
            with urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())

            for item in data.get("items", []):
                snippet = item.get("snippet", {})
                title = snippet.get("title", "")
                video_id = item.get("id", {}).get("videoId", "")
                keywords = _extract_kpop_keywords(title)

                if keywords:
                    signals.append({
                        "timestamp": _now_jst().isoformat(),
                        "source": "youtube",
                        "source_id": query,
                        "keyword": keywords[0] if keywords else title[:50],
                        "title": title[:200],
                        "url": f"https://www.youtube.com/watch?v={video_id}" if video_id else None,
                        "engagement_score": 1.5,  # YouTube signals are weighted
                        "language": "ja",
                        "raw_data": {
                            "channel": snippet.get("channelTitle", ""),
                            "published_at": snippet.get("publishedAt", ""),
                            "all_keywords": keywords,
                        },
                    })

            _log(f"    -> YouTube '{query}': {len(data.get('items', []))} results")

        except HTTPError as e:
            if e.code == 403:
                _log(f"    WARN: YouTube API quota exceeded for '{query}' (403) — skipping remaining queries")
                break  # 配額超過なら残りクエリも無駄なのでループ終了
            _log(f"    WARN: YouTube API error for '{query}': {e}")
            continue
        except (URLError, OSError) as e:
            _log(f"    WARN: YouTube API error for '{query}': {e}")
            continue

    return signals


# ---------------------------------------------------------------------------
# GSC Rising Queries (delegate to trend_predictor.py output)
# ---------------------------------------------------------------------------

def collect_gsc_signals() -> list[dict]:
    """
    Read GSC rising query signals from trend_predictor.py's output log.
    This avoids duplicating the GSC API call.
    """
    trend_log = LOGS / "trend_predictions.jsonl"
    if not trend_log.exists():
        _log("  No trend_predictions.jsonl found -> skip GSC signals")
        return []

    signals = []
    cutoff = _now_jst() - timedelta(hours=24)

    with open(trend_log, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                ts_str = entry.get("timestamp", "")
                if ts_str:
                    ts = datetime.fromisoformat(ts_str)
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=JST)
                    if ts < cutoff:
                        continue

                for pred in entry.get("top_predictions", []):
                    if "gsc" in pred.get("source_signals", []):
                        signals.append({
                            "timestamp": _now_jst().isoformat(),
                            "source": "gsc_rising",
                            "source_id": "trend_predictor",
                            "keyword": pred.get("topic", ""),
                            "title": None,
                            "url": None,
                            "engagement_score": pred.get("buzz_score", 0) / 10,
                            "language": "ja",
                            "raw_data": {
                                "growth_ratio": pred.get("gsc_growth_ratio", 0),
                                "impressions": pred.get("gsc_impressions", 0),
                                "buzz_score": pred.get("buzz_score", 0),
                            },
                        })
            except (json.JSONDecodeError, ValueError):
                continue

    _log(f"  -> {len(signals)} GSC rising signals from trend_predictor output")
    return signals


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_collection(
    sources: Optional[list[str]] = None,
    dry_run: bool = False,
) -> list[dict]:
    """Main collection flow."""
    _log("=== Trend Collector START ===")

    config = _load_sources_config()
    all_signals: list[dict] = []

    collect_all = sources is None or "all" in sources

    # RSS
    if collect_all or "rss" in sources:
        _log("[1] RSS collection...")
        rss_signals = collect_rss(config)
        all_signals.extend(rss_signals)
        _log(f"  RSS total: {len(rss_signals)} signals")

    # X (Twitter)
    if collect_all or "x" in sources:
        _log("[2] X(Twitter) collection...")
        x_signals = collect_x_trends(config)
        all_signals.extend(x_signals)
        _log(f"  X total: {len(x_signals)} signals")

    # YouTube
    if collect_all or "youtube" in sources:
        _log("[3] YouTube collection...")
        yt_signals = collect_youtube(config)
        all_signals.extend(yt_signals)
        _log(f"  YouTube total: {len(yt_signals)} signals")

    # GSC (from trend_predictor output)
    if collect_all or "gsc" in sources:
        _log("[4] GSC rising queries (from trend_predictor)...")
        gsc_signals = collect_gsc_signals()
        all_signals.extend(gsc_signals)
        _log(f"  GSC total: {len(gsc_signals)} signals")

    # Summary
    _log(f"\nCollection complete: {len(all_signals)} total signals")

    if dry_run:
        _log("[dry-run] Skipping file write")
        for sig in all_signals[:10]:
            _log(f"  {sig['source']:12s} | {sig['keyword'][:30]:30s} | score={sig['engagement_score']:.1f}")
    else:
        # Cleanup old signals first
        output_config = config.get("output", {})
        max_age = output_config.get("max_age_days", 7)
        _cleanup_old_signals(max_age)

        # Write new signals
        _write_signals(all_signals)
        _log(f"Written {len(all_signals)} signals to {OUTPUT_PATH}")

    _log("=== Trend Collector END ===")
    return all_signals


def main():
    parser = argparse.ArgumentParser(
        description="K-POP Trend Collector - RSS/X/YouTube/GSCからトレンドシグナルを収集"
    )
    parser.add_argument(
        "--source",
        choices=["all", "rss", "x", "youtube", "gsc"],
        default="all",
        help="収集ソースを指定（default: all）",
    )
    parser.add_argument("--dry-run", action="store_true", help="収集結果表示のみ（書き込みなし）")
    args = parser.parse_args()

    sources = [args.source] if args.source != "all" else None
    run_collection(sources=sources, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
