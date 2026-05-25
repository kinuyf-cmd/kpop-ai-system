#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""webp_stage.py — 本番公開URLから自社画像を取得し WebP に変換、uploads相対パスで staging する。
www-data に PIL/cwebp が無く /var/www も書けない制約への対応:
  aiuser(Pillow有・公開URL読める)が変換まで行い、owner は staging を uploads へコピーするだけ。

入力: 対象URL一覧(--from-sitemap で本番sitemap全URLを巡回しimg収集 / --url 個別 / 既定=home+主要)
変換: PNG/JPG → 同名 .webp(quality=82, method=6)。出力は uploads 相対パスを保ったツリー。
出力: tools/perf/webp_stage/wp-content/uploads/.../<name>.webp
適用(owner): sudo cp -rn tools/perf/webp_stage/wp-content/uploads/. /var/www/wp_stg/wp-content/uploads/
            sudo chown -R www-data:www-data /var/www/wp_stg/wp-content/uploads
使い方: python3 tools/perf/webp_stage.py --from-sitemap
"""
import sys, os, re, json, time, argparse, urllib.request, urllib.parse
from io import BytesIO
from pathlib import Path
from PIL import Image

BASE = Path(__file__).resolve().parents[2]
STAGE = BASE / "tools" / "perf" / "webp_stage"
SITE = "https://www.kpopjournal.tokyo"
UA = {"User-Agent": "KpopJournalBot/1.0 perf-optimize"}
IMG_RE = re.compile(r'https://www\.kpopjournal\.tokyo/wp-content/uploads/[^"\'\) ]+\.(?:png|jpe?g)', re.I)

def fetch(url, timeout=30):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()

def page_urls_from_sitemap():
    urls = set()
    try:
        sm = fetch(f"{SITE}/sitemap.xml").decode("utf-8", "replace")
    except Exception as e:
        print(f"[warn] sitemap取得失敗 {e}; homeのみ", file=sys.stderr); return [SITE + "/"]
    # AIOSEO は <loc><![CDATA[url]]></loc>。CDATA と素の両対応。sitemap index→子も辿る。
    loc_re = re.compile(r"<loc>\s*(?:<!\[CDATA\[)?\s*([^<\]]+?)\s*(?:\]\]>)?\s*</loc>", re.I)
    all_locs = loc_re.findall(sm)
    subs = [u for u in all_locs if u.endswith(".xml")]
    locs = [u for u in all_locs if not u.endswith(".xml")]
    for s in subs:
        try:
            sub = fetch(s).decode("utf-8", "replace")
            locs += [u for u in loc_re.findall(sub) if not u.endswith(".xml")]
            time.sleep(0.2)
        except Exception:
            pass
    for u in locs:
        if u.endswith(".xml"): continue
        urls.add(u)
    urls.add(SITE + "/")
    return sorted(urls)

def collect_images(pages):
    imgs = set()
    for i, p in enumerate(pages):
        try:
            html = fetch(p).decode("utf-8", "replace")
            for m in IMG_RE.findall(html):
                imgs.add(m)
        except Exception as e:
            print(f"[warn] {p}: {e}", file=sys.stderr)
        if i % 10 == 0:
            print(f"  巡回 {i+1}/{len(pages)} … 画像 {len(imgs)}", file=sys.stderr)
        time.sleep(0.3)
    return sorted(imgs)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-sitemap", action="store_true", help="sitemap全URLから画像収集")
    ap.add_argument("--url", action="append", help="個別ページURL")
    ap.add_argument("-q", type=int, default=82)
    args = ap.parse_args()

    if args.from_sitemap:
        pages = page_urls_from_sitemap()
    elif args.url:
        pages = args.url
    else:
        pages = [SITE + "/", SITE + "/artists/"]
    print(f"対象ページ {len(pages)}", file=sys.stderr)
    imgs = collect_images(pages)
    print(f"自社画像 {len(imgs)} 件 → WebP変換", file=sys.stderr)

    conv = skip = err = 0
    tb = ta = 0
    for u in imgs:
        rel = urllib.parse.urlparse(u).path.lstrip("/")  # wp-content/uploads/...
        out = STAGE / (rel.rsplit(".", 1)[0] + ".webp")
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.exists():
            skip += 1; continue
        try:
            data = fetch(u)
            im = Image.open(BytesIO(data)).convert("RGB")
            im.save(out, "WEBP", quality=args.q, method=6)
            tb += len(data); ta += out.stat().st_size; conv += 1
        except Exception as e:
            print(f"[err] {u}: {e}", file=sys.stderr); err += 1
        time.sleep(0.2)

    pct = 100 - ta * 100 // max(tb, 1)
    print(f"\n変換 {conv} / skip {skip} / err {err}")
    print(f"元 {tb//1024}KB → WebP {ta//1024}KB  削減 {pct}% ({(tb-ta)//1024}KB)")
    print(f"staging: {STAGE}")
    print("適用(owner): sudo cp -rn tools/perf/webp_stage/wp-content/uploads/. /var/www/wp_stg/wp-content/uploads/ "
          "&& sudo chown -R www-data:www-data /var/www/wp_stg/wp-content/uploads")

if __name__ == "__main__":
    main()
