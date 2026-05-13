#!/usr/bin/env python3
"""
lib/trending_widget.py
急上昇ランキングウィジェット — トップページ自動挿入

GA4メトリクス + GSCデータから直近の急上昇記事を抽出し、
トップページ (page ID 368) の entry-content に
急上昇ランキングHTMLを自動注入する。

CTA_JS_APPEND のスクリプト領域でDOM注入する方式で、
既存の ui_optimizer.py のCSS適用とは独立して動作可能。

Usage:
  python3 lib/trending_widget.py generate   # HTMLプレビュー表示
  python3 lib/trending_widget.py apply      # トップページに注入
  python3 lib/trending_widget.py update     # GA4→ランキング更新→注入
"""

import json
import re
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
LOGS = BASE_DIR / "logs"
GMETRICS = BASE_DIR / "google_metrics"
METRICS_FILE = GMETRICS / "metrics_yesterday.json"
ARTICLE_INDEX = LOGS / "article_index.json"
WIN_PATTERNS = LOGS / "winning_patterns.jsonl"
TRENDING_CACHE = LOGS / "trending_ranking.json"

WP_BASE = "https://www.kpopjournal.tokyo/wp-json/wp/v2"
WP_AUTH_FILE = Path.home() / ".wp_auth"
SITE_URL = "https://www.kpopjournal.tokyo"
TOP_PAGE_ID = 368

JST = timezone(timedelta(hours=9))
MAX_RANKING = 5


def _get_auth_header():
    if not WP_AUTH_FILE.exists():
        return None
    content = WP_AUTH_FILE.read_text()
    m = re.search(r'Authorization:\s*(Basic\s+\S+)', content, re.IGNORECASE)
    if m:
        return m.group(1)
    token = content.strip().split()[-1]
    return f"Basic {token}"


def _wp_request(method, path, data=None):
    auth = _get_auth_header()
    if not auth:
        return None, "AUTH_FAIL"
    url = f"{WP_BASE}{path}"
    headers = {
        "Authorization": auth,
        "Content-Type": "application/json",
        "User-Agent": "kpop-trending-widget/1.0",
    }
    body = json.dumps(data, ensure_ascii=False).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8")), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.read().decode('utf-8', errors='replace')[:300]}"
    except Exception as e:
        return None, str(e)


