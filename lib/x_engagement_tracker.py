#!/usr/bin/env python3
"""
x_engagement_tracker.py -- X投稿のエンゲージメント追跡 (Phase 8)

公開済みX投稿のreply/RT/likeを定期取得し、高反応パターンを抽出する。
learning_loop.pyと統合して記事品質改善にフィードバック。

Usage:
  python3 lib/x_engagement_tracker.py                    # 追跡実行
  python3 lib/x_engagement_tracker.py --dry-run          # 取得のみ（書き込みなし）
  python3 lib/x_engagement_tracker.py --analyze          # パターン分析のみ
  python3 lib/x_engagement_tracker.py --hours 48         # 過去48時間の投稿を追跡

管轄: メタモン（X投稿）+ ポリゴンZ（分析）
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"
DATA = BASE / "data"
CONFIG = BASE / "config"

CREDS_FILE = os.path.expanduser("~/.x_credentials")
BUZZ_PATTERNS_PATH = DATA / "buzz_patterns.jsonl"
ENGAGEMENT_LOG = LOGS / "x_engagement_tracking.jsonl"
LEARNING_HISTORY = LOGS / "learning_history.jsonl"
X_QUEUE_LOG = LOGS / "x_queue.jsonl"
X_POST_LOG = LOGS / "x_post_log.jsonl"

JST = timezone(timedelta(hours=9))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_jst() -> datetime:
    return datetime.now(JST)


def _log(msg: str):
    ts = _now_jst().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")


def _load_credentials() -> Optional[dict]:
    """Load X API credentials. Returns None if not available."""
    if not os.path.exists(CREDS_FILE):
        _log("X credentials not found -> graceful skip")
        return None
    try:
        with open(CREDS_FILE, "r") as f:
            creds = json.load(f)
        # Need bearer_token for v2 read endpoints
        if not creds.get("bearer_token"):
            _log("bearer_token not found in credentials -> graceful skip")
            return None
        return creds
    except (json.JSONDecodeError, OSError) as e:
        _log(f"Credentials load error: {e} -> graceful skip")
        return None


# ---------------------------------------------------------------------------
# Tweet ID collection from logs
# ---------------------------------------------------------------------------

def _collect_recent_tweet_ids(hours: int = 24) -> list[dict]:
    """
    Collect tweet IDs from X post logs.
    Returns list of {tweet_id, article_url, posted_at, text}.
    """
    cutoff = _now_jst() - timedelta(hours=hours)
    tweets = []

    # Check multiple log sources for tweet IDs
    log_files = [X_POST_LOG, X_QUEUE_LOG]

    for log_file in log_files:
        if not log_file.exists():
            continue
        with open(log_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    ts_str = entry.get("ts", entry.get("timestamp", ""))
                    if ts_str:
                        ts = datetime.fromisoformat(ts_str)
                        if ts.tzinfo is None:
                            ts = ts.replace(tzinfo=JST)
                        if ts < cutoff:
                            continue

                    tweet_id = entry.get("tweet_id", "")
                    if not tweet_id:
                        # Try to extract from result/url
                        result = entry.get("result", "")
                        m = re.search(r"TWEET_ID=(\d+)", result) if isinstance(result, str) else None
                        if m:
                            tweet_id = m.group(1)

                    if tweet_id:
                        tweets.append({
                            "tweet_id": str(tweet_id),
                            "article_url": entry.get("url", entry.get("article_url", "")),
                            "posted_at": ts_str,
                            "text": entry.get("text", entry.get("tweet_text", ""))[:200],
                        })
                except (json.JSONDecodeError, ValueError):
                    continue

    # Deduplicate by tweet_id
    seen = set()
    unique = []
    for t in tweets:
        if t["tweet_id"] not in seen:
            seen.add(t["tweet_id"])
            unique.append(t)

    return unique


# ---------------------------------------------------------------------------
# X API v2 engagement fetch
# ---------------------------------------------------------------------------

def fetch_tweet_metrics(tweet_ids: list[str], bearer_token: str) -> dict[str, dict]:
    """
    Fetch public metrics for a batch of tweet IDs via X API v2.
    Returns {tweet_id: {retweet_count, reply_count, like_count, ...}}.
    """
    if not tweet_ids:
        return {}

    results = {}

    # X API v2 allows up to 100 IDs per request
    for batch_start in range(0, len(tweet_ids), 100):
        batch = tweet_ids[batch_start:batch_start + 100]
        ids_param = ",".join(batch)

        endpoint = (
            f"https://api.twitter.com/2/tweets"
            f"?ids={ids_param}"
            f"&tweet.fields=public_metrics,created_at"
        )

        try:
            req = Request(endpoint, headers={
                "Authorization": f"Bearer {bearer_token}",
                "User-Agent": "KPOPJournal-EngagementTracker/1.0",
            })
            with urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())

            for tweet in data.get("data", []):
                tid = tweet.get("id", "")
                metrics = tweet.get("public_metrics", {})
                results[tid] = {
                    "retweet_count": metrics.get("retweet_count", 0),
                    "reply_count": metrics.get("reply_count", 0),
                    "like_count": metrics.get("like_count", 0),
                    "quote_count": metrics.get("quote_count", 0),
                    "impression_count": metrics.get("impression_count", 0),
                    "fetched_at": _now_jst().isoformat(),
                }

            _log(f"  Fetched metrics for {len(data.get('data', []))}/{len(batch)} tweets")

        except HTTPError as e:
            if e.code == 429:
                _log(f"  WARN: Rate limited (429). Stopping batch fetch.")
                break
            elif e.code in (401, 403):
                _log(f"  WARN: Auth error ({e.code}). Check credentials.")
                break
            else:
                _log(f"  WARN: HTTP {e.code} fetching tweet metrics")
        except (URLError, OSError) as e:
            _log(f"  WARN: Network error: {e}")

    return results


# ---------------------------------------------------------------------------
# Engagement scoring and pattern extraction
# ---------------------------------------------------------------------------

def compute_engagement_score(metrics: dict) -> float:
    """
    Compute a normalized engagement score (0-100).
    Weighted: RT=3x, quote=2x, reply=2x, like=1x.
    """
    rt = metrics.get("retweet_count", 0)
    quote = metrics.get("quote_count", 0)
    reply = metrics.get("reply_count", 0)
    like = metrics.get("like_count", 0)

    raw = rt * 3 + quote * 2 + reply * 2 + like
    # Normalize: 100 raw = score 50 (log scale for high values)
    import math
    if raw <= 0:
        return 0.0
    score = min(100, math.log10(raw + 1) * 25)
    return round(score, 1)


def extract_buzz_pattern(tweet_info: dict, metrics: dict) -> Optional[dict]:
    """
    Extract a buzz pattern from a high-engagement tweet.
    Returns a pattern dict or None if engagement is too low.
    """
    score = compute_engagement_score(metrics)
    if score < 10:  # Minimum threshold
        return None

    text = tweet_info.get("text", "")
    article_url = tweet_info.get("article_url", "")

    # Detect content features
    features = []
    if "?" in text or "\uff1f" in text:
        features.append("question")
    if any(c in text for c in "!！"):
        features.append("exclamation")
    if re.search(r"#\w+", text):
        features.append("hashtag")
    if re.search(r"https?://", text):
        features.append("link")
    if any(w in text for w in ["速報", "最新", "判明", "発表", "決定"]):
        features.append("breaking_news")
    if any(w in text for w in ["まとめ", "一覧", "ランキング", "比較"]):
        features.append("listicle")
    if len(text) < 80:
        features.append("short_text")
    elif len(text) > 200:
        features.append("long_text")

    return {
        "timestamp": _now_jst().isoformat(),
        "tweet_id": tweet_info.get("tweet_id", ""),
        "article_url": article_url,
        "engagement_score": score,
        "metrics": metrics,
        "text_length": len(text),
        "features": features,
        "text_preview": text[:100],
        "source": "x_engagement_tracker",
    }


# ---------------------------------------------------------------------------
# Pattern analysis
# ---------------------------------------------------------------------------

def analyze_patterns() -> dict:
    """
    Analyze accumulated buzz patterns to find common traits of high-engagement posts.
    Returns summary statistics.
    """
    if not BUZZ_PATTERNS_PATH.exists():
        _log("No buzz_patterns.jsonl found")
        return {}

    patterns = []
    with open(BUZZ_PATTERNS_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                patterns.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    if not patterns:
        _log("No patterns to analyze")
        return {}

    # Feature frequency in high-engagement posts
    feature_counts: dict[str, int] = {}
    total = len(patterns)
    high_engagement = [p for p in patterns if p.get("engagement_score", 0) >= 30]
    all_scores = [p.get("engagement_score", 0) for p in patterns]

    for p in high_engagement:
        for feat in p.get("features", []):
            feature_counts[feat] = feature_counts.get(feat, 0) + 1

    # Sort features by frequency
    top_features = sorted(feature_counts.items(), key=lambda x: -x[1])

    # Average text length for high vs low engagement
    high_avg_len = (
        sum(p.get("text_length", 0) for p in high_engagement) / len(high_engagement)
        if high_engagement else 0
    )
    low_engagement = [p for p in patterns if p.get("engagement_score", 0) < 30]
    low_avg_len = (
        sum(p.get("text_length", 0) for p in low_engagement) / len(low_engagement)
        if low_engagement else 0
    )

    analysis = {
        "analyzed_at": _now_jst().isoformat(),
        "total_patterns": total,
        "high_engagement_count": len(high_engagement),
        "avg_score": round(sum(all_scores) / total, 1) if total else 0,
        "top_features": top_features[:10],
        "high_engagement_avg_text_length": round(high_avg_len),
        "low_engagement_avg_text_length": round(low_avg_len),
        "insights": [],
    }

    # Generate insights
    if top_features:
        top_feat_name = top_features[0][0]
        analysis["insights"].append(
            f"高エンゲージメント投稿で最も多い特徴: {top_feat_name} "
            f"({top_features[0][1]}/{len(high_engagement)}件)"
        )

    if high_avg_len > 0 and low_avg_len > 0:
        if high_avg_len < low_avg_len:
            analysis["insights"].append(
                f"短い投稿の方がエンゲージメントが高い傾向 "
                f"(高: {round(high_avg_len)}字 vs 低: {round(low_avg_len)}字)"
            )
        else:
            analysis["insights"].append(
                f"長い投稿の方がエンゲージメントが高い傾向 "
                f"(高: {round(high_avg_len)}字 vs 低: {round(low_avg_len)}字)"
            )

    return analysis


# ---------------------------------------------------------------------------
# Learning Loop integration
# ---------------------------------------------------------------------------

def _write_to_learning_history(analysis: dict):
    """Write engagement analysis summary to learning_history.jsonl for learning_loop integration."""
    if not analysis:
        return

    entry = {
        "timestamp": _now_jst().isoformat(),
        "source": "x_engagement_tracker",
        "type": "engagement_analysis",
        "data": analysis,
    }

    LOGS.mkdir(parents=True, exist_ok=True)
    with open(LEARNING_HISTORY, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_tracking(hours: int = 24, dry_run: bool = False) -> list[dict]:
    """Main tracking flow."""
    _log("=== X Engagement Tracker START ===")

    # 1. Collect recent tweet IDs
    _log(f"[1] Collecting tweet IDs from past {hours}h...")
    tweet_infos = _collect_recent_tweet_ids(hours=hours)
    _log(f"  Found {len(tweet_infos)} tweets to track")

    if not tweet_infos:
        _log("No tweets to track. Done.")
        return []

    # 2. Fetch metrics from X API
    creds = _load_credentials()
    all_patterns = []

    if creds:
        _log("[2] Fetching engagement metrics from X API...")
        tweet_ids = [t["tweet_id"] for t in tweet_infos]
        metrics_map = fetch_tweet_metrics(tweet_ids, creds["bearer_token"])
        _log(f"  Got metrics for {len(metrics_map)} tweets")

        # 3. Extract patterns
        _log("[3] Extracting buzz patterns...")
        for info in tweet_infos:
            tid = info["tweet_id"]
            if tid in metrics_map:
                pattern = extract_buzz_pattern(info, metrics_map[tid])
                if pattern:
                    all_patterns.append(pattern)

        _log(f"  Extracted {len(all_patterns)} buzz patterns")
    else:
        _log("[2] Skipping API fetch (no credentials)")
        _log("[3] Skipping pattern extraction")

    # 4. Write results
    if not dry_run and all_patterns:
        DATA.mkdir(parents=True, exist_ok=True)
        with open(BUZZ_PATTERNS_PATH, "a", encoding="utf-8") as f:
            for pattern in all_patterns:
                f.write(json.dumps(pattern, ensure_ascii=False) + "\n")
        _log(f"Written {len(all_patterns)} patterns to {BUZZ_PATTERNS_PATH}")

        # Log to engagement tracking
        LOGS.mkdir(parents=True, exist_ok=True)
        log_entry = {
            "timestamp": _now_jst().isoformat(),
            "tweets_checked": len(tweet_infos),
            "metrics_fetched": len(metrics_map) if creds else 0,
            "patterns_extracted": len(all_patterns),
            "avg_engagement_score": (
                round(sum(p["engagement_score"] for p in all_patterns) / len(all_patterns), 1)
                if all_patterns else 0
            ),
        }
        with open(ENGAGEMENT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
    elif dry_run:
        _log("[dry-run] Skipping file write")
        for p in all_patterns[:5]:
            _log(f"  score={p['engagement_score']:5.1f} | features={p['features']} | {p['text_preview'][:60]}")

    _log("=== X Engagement Tracker END ===")
    return all_patterns


def main():
    parser = argparse.ArgumentParser(
        description="X投稿エンゲージメント追跡 & バズパターン抽出"
    )
    parser.add_argument("--hours", type=int, default=24, help="追跡対象の時間範囲（default: 24h）")
    parser.add_argument("--dry-run", action="store_true", help="取得のみ（書き込みなし）")
    parser.add_argument("--analyze", action="store_true", help="パターン分析のみ")
    args = parser.parse_args()

    if args.analyze:
        analysis = analyze_patterns()
        if analysis:
            _log("\n=== Engagement Pattern Analysis ===")
            _log(f"  Total patterns: {analysis['total_patterns']}")
            _log(f"  High engagement: {analysis['high_engagement_count']}")
            _log(f"  Avg score: {analysis['avg_score']}")
            for feat, count in analysis.get("top_features", []):
                _log(f"    {feat}: {count}")
            for insight in analysis.get("insights", []):
                _log(f"  >> {insight}")

            # Write to learning history
            _write_to_learning_history(analysis)
        return

    run_tracking(hours=args.hours, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
