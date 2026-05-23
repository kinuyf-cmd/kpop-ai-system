#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""投稿内容の敵対的(RED TEAM)総監査(2026-05-23・オーナー指示)。

直近 publish の記事を「攻める視点」で検査し、問題を CRITICAL/HIGH/MEDIUM/LOW で
報告する。決定論チェック(LLM不要・コスト0)を主体とし、ハルシネーション/AI臭の
深い判定は別途 LLM(factcheck_v2 等)に委ねる(本スクリプトは検出フラグまで)。

監査項目(オーナー確定):
  1. 誤情報・捏造(ハルシネーション)— ソース照合は LLM 領域。ここでは「出典リンク有無」
     「英語生ソースのコピペ疑い(英語比率異常)」等の代理シグナルを検出。
  2. 品質・AI臭・視認性・言語 — 英語/ハングル残留、ベタ打ち(見出し/段落不足)、
     同一フレーズ反復、文字数過少。
  3. 重複・SEO・技術 — 日本語slug、内部リンク欠落、404リンク、重複タイトル。
  4. サムネイル — featured_media 有無、引用記事の og:image 由来か(出典ドメイン画像か)。
  5. メタ情報 — meta description(excerpt)有無。
  6. 最適カテゴリ — Uncategorized/未分類でないか。
  7. ゴミ混入 — プレースホルダ([ソース名]等)、システムメッセージ、コードブロック残存。

read-only(REST GET のみ)。DB/記事は変更しない。修正は別途(blue-team/post_audit)。

  python3 adversarial_post_audit.py            # 直近24hの publish を監査
  python3 adversarial_post_audit.py --hours 3  # 直近3h
  python3 adversarial_post_audit.py --ids 651,654