def _load_metrics():
    """GA4 + GSC メトリクスを読み込み"""
    if not METRICS_FILE.exists():
        return None
    try:
        return json.loads(METRICS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_article_index():
    """記事インデックスを読み込み"""
    if not ARTICLE_INDEX.exists():
        return {}
    try:
        data = json.loads(ARTICLE_INDEX.read_text(encoding="utf-8"))
        articles = data.get("articles", []) if isinstance(data, dict) else data
        # slug → article mapping
        index = {}
        for a in articles:
            url = a.get("url", "")
            slug = url.rstrip("/").split("/")[-1] if url else ""
            if slug:
                index[slug] = a
        return index
    except Exception:
        return {}


def _load_winning_patterns():
    """winning_patterns から最近の高スコア記事を取得"""
    if not WIN_PATTERNS.exists():
        return []
    records = []
    try:
        for line in WIN_PATTERNS.read_text(encoding="utf-8").splitlines()[-100:]:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except Exception:
                    pass
    except Exception:
        pass
    return records


def compute_trending():
    """急上昇ランキングを計算"""
    print(f"[{datetime.now(JST).isoformat()}] compute_trending start", flush=True)
    metrics = _load_metrics()
    if not metrics:
        print("WARN: metrics_yesterday.json が読めません", file=sys.stderr)
        return []

    article_index = _load_article_index()
    trending = []

    # GA4 トップランディングページからスコア計算
    ga4 = metrics.get("ga4", {})
    top_pages = ga4.get("top_landing_pages", [])

    for page in top_pages:
        path = page.get("page", "")
        if not path or path == "/" or path == "(not set)":
            continue
        slug = path.strip("/")
        sessions = int(page.get("sessions", 0))
        engaged = int(page.get("engaged_sessions", 0))
        duration = float(page.get("avg_session_duration", 0))

        # エンゲージメントスコア = sessions * (1 + engaged_ratio) * duration_factor
        engaged_ratio = engaged / max(sessions, 1)
        duration_factor = min(duration / 60, 3.0)  # 最大3倍
        score = sessions * (1 + engaged_ratio) * (1 + duration_factor * 0.3)

        title = ""
        article = article_index.get(slug)
        if article:
            title = article.get("title", "")

        trending.append({
            "slug": slug,
            "path": path,
            "title": title,
            "sessions": sessions,
            "engaged_sessions": engaged,
            "duration": round(duration, 1),
            "score": round(score, 2),
            "source": "ga4",
        })

    # GSC データで補強 (高CTRの新記事を検出)
    gsc = metrics.get("gsc", {})
    gsc_pages = gsc.get("top_pages", [])

    existing_slugs = {t["slug"] for t in trending}
    for gp in gsc_pages:
        url = gp.get("page", "")
        slug = url.rstrip("/").split("/")[-1] if url else ""
        if not slug or slug in existing_slugs:
            # 既存エントリはGSCスコアで加点
            for t in trending:
                if t["slug"] == slug:
                    clicks = int(gp.get("clicks", 0))
                    impressions = int(gp.get("impressions", 0))
                    t["score"] += clicks * 2 + impressions * 0.05
                    t["gsc_clicks"] = clicks
                    t["gsc_impressions"] = impressions
            continue

        clicks = int(gp.get("clicks", 0))
        impressions = int(gp.get("impressions", 0))
        ctr = float(gp.get("ctr", 0))

        if clicks < 1:
            continue

        score = clicks * 3 + impressions * 0.1 + ctr * 10

        title = ""
        article = article_index.get(slug)
        if article:
            title = article.get("title", "")

        trending.append({
            "slug": slug,
            "path": f"/{slug}/",
            "title": title,
            "sessions": 0,
            "score": round(score, 2),
            "source": "gsc",
            "gsc_clicks": clicks,
            "gsc_impressions": impressions,
        })

    # スコア順にソート
    trending.sort(key=lambda x: x["score"], reverse=True)

    # タイトルが未取得のものをWP APIで補完
    for item in trending[:MAX_RANKING]:
        if not item["title"]:
            item["title"] = _fetch_title(item["slug"])

    result = trending[:MAX_RANKING]

    # キャッシュ保存
    cache = {
        "updated_at": datetime.now(JST).isoformat(),
        "date": metrics.get("date", ""),
        "ranking": result,
    }
    TRENDING_CACHE.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print(f"[{datetime.now(JST).isoformat()}] compute_trending done count={len(result)}", flush=True)
    return result


def _fetch_title(slug):
    """WP APIからタイトルを取得"""
    try:
        url = f"{WP_BASE}/posts?slug={slug}&_fields=title"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data and isinstance(data, list):
                return data[0].get("title", {}).get("rendered", "")
    except Exception:
        pass
    return slug


def generate_html(ranking=None):
    """急上昇ランキングHTMLを生成"""
    if ranking is None:
        # キャッシュから読み込み
        if TRENDING_CACHE.exists():
            try:
                cache = json.loads(TRENDING_CACHE.read_text(encoding="utf-8"))
                ranking = cache.get("ranking", [])
            except Exception:
                ranking = []
        if not ranking:
            ranking = compute_trending()

    if not ranking:
        return ""

    items_html = []
    for i, item in enumerate(ranking[:MAX_RANKING]):
        rank = i + 1
        title = item.get("title", item.get("slug", ""))
        # HTMLエンティティをデコード
        title = title.replace("&amp;", "&").replace("&#8211;", "–").replace("&#8212;", "—")
        path = item.get("path", f"/{item.get('slug', '')}/")
        url = f"{SITE_URL}{path}"

        badge = ""
        if item.get("gsc_clicks", 0) >= 3:
            badge = '<span class="kpj-trend-badge">検索急上昇</span>'
        elif item.get("engaged_sessions", 0) >= 2:
            badge = '<span class="kpj-trend-badge">注目</span>'
        elif rank == 1:
            badge = '<span class="kpj-trend-badge">HOT</span>'

        items_html.append(
            f'<a class="kpj-trend-item" href="{url}">'
            f'<span class="kpj-trend-rank r{rank}">{rank}</span>'
            f'<span class="kpj-trend-title">{title}</span>'
            f'{badge}'
            f'</a>'
        )

    now_str = datetime.now(JST).strftime("%m/%d %H:%M")
    html = (
        f'<div id="kpj-trending">'
        f'<h2>急上昇ランキング</h2>'
        f'<div class="kpj-trend-list">{"".join(items_html)}</div>'
        f'<div style="text-align:right;font-size:11px;color:#999;margin-top:8px;">'
        f'更新: {now_str}</div>'
        f'</div>'
    )
    return html


def generate_trending_js():
    """CTA_JS_APPEND のスクリプト内に追加するトレンドウィジェットDOM注入JS"""
    ranking = None
    if TRENDING_CACHE.exists():
        try:
            cache = json.loads(TRENDING_CACHE.read_text(encoding="utf-8"))
            ranking = cache.get("ranking", [])
        except Exception:
            pass
    if not ranking:
        ranking = compute_trending()

    html = generate_html(ranking)
    if not html:
        return ""

    # JSの文字列内で安全にエスケープ
    escaped = html.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "")

    js = f"""
  /* ─ 急上昇ランキング注入 ─ */
  if(document.body.className.indexOf('front-top-page')!==-1){{
    var ec=document.querySelector('.entry-content');
    if(ec){{
      var tw=document.createElement('div');
      tw.innerHTML='{escaped}';
      ec.appendChild(tw.firstChild);
    }}
  }}"""
    return js


