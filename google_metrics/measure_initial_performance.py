#!/usr/bin/env python3
"""
初動パフォーマンス測定（v1.2 Phase 4）

投稿後24時間のPV・流入元を計測し、記録する。
毎日10:00にcronで実行し、前日投稿分の初動を計測。

データ本部（ミュウツー）管轄
"""
import json
import os
import sys
from datetime import date, datetime, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

LOGS_DIR = os.path.join(BASE_DIR, "logs")
KPI_FILE = os.path.join(LOGS_DIR, "kpi_posts.jsonl")
INITIAL_PERF_FILE = os.path.join(LOGS_DIR, "initial_performance.jsonl")
METRICS_FILE = os.path.join(BASE_DIR, "google_metrics", "metrics_yesterday.json")


def load_yesterday_posts():
    """前日に投稿された記事をKPIログから取得"""
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    posts = []
    if not os.path.exists(KPI_FILE):
        return posts
    with open(KPI_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if entry.get("date") == yesterday:
                    posts.append(entry)
            except json.JSONDecodeError:
                continue
    return posts


def load_metrics():
    """GA4/GSCメトリクスを読み込み"""
    if not os.path.exists(METRICS_FILE):
        return {}
    with open(METRICS_FILE, encoding="utf-8") as f:
        return json.load(f)


def measure_initial_performance():
    """前日投稿分の初動パフォーマンスを計測"""
    posts = load_yesterday_posts()
    if not posts:
        print("前日投稿なし → スキップ")
        return

    metrics = load_metrics()
    ga4 = metrics.get("ga4", {})
    gsc = metrics.get("gsc", {})

    # GA4のトップページデータからURL別PVを取得
    top_pages = ga4.get("top_landing_pages", [])
    page_pv_map = {}
    for page in top_pages:
        if isinstance(page, dict):
            page_pv_map[page.get("page", "")] = page.get("sessions", 0)
        elif isinstance(page, str):
            page_pv_map[page] = 0

    # GSCのトップページデータ
    gsc_pages = gsc.get("top_pages", [])
    page_clicks_map = {}
    page_impressions_map = {}
    for page in gsc_pages:
        if isinstance(page, dict):
            url = page.get("page", page.get("url", ""))
            page_clicks_map[url] = page.get("clicks", 0)
            page_impressions_map[url] = page.get("impressions", 0)

    os.makedirs(LOGS_DIR, exist_ok=True)
    results = []

    for post in posts:
        slug = post.get("slug", "")
        url = post.get("url", "")
        post_id = post.get("post_id", "")

        # URLまたはスラッグでマッチ
        initial_pv = 0
        search_clicks = 0
        search_impressions = 0

        for page_url, pv in page_pv_map.items():
            if slug and slug in page_url:
                initial_pv += pv
            elif url and url in page_url:
                initial_pv += pv

        for page_url, clicks in page_clicks_map.items():
            if slug and slug in page_url:
                search_clicks += clicks
            elif url and url in page_url:
                search_clicks += clicks

        for page_url, imps in page_impressions_map.items():
            if slug and slug in page_url:
                search_impressions += imps
            elif url and url in page_url:
                search_impressions += imps

        result = {
            "timestamp": datetime.now().isoformat(),
            "measurement_date": date.today().isoformat(),
            "post_date": post.get("date", ""),
            "post_id": post_id,
            "title": post.get("title", ""),
            "url": url,
            "slug": slug,
            "pipeline": post.get("pipeline", ""),
            "char_count": post.get("char_count", 0),
            "initial_24h_pv": initial_pv,
            "initial_24h_search_clicks": search_clicks,
            "initial_24h_search_impressions": search_impressions,
            "has_cta": post.get("has_cta", False),
            "token_count": post.get("token_count", 0),
        }
        results.append(result)

        with open(INITIAL_PERF_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")

    # サマリー出力
    total_posts = len(results)
    total_pv = sum(r["initial_24h_pv"] for r in results)
    avg_pv = total_pv / total_posts if total_posts else 0

    print(f"初動計測完了: {total_posts}記事")
    print(f"  合計PV: {total_pv}")
    print(f"  平均PV: {avg_pv:.1f}")
    for r in results:
        print(f"  - [{r['initial_24h_pv']}PV] {r['title'][:40]}")

    return results


TWEET_DB_FILE = os.path.join(LOGS_DIR, "tweet_id_db.tsv")


def algo_engagement_value(m: dict) -> float:
    """最新Xアルゴ(2026/5/15)の重みで public_metrics を1指標化(like基準)。
    public_metrics で取れるのは like/reply/retweet/quote/bookmark/impression。
    著者返信(+75)・プロフィール訪問(+12)・リンク2分閲覧(+10-11)・ネガティブ(-74/-369)は
    public_metrics では取得不能のため 0 扱い(将来 non_public_metrics/analytics で拡張)。"""
    return (
        13.5 * m.get("reply_count", 0)
        + 10.0 * m.get("bookmark_count", 0)
        + 5.0 * m.get("quote_count", 0)
        + 1.0 * m.get("retweet_count", 0)
        + 0.5 * m.get("like_count", 0)
    )


def _recent_tweet_ids(days: int = 2) -> list[tuple[str, str, str]]:
    """tweet_id_db.tsv から直近 days 日の (post_id, tweet_id, title) を返す。"""
    if not os.path.exists(TWEET_DB_FILE):
        return []
    cutoff = datetime.now() - timedelta(days=days)
    rows = []
    with open(TWEET_DB_FILE, encoding="utf-8") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 4:
                continue
            post_id, tweet_id, title, posted_at = parts[0], parts[1], parts[2], parts[3]
            if not tweet_id.isdigit():
                continue
            try:
                ts = datetime.fromisoformat(posted_at.replace("Z", ""))
            except ValueError:
                ts = cutoff  # パース不能は対象に含める
            if ts >= cutoff:
                rows.append((post_id, tweet_id, title))
    return rows


TITLE_PERF_FILE = os.path.join(LOGS_DIR, "title_performance.jsonl")
# score_per_impression がこの値を超えた投稿を「勝ち」とみなす(運用で調整)。
X_WIN_SPI_THRESHOLD = float(os.environ.get("X_WIN_SPI_THRESHOLD", "0.5"))


def _reflect_wins_to_title_performance(x_results: list[dict]):
    """X実測(score_per_impression)を title_performance.jsonl に還元。
    閾値超の post_id を result=win に昇格し x_score_per_impression を記録。
    既存行を post_id でマッチして上書き(無ければ何もしない=PVパイプラインが作る行を尊重)。"""
    if not x_results or not os.path.exists(TITLE_PERF_FILE):
        return
    by_pid = {str(r["post_id"]): r for r in x_results if r.get("post_id")}
    if not by_pid:
        return
    lines = [l for l in open(TITLE_PERF_FILE, encoding="utf-8") if l.strip()]
    out, promoted = [], 0
    for line in lines:
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            out.append(line)
            continue
        pid = str(rec.get("post_id", ""))
        xr = by_pid.get(pid)
        if xr:
            rec["x_score_per_impression"] = xr["x_score_per_impression"]
            rec["x_engagement_value"] = xr["x_engagement_value"]
            if xr["x_score_per_impression"] >= X_WIN_SPI_THRESHOLD and rec.get("result") != "win":
                rec["result"] = "win"
                promoted += 1
        out.append(json.dumps(rec, ensure_ascii=False) + "\n")
    with open(TITLE_PERF_FILE, "w", encoding="utf-8") as f:
        f.writelines(out)
    if promoted:
        print(f"  title_performance: {promoted}件を実測でwin昇格(SPI>={X_WIN_SPI_THRESHOLD})")


def measure_x_engagement(days: int = 2):
    """直近投稿の X public_metrics を取得し、アルゴ重みでスコア化して
    initial_performance.jsonl に相乗り記録する(施策3a/3b)。"""
    rows = _recent_tweet_ids(days)
    if not rows:
        print("X: 直近 tweet_id なし → スキップ")
        return []
    try:
        from google_metrics.post_to_x import get_public_metrics
    except ImportError as e:
        print(f"X: post_to_x import 失敗 → スキップ ({e})")
        return []

    ids = [r[1] for r in rows]
    metrics = get_public_metrics(ids)
    if not metrics:
        print("X: public_metrics 取得0件(API tier/権限/失効の可能性)")
        return []

    os.makedirs(LOGS_DIR, exist_ok=True)
    results = []
    for post_id, tweet_id, title in rows:
        m = metrics.get(tweet_id)
        if not m:
            continue
        imp = m.get("impression_count", 0)
        ev = algo_engagement_value(m)
        rec = {
            "timestamp": datetime.now().isoformat(),
            "measurement_date": date.today().isoformat(),
            "source": "x_engagement",
            "post_id": post_id,
            "tweet_id": tweet_id,
            "title": title,
            "x_likes": m.get("like_count", 0),
            "x_replies": m.get("reply_count", 0),
            "x_retweets": m.get("retweet_count", 0),
            "x_quotes": m.get("quote_count", 0),
            "x_bookmarks": m.get("bookmark_count", 0),
            "x_impressions": imp,
            "x_engagement_value": round(ev, 2),
            "x_score_per_impression": round(ev / imp, 4) if imp else 0.0,
        }
        results.append(rec)
        with open(INITIAL_PERF_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # title_performance.jsonl に実測を還元(施策3b): score_per_impression が
    # 閾値超の post を result=win に昇格し x_score_per_impression を付与。
    # x_pre_score.similarity_score が実測重み付けに使う(ループを閉じる)。
    _reflect_wins_to_title_performance(results)

    n = len(results)
    avg = sum(r["x_score_per_impression"] for r in results) / n if n else 0
    print(f"X初動計測完了: {n}件 / 平均 score_per_impression={avg:.4f}")
    for r in sorted(results, key=lambda x: x["x_engagement_value"], reverse=True)[:5]:
        print(f"  - [EV={r['x_engagement_value']} reply={r['x_replies']} imp={r['x_impressions']}] {r['title'][:36]}")
    return results


if __name__ == "__main__":
    import sys as _sys
    if "--x" in _sys.argv:
        measure_x_engagement()
    else:
        measure_initial_performance()
        # PV計測に続けて X エンゲージメントも計測(同 cron に相乗り)
        measure_x_engagement()