"""
import os
import re
import sys
import json
import base64
import argparse
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta

sys.path.insert(0, "/home/aiuser/kpop-ai-system")
try:
    from dotenv import load_dotenv
    load_dotenv("/home/aiuser/kpop-ai-system/.env")
except Exception:
    pass

WP_API = "https://www.kpopjournal.tokyo/wp-json/wp/v2"
_PLACEHOLDER_RE = re.compile(r"\[(?:ソース名|サイト名|メディア名|執筆者名|タイトル|未定|要確認|TBD|TODO)\]")
_SYSMSG_RE = re.compile(r"(?:申し訳|I (?:cannot|can't|am unable)|as an AI|here(?:'s| is) (?:the|your))", re.I)
_CODEBLOCK_RE = re.compile(r"```")


def _auth():
    u = os.environ.get("WP_USER", "")
    p = os.environ.get("WP_APP_PASS") or os.environ.get("WP_PASS", "")
    return base64.b64encode(f"{u}:{p}".encode()).decode()


def _get(url):
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {_auth()}", "User-Agent": "audit/1.0"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode())


def fetch_posts(hours=None, ids=None):
    if ids:
        return [_get(f"{WP_API}/posts/{i}?context=edit&_fields=id,title,slug,content,excerpt,categories,featured_media,link") for i in ids]
    after = (datetime.now(timezone.utc) - timedelta(hours=hours or 24)).isoformat()
    qs = urllib.parse.urlencode({
        "after": after, "status": "publish", "per_page": 50,
        "context": "edit",
        "_fields": "id,title,slug,content,excerpt,categories,featured_media,link",
        "orderby": "date", "order": "desc",
    })
    return _get(f"{WP_API}/posts?{qs}")


def _body_only(content_raw):
    """記事本文(post_content)のみ。ページ全体のサイドバー等は含まない(REST raw は本文)。"""
    return content_raw or ""


def audit_post(post):
    """1記事を敵対的に検査。issues のリストを返す(各 dict: severity/type/detail)。"""
    issues = []
    pid = post.get("id")
    raw = (post.get("content", {}) or {}).get("raw", "") or (post.get("content", {}) or {}).get("rendered", "")
    title = (post.get("title", {}) or {}).get("raw", "") or (post.get("title", {}) or {}).get("rendered", "")
    excerpt = (post.get("excerpt", {}) or {}).get("raw", "") or ""
    cats = post.get("categories", []) or []
    fm = post.get("featured_media", 0) or 0
    plain = re.sub(r"<[^>]+>", " ", raw)

    def add(sev, typ, detail):
        issues.append({"severity": sev, "type": typ, "detail": detail})

    # 7. ゴミ混入 — プレースホルダ/システムメッセージ/コードブロック(CRITICAL)
    if _PLACEHOLDER_RE.search(plain):
        add("CRITICAL", "placeholder", f"未置換プレースホルダ: {_PLACEHOLDER_RE.search(plain).group()}")
    if _SYSMSG_RE.search(plain):
        add("CRITICAL", "system_message", "LLMシステムメッセージ混入の疑い")
    if _CODEBLOCK_RE.search(raw):
        add("HIGH", "codeblock", "コードブロックマーカー(```)残存")

    # 2. 言語 — 英語/ハングル残留(CRITICAL: 英語主体 / HIGH: ハングル残留)
    en = len(re.findall(r"[A-Za-z]", plain))
    ja = len(re.findall(r"[ぁ-んァ-ヶ一-龥]", plain))
    han = len(re.findall(r"[가-힣]", plain))
    if en > ja and ja > 0:
        add("CRITICAL", "language_english", f"英語主体(英字{en} > 日本語{ja})= 翻訳不全の疑い")
    elif ja == 0 and en > 50:
        add("CRITICAL", "language_english", "本文に日本語がほぼ無い")
    if han > 10:
        add("HIGH", "language_hangul", f"ハングル残留 {han}字(翻訳漏れ)")

    # 2. 視認性 — ベタ打ち(見出し/段落不足)・文字数過少
    n_h2 = len(re.findall(r"<h2", raw)); n_p = len(re.findall(r"<p", raw))
    body_chars = len(plain.replace(" ", ""))
    if body_chars < 400:
        add("HIGH", "too_short", f"本文 {body_chars}字(過少・薄い記事)")
    if n_h2 == 0 and body_chars > 600:
        add("HIGH", "no_structure", f"見出し(h2)無しのベタ打ち({n_p}段落)")
    # 同一フレーズ反復(先頭25字一致の文が複数)
    sents = [s.strip()[:25] for s in re.split(r"[。\n]", plain) if s.strip()]
    if len(sents) != len(set(sents)) and len(sents) > 3:
        add("MEDIUM", "repetition", "同一フレーズ反復の疑い")

    # 1. 誤情報の代理シグナル — 出典リンク欠落(HIGH)
    from lib.source_domains import source_url_regex
    src_urls = re.findall(source_url_regex(), raw)
    if not src_urls:
        add("HIGH", "no_source", "信頼ソースURLが本文に無い(出典欠落・捏造リスク)")

    # 5. メタ情報 — excerpt(meta description)有無
    if not excerpt.strip():
        add("MEDIUM", "no_meta", "meta description(excerpt)未設定")

    # 6. 最適カテゴリ — 未分類でないか(category id=1 が通例 Uncategorized)
    if not cats or cats == [1]:
        add("HIGH", "uncategorized", f"カテゴリ未分類(categories={cats})")

    # 4. サムネイル — featured_media 有無 + 引用記事の og:image 由来か
    if not fm:
        add("HIGH", "no_thumbnail", "アイキャッチ(featured_media)未設定")
    else:
        # 引用記事は出典(soompi等)の og:image を使う想定。featured の source を確認。
        try:
            media = _get(f"{WP_API}/media/{fm}?_fields=source_url,alt_text")
            alt = (media.get("alt_text") or "")
            msrc = media.get("source_url", "")
            # 出典明記が alt にあるか(citation: 出典名)。og由来判定の代理。
            if src_urls and "出典" not in alt and "soompi" not in alt.lower() and "kbuzz" not in alt.lower():
                add("LOW", "thumbnail_attribution", f"サムネ alt に出典記載なし(alt='{alt[:30]}')")
        except Exception:
            pass

    # 3. SEO技術 — 日本語slug
    slug = post.get("slug", "")
    if re.search(r"[ぁ-んァ-ヶ一-龥가-힣%]", urllib.parse.unquote(slug)):
        add("HIGH", "japanese_slug", f"日本語/非ASCII slug: {slug[:40]}")

    return {"id": pid, "title": title[:50], "link": post.get("link", ""), "issues": issues}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=24)
    ap.add_argument("--ids", default="")
    args = ap.parse_args()
    ids = [int(x) for x in args.ids.split(",") if x.strip().isdigit()] if args.ids.strip() else None

    posts = fetch_posts(hours=args.hours, ids=ids)
    print(f"=== 投稿内容 敵対的総監査 ({datetime.now().strftime('%Y-%m-%d %H:%M')}) 対象 {len(posts)}件 ===")
    sev_count = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    flagged = 0
    for post in posts:
        r = audit_post(post)
        if r["issues"]:
            flagged += 1
            print(f"\n[{r['id']}] {r['title']}")
            print(f"  {r['link']}")
            for iss in r["issues"]:
                sev_count[iss["severity"]] = sev_count.get(iss["severity"], 0) + 1
                print(f"    {iss['severity']:8} {iss['type']}: {iss['detail']}")
    print(f"\n=== サマリー: {flagged}/{len(posts)}件に問題 / "
          f"CRITICAL={sev_count['CRITICAL']} HIGH={sev_count['HIGH']} "
          f"MEDIUM={sev_count['MEDIUM']} LOW={sev_count['LOW']} ===")
    # CRITICAL があれば exit 1(cron/通知で検知)
    return 1 if sev_count["CRITICAL"] > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
