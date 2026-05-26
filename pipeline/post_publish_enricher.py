#!/usr/bin/env python3
"""
post_publish_enricher.py — 記事公開後の構造自動補完

公開直後の記事に対して以下を自動挿入する:
  1. 3行まとめ (kpj-summary)  — article_summarizer.py
  2. アーティストプロフィール (kpj-artist-profile) — artist_profile_inserter.py
  3. サムネサイズ検証（GRADIENT_FAIL検出時はログ警告）

Usage:
  # 単一記事
  python3 pipeline/post_publish_enricher.py --post-id 3952

  # 直近N時間以内の全記事
  python3 pipeline/post_publish_enricher.py --recent-hours 6

  # パイプラインから呼び出し
  from pipeline.post_publish_enricher import enrich_post
  result = enrich_post(post_id=3952)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "lib"))

from article_summarizer import generate_summary, insert_summary_into_html
from artist_profile_inserter import detect_artist_in_text, generate_profile_html

try:
    from gsc_indexing import notify_url_updated as _idx_notify
except Exception:
    _idx_notify = None

LOGS = BASE / "logs"
JST = timezone(timedelta(hours=9))

# YouTube Data API key (optional — used for placeholder resolution)
YOUTUBE_API_KEY = None
try:
    from dotenv import load_dotenv
    load_dotenv(BASE / ".env")
    import os as _os_env
    YOUTUBE_API_KEY = _os_env.getenv("YOUTUBE_API_KEY", "")
except Exception:
    pass

# WP API helpers
WP_DOMAIN = "https://www.kpopjournal.tokyo"
WP_AUTH_FILE = Path.home() / ".wp_auth"


def _wp_headers() -> dict:
    """Load WP auth header from ~/.wp_auth curl config."""
    if WP_AUTH_FILE.exists():
        for line in WP_AUTH_FILE.read_text().splitlines():
            if line.strip().startswith("header"):
                # header = "Authorization: Basic xxx"
                val = line.split("=", 1)[1].strip().strip('"')
                return {"Authorization": val.split(": ", 1)[1] if ": " in val else val,
                        "Content-Type": "application/json"}
    return {}


def _log(msg: str):
    ts = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [enricher] {msg}"
    print(line)
    LOGS.mkdir(parents=True, exist_ok=True)
    with open(LOGS / "post_publish_enricher.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _fetch_post(post_id: int) -> dict | None:
    """post 取得 — context=edit で content.raw まで含めて取得 (2026-05-11修正)。
    旧実装は認証なし default view (rendered のみ) で取得し、enricher が rendered を
    そのまま raw に PUT し直すため wpautop 二重適用で <p> が壊れる事故が頻発していた
    (post 21006 等)。
    """
    import requests
    headers = _wp_headers() or {}
    try:
        resp = requests.get(
            f"{WP_DOMAIN}/wp-json/wp/v2/posts/{post_id}",
            params={"_fields": "id,slug,title,content,featured_media,categories", "context": "edit"},
            headers=headers,
            timeout=15,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        _log(f"WARN: fetch post {post_id} failed: {e}")
    return None


def _fetch_related_by_category(post_id: int, categories: list[int], count: int = 3,
                               title: str = '') -> list[dict]:
    """同アーティスト優先 → 同カテゴリの関連記事をcount件取得（サムネ付き）"""
    import requests
    results = []

    # 1. タイトルからアーティストを検出し、同アーティスト記事を優先取得
    if title:
        try:
            from lib.article_topic_classifier import classify
            c = classify(title)
            subjects = c.get('subjects', [])
            if subjects:
                # アーティスト名で検索
                resp = requests.get(
                    f"{WP_DOMAIN}/wp-json/wp/v2/posts",
                    params={
                        "search": subjects[0],
                        "exclude": post_id,
                        "per_page": count,
                        "orderby": "date",
                        "order": "desc",
                        "status": "publish",
                        "_fields": "id,title,link,featured_media,_links",
                        "_embed": "wp:featuredmedia",
                    },
                    timeout=15,
                )
                if resp.status_code == 200:
                    posts = resp.json()
                    for p in posts:
                        if not isinstance(p, dict):
                            continue
                        thumb_url = ''
                        try:
                            embedded = p.get('_embedded', {}).get('wp:featuredmedia', [])
                            if embedded:
                                sizes = embedded[0].get('media_details', {}).get('sizes', {})
                                thumb_url = (sizes.get('thumbnail', {}).get('source_url', '')
                                           or sizes.get('medium', {}).get('source_url', '')
                                           or embedded[0].get('source_url', ''))
                        except Exception:
                            pass
                        results.append({
                            "title": p["title"]["rendered"],
                            "url": p["link"],
                            "thumbnail": thumb_url,
                        })
        except Exception:
            pass

    # 1b. アーティスト検索0件の場合: タイトルキーワードで検索フォールバック
    if len(results) == 0 and title:
        try:
            import re as _re
            # タイトルから主要キーワードを抽出（アーティスト名以外も）
            keywords = _re.findall(r'[\w]{2,}', title)
            # 最も特徴的なキーワードで検索（短い一般語を除外）
            search_kws = [k for k in keywords if len(k) >= 3 and k not in ('速報', '完全', 'ガイド', '2026', '最新')][:2]
            if search_kws:
                search_q = ' '.join(search_kws)
                resp = requests.get(
                    f"{WP_DOMAIN}/wp-json/wp/v2/posts",
                    params={
                        "search": search_q,
                        "exclude": post_id,
                        "per_page": count,
                        "orderby": "relevance",
                        "status": "publish",
                        "_fields": "id,title,link,featured_media,_links",
                        "_embed": "wp:featuredmedia",
                    },
                    timeout=15,
                )
                if resp.status_code == 200:
                    existing_urls = {r['url'] for r in results}
                    for p in resp.json():
                        if len(results) >= count:
                            break
                        if not isinstance(p, dict) or p.get('link', '') in existing_urls:
                            continue
                        thumb_url = ''
                        try:
                            embedded = p.get('_embedded', {}).get('wp:featuredmedia', [])
                            if embedded:
                                sizes = embedded[0].get('media_details', {}).get('sizes', {})
                                thumb_url = (sizes.get('thumbnail', {}).get('source_url', '')
                                           or embedded[0].get('source_url', ''))
                        except Exception:
                            pass
                        results.append({
                            "title": p["title"]["rendered"],
                            "url": p["link"],
                            "thumbnail": thumb_url,
                        })
        except Exception:
            pass

    # 2. 不足分をカテゴリベースで補完（cat 1,2は汎用すぎるのでスキップ）
    if len(results) < count and categories:
        meaningful = [c for c in categories if c not in (1, 2)]
        if not meaningful:
            return results  # cat 1,2のみの場合はキーワード検索結果で十分
        cat_id = meaningful[0]
        existing_urls = {r['url'] for r in results}
        try:
            resp = requests.get(
                f"{WP_DOMAIN}/wp-json/wp/v2/posts",
                params={
                    "categories": cat_id,
                    "exclude": post_id,
                    "per_page": count * 2,
                    "orderby": "date",
                    "order": "desc",
                    "status": "publish",
                    "_fields": "id,title,link,featured_media,_links",
                    "_embed": "wp:featuredmedia",
                },
                timeout=15,
            )
            if resp.status_code == 200:
                for p in resp.json():
                    if len(results) >= count:
                        break
                    if not isinstance(p, dict) or p.get('link', '') in existing_urls:
                        continue
                    thumb_url = ''
                    try:
                        embedded = p.get('_embedded', {}).get('wp:featuredmedia', [])
                        if embedded:
                            sizes = embedded[0].get('media_details', {}).get('sizes', {})
                            thumb_url = (sizes.get('thumbnail', {}).get('source_url', '')
                                       or sizes.get('medium', {}).get('source_url', '')
                                       or embedded[0].get('source_url', ''))
                    except Exception:
                        pass
                    results.append({
                        "title": p["title"]["rendered"],
                        "url": p["link"],
                        "thumbnail": thumb_url,
                    })
        except Exception as e:
            _log(f"WARN: related fetch failed (cat={cat_id}): {e}")

    return results[:count]


def _build_related_widget(related: list[dict]) -> str:
    """関連記事ウィジェットHTML（related-articlesと同一形式）"""
    if not related:
        return ""
    items = "".join(
        f'<li><a href="{a["url"]}">{a["title"]}</a></li>'
        for a in related[:4]
    )
    return (
        '\n<section class="related-articles" aria-label="関連記事">'
        '<h2>あわせて読みたい</h2>'
        f'<ul>{items}</ul>'
        '</section>\n'
    )


def _update_post_content(post_id: int, content: str) -> bool:
    import requests
    headers = _wp_headers()
    if not headers:
        _log("ERROR: WP auth not available")
        return False
    try:
        resp = requests.post(
            f"{WP_DOMAIN}/wp-json/wp/v2/posts/{post_id}",
            headers=headers,
            json={"content": content},
            timeout=30,
        )
        return resp.status_code == 200
    except Exception as e:
        _log(f"ERROR: update post {post_id} failed: {e}")
        return False


def _update_post_title(post_id: int, title: str) -> bool:
    import requests
    headers = _wp_headers()
    if not headers:
        return False
    try:
        resp = requests.post(
            f"{WP_DOMAIN}/wp-json/wp/v2/posts/{post_id}",
            headers=headers,
            json={"title": title},
            timeout=30,
        )
        return resp.status_code == 200
    except Exception as e:
        _log(f"ERROR: update title post {post_id} failed: {e}")
        return False


def _check_thumbnail_size(featured_media: int) -> tuple[str, int]:
    """Check thumbnail file size. Returns (verdict, size_bytes)."""
    if not featured_media:
        return "NO_THUMB", 0
    import requests
    try:
        m = requests.get(f"{WP_DOMAIN}/wp-json/wp/v2/media/{featured_media}", timeout=10).json()
        url = m.get("source_url", "")
        if not url:
            return "NO_URL", 0
        head = requests.head(url, timeout=5)
        size = int(head.headers.get("content-length", 0))
        if size >= 50000:
            return "PASS", size
        elif size >= 10000:
            return "NEEDS_V6_REPLACE", size
        else:
            return "GRADIENT_FAIL", size
    except Exception:
        return "CHECK_FAILED", 0


def _check_thumbnail_quality(image_url: str) -> tuple[bool, str]:
    """Download thumbnail and check for v6 violations (dark bg / text burn-in).
    Returns (is_violation, reason).
    """
    try:
        from PIL import Image
        import numpy as np
        import io
        import requests as _req
    except ImportError:
        return False, "PIL/numpy not installed"

    try:
        resp = _req.get(image_url, timeout=10)
        img = Image.open(io.BytesIO(resp.content)).convert("RGB")
        arr = np.array(img)
    except Exception as e:
        return False, f"image load failed: {e}"

    mean_brightness = float(arr.mean())
    if mean_brightness < 55:
        return True, f"dark_bg(brightness={mean_brightness:.0f})"

    h = arr.shape[0]
    bottom = arr[int(h * 0.66):, :, :]
    bottom_mean = float(bottom.mean())
    if abs(bottom_mean - mean_brightness) > 80:
        return True, f"text_band(bottom={bottom_mean:.0f},full={mean_brightness:.0f})"

    std_val = float(arr.std())
    if std_val < 20:
        return True, f"flat_color(std={std_val:.0f})"

    return False, "ok"


def _resolve_visual_placeholders(html: str) -> tuple[str, list[str]]:
    """Resolve <!-- MAP: ... --> and <!-- YOUTUBE: ... --> placeholders in HTML.

    Returns (modified_html, list_of_changes).
    <!-- IMAGE: ... --> placeholders are left as-is for future DALL-E integration.
    """
    changes: list[str] = []

    # --- Google Maps embed ---
    def _replace_map(m):
        venue_info = m.group(1).strip()
        # URL-encode the query for Google Maps embed
        import urllib.parse
        query = urllib.parse.quote_plus(venue_info)
        iframe = (
            f'<div class="kpj-map-embed" style="margin:20px 0;">'
            f'<iframe src="https://www.google.com/maps?q={query}&output=embed" '
            f'width="100%" height="350" style="border:0;border-radius:8px;" '
            f'allowfullscreen="" loading="lazy" '
            f'referrerpolicy="no-referrer-when-downgrade"></iframe>'
            f'<p style="font-size:12px;color:#888;margin-top:4px;">'
            f'{venue_info}</p></div>'
        )
        changes.append(f"map_embed({venue_info[:30]})")
        return iframe

    html = re.sub(r'<!--\s*MAP:\s*(.+?)\s*-->', _replace_map, html)

    # --- YouTube embed ---
    def _replace_youtube(m):
        query = m.group(1).strip()
        video_id = _search_youtube(query)
        if video_id:
            iframe = (
                f'<div class="kpj-youtube-embed" style="margin:20px 0;">'
                f'<div style="position:relative;padding-bottom:56.25%;height:0;overflow:hidden;border-radius:8px;">'
                f'<iframe src="https://www.youtube.com/embed/{video_id}" '
                f'style="position:absolute;top:0;left:0;width:100%;height:100%;" '
                f'frameborder="0" allow="accelerometer; autoplay; clipboard-write; '
                f'encrypted-media; gyroscope; picture-in-picture" allowfullscreen '
                f'loading="lazy"></iframe></div></div>'
            )
            changes.append(f"youtube_embed({query[:30]})")
            return iframe
        # If search fails, leave a visible link instead
        search_url = f"https://www.youtube.com/results?search_query={__import__('urllib.parse', fromlist=['quote_plus']).quote_plus(query)}"
        fallback = (
            f'<div class="kpj-youtube-fallback" style="margin:20px 0;padding:16px;'
            f'background:#f8f4ff;border-radius:8px;text-align:center;">'
            f'<a href="{search_url}" target="_blank" rel="noopener" '
            f'style="color:#FF1493;font-weight:600;">YouTubeで「{query}」を検索</a></div>'
        )
        changes.append(f"youtube_fallback({query[:30]})")
        return fallback

    html = re.sub(r'<!--\s*YOUTUBE:\s*(.+?)\s*-->', _replace_youtube, html)

    return html, changes


def _search_youtube(query: str) -> str | None:
    """Search YouTube Data API v3 for a video ID. Returns None on failure."""
    if not YOUTUBE_API_KEY:
        return None
    import urllib.parse
    import urllib.request
    try:
        params = urllib.parse.urlencode({
            "part": "snippet",
            "q": query,
            "type": "video",
            "maxResults": 1,
            "key": YOUTUBE_API_KEY,
        })
        url = f"https://www.googleapis.com/youtube/v3/search?{params}"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        resp = json.loads(urllib.request.urlopen(req, timeout=10).read())
        items = resp.get("items", [])
        if items:
            return items[0]["id"]["videoId"]
    except Exception as e:
        _log(f"YouTube search error for '{query}': {e}")
    return None


def enrich_post(post_id: int) -> dict:
    """Enrich a single post with summary + profile if missing."""
    result = {"post_id": post_id, "changes": [], "status": "ok"}

    post = _fetch_post(post_id)
    if not post:
        result["status"] = "fetch_failed"
        return result

    title = post.get("title", {}).get("rendered", "")
    # content は raw 優先 — rendered を読んで PUT すると wpautop 二重適用で <p> が壊れる
    # (2026-05-11: pid 21006 ほか「<p> open=12 close=9 (差分-3)」事故の真因)
    content_obj = post.get("content", {})
    content = content_obj.get("raw") or content_obj.get("rendered", "")
    featured_media = post.get("featured_media", 0)

    modified = content
    changes = []

    # 1. Summary
    if "kpj-summary" not in content:
        summary_html = generate_summary(content)
        modified = insert_summary_into_html(modified, summary_html)
        changes.append("summary_added")

    # 2. Profile — (廃止 2026-05-26) 本文末への生プロフィール表(kpj-artist-profile)
    # 注入を停止。オーナー指摘[3]「プロフィールはボタンで圧縮」。プロフィール導線は
    # テンプレ側 .kpop-idol-wiki-link CTA(表示時に idol_artist へのボタンを出す)に
    # 一任し、本文へ焼き付けない(長い dl 表が記事末を圧迫していた)。

    # 3. Thumbnail check
    thumb_verdict, thumb_size = _check_thumbnail_size(featured_media)
    if thumb_verdict not in ("PASS", "NO_THUMB"):
        changes.append(f"thumb_warn({thumb_verdict},{thumb_size}B)")
        _log(f"WARN: post {post_id} thumbnail {thumb_verdict} ({thumb_size}B)")

    # 3b. Thumbnail quality check + auto-regen via DALL-E
    if featured_media:
        try:
            import requests as _req
            _media_r = _req.get(f"{WP_DOMAIN}/wp-json/wp/v2/media/{featured_media}", params={"_fields": "source_url"}, timeout=15)
            thumb_url = _media_r.json().get("source_url", "") if _media_r.status_code == 200 else ""
            if thumb_url:
                violation, reason = _check_thumbnail_quality(thumb_url)
                if violation:
                    _log(f"THUMB_VIOLATION: post {post_id} — {reason}, attempting DALL-E regen")
                    import subprocess
                    regen = subprocess.run(
                        ["python3", "/home/aiuser/kpop-ai-system/tools/regenerate_thumbnail_wp.py", str(post_id)],
                        capture_output=True, text=True, timeout=120,
                    )
                    if "featured_media: OK" in regen.stdout or "featured_media updated" in regen.stdout:
                        changes.append("thumb_dalle_regen")
                    else:
                        changes.append(f"thumb_regen_failed({reason})")
        except Exception as e:
            _log(f"thumb_quality_check error: {e}")

    # 2b. Related articles widget — 無効化
    # Next.js側の RelatedArticles コンポーネントが4カラムグリッドで
    # 関連記事を表示するため、WPコンテンツへの書き込みは不要。
    # (旧コード: _build_related_widget → kpj-related-widget / related-articles セクション挿入)

    # 4b. Resolve visual placeholders (MAP / YOUTUBE embeds)
    if "<!-- MAP:" in modified or "<!-- YOUTUBE:" in modified:
        resolved_html, visual_changes = _resolve_visual_placeholders(modified)
        if visual_changes:
            modified = resolved_html
            changes.extend(visual_changes)

    # サムネ品質ゲート: regen失敗時はdraft化 (2026-05-01追加)
    thumb_failed = any(c.startswith("thumb_regen_failed") for c in changes)
    if thumb_failed:
        _log(f"THUMB_BLOCK: post {post_id} サムネ再生成失敗→draft化")
        try:
            import requests as _req_draft
            _req_draft.post(
                f"{WP_DOMAIN}/wp-json/wp/v2/posts/{post_id}",
                headers=_wp_headers(),
                json={"status": "draft"},
                timeout=15,
            )
            result["status"] = "thumb_draft"
            changes.append("draft_for_thumb_failure")
        except Exception as e:
            _log(f"draft化失敗: {e}")

    # 4c. 【速報】ラベル除去（公開から6h以上経過した速報タイトル）
    if "【速報】" in title:
        pub_date_str = post.get("date", "")
        try:
            pub_date = datetime.fromisoformat(pub_date_str.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            if (now - pub_date).total_seconds() > 6 * 3600:
                new_title = title.replace("【速報】", "").strip()
                _update_post_title(post_id, new_title)
                changes.append("sokuho_label_removed")
                _log(f"TITLE_FIX: post {post_id} 【速報】除去 (6h経過)")
        except Exception:
            pass

    # Apply changes
    has_content_changes = any(c.startswith(("summary_", "profile_", "related_", "map_embed", "youtube_embed", "youtube_fallback")) for c in changes)
    if has_content_changes:
        ok = _update_post_content(post_id, modified)
        if ok:
            _log(f"OK: post {post_id} enriched: {', '.join(changes)}")
        else:
            result["status"] = "update_failed"
            _log(f"FAIL: post {post_id} update failed")
    else:
        _log(f"SKIP: post {post_id} already complete (thumb={thumb_verdict})")

    # 4. Lead structure validation (Phase 10)
    lead_ok, lead_issues = _validate_lead_structure(content)
    if not lead_ok:
        changes.append(f"lead_warn({'; '.join(lead_issues[:2])})")

    # 5. GSC Indexing API 通知
    if _idx_notify is not None:
        try:
            slug = post.get("slug", "")
            if slug:
                post_url = f"https://www.kpopjournal.tokyo/{slug}/"
                idx_r = _idx_notify(post_url)
                if idx_r.get("status") == "ok":
                    changes.append("gsc_indexed")
                    _log(f"GSC Indexing OK: {post_url}")
                else:
                    changes.append(f"gsc_idx_{idx_r.get('status', 'err')}")
                    _log(f"GSC Indexing {idx_r.get('status')}: {post_url} — {idx_r.get('response', {}).get('error', '')[:100]}")
        except Exception as e:
            _log(f"GSC Indexing error: {e}")

    result["changes"] = changes
    return result


def _validate_lead_structure(content_html: str) -> tuple:
    """記事冒頭3段落がリード文構造 (5W1H→背景→重要性) かを検証。"""
    pre_h2 = content_html.split("<h2", 1)[0] if "<h2" in content_html else content_html
    paras = re.findall(r"<p[^>]*>(.*?)</p>", pre_h2, re.DOTALL)
    paras_text = [re.sub(r"<[^>]+>", "", p).strip() for p in paras]
    paras_text = [p for p in paras_text if len(p) > 20]

    issues: list[str] = []
    if len(paras_text) < 3:
        issues.append(f"リード文{len(paras_text)}段落(3段落必須)")
        return False, issues

    p1 = paras_text[0]
    has_who = bool(re.search(r"[A-Z][A-Z]+|[ぁ-んァ-ヶ一-龠]{2,}(?:は|が|、)", p1))
    has_when = bool(re.search(r"\d+月|\d+日|\d+年|本日|今週|先週", p1))
    if not (has_who and has_when):
        issues.append("第1段落の5W1H要素不足")

    if len(paras_text[1]) < 40:
        issues.append("第2段落が短い(背景不足)")

    if not re.search(r"重要|初|史上|記録|最大|注目|意味|背景", paras_text[2]):
        issues.append("第3段落に重要性表現不足")

    return len(issues) == 0, issues


def enrich_recent(hours: int = 6) -> list[dict]:
    """Enrich all posts published within the last N hours."""
    import requests
    cutoff = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S")
    try:
        resp = requests.get(
            f"{WP_DOMAIN}/wp-json/wp/v2/posts",
            params={"after": cutoff, "per_page": 50, "_fields": "id"},
            timeout=15,
        )
        posts = resp.json() if resp.status_code == 200 else []
    except Exception:
        posts = []

    results = []
    for p in posts:
        r = enrich_post(p["id"])
        results.append(r)
    return results


def main():
    parser = argparse.ArgumentParser(description="記事公開後の構造自動補完")
    parser.add_argument("--post-id", type=int, help="特定の記事IDを処理")
    parser.add_argument("--recent-hours", type=int, default=2, help="直近N時間以内の記事を一括処理 (default: 2)")
    args = parser.parse_args()

    if args.post_id:
        result = enrich_post(args.post_id)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        hours = args.recent_hours
        results = enrich_recent(hours)
        for r in results:
            print(json.dumps(r, ensure_ascii=False))
        print(f"\nTotal: {len(results)} posts processed")


if __name__ == "__main__":
    main()