PHASE1_CSS = (BASE_DIR / "lib" / "phase1_toppage.css").resolve()


def _load_phase1_css():
    """Phase1 CSSテンプレートを読み込む (ファイルがなければ埋め込みを使う)"""
    # 現在のページからCSS+JSブロックを抽出して再利用
    resp, err = _wp_request("GET", f"/pages/{TOP_PAGE_ID}")
    if err:
        return "", ""
    raw = resp.get("content", {}).get("raw", "")
    css_match = re.search(r'(<style id="kpj-phase1-css">.*?</style>)', raw, re.DOTALL)
    js_match = re.search(r'(<script>.*?</script>)\s*$', raw, re.DOTALL)
    css_block = css_match.group(1) if css_match else ""
    js_block = js_match.group(1) if js_match else ""
    return css_block, js_block


def apply_to_top_page():
    """トップページ(page 368)のコンテンツにランキングHTML + CSS + JSをフル注入"""
    ranking = compute_trending()
    if not ranking:
        print("ERROR: ランキングデータなし")
        return False

    ranking_html = generate_html(ranking)
    if not ranking_html:
        print("ERROR: HTML生成失敗")
        return False

    # 既存のCSS+JSブロックを取得（Phase1で注入済みのものを維持）
    css_block, js_block = _load_phase1_css()

    # 全体を組み立て: ランキング + CSS + JS
    parts = [ranking_html]
    if css_block:
        parts.append(css_block)
    if js_block:
        parts.append(js_block)

    new_content = "\n".join(parts)

    resp, err = _wp_request("POST", f"/pages/{TOP_PAGE_ID}", {
        "content": new_content,
    })
    if err:
        print(f"ERROR: ページ更新失敗: {err}")
        return False

    print(f"OK: トップページにランキング注入完了 ({len(ranking)}件)")
    return True


def main():
    import argparse
    parser = argparse.ArgumentParser(description="急上昇ランキングウィジェット")
    parser.add_argument("action", choices=["generate", "apply", "update"],
                        help="generate=HTMLプレビュー, apply=トップページ注入, update=データ更新+注入")
    args = parser.parse_args()

    if args.action == "generate":
        ranking = compute_trending()
        html = generate_html(ranking)
        print(html)
        print(f"\n--- {len(ranking)}件のランキング生成 ---")
        for i, r in enumerate(ranking):
            print(f"  {i+1}. [{r['score']:.1f}pt] {r['title'][:50]} ({r['source']})")

    elif args.action == "apply":
        apply_to_top_page()

    elif args.action == "update":
        ranking = compute_trending()
        print(f"ランキング更新完了: {len(ranking)}件")
        for i, r in enumerate(ranking):
            print(f"  {i+1}. [{r['score']:.1f}pt] {r['title'][:50]}")
        apply_to_top_page()


if __name__ == "__main__":
    main()
