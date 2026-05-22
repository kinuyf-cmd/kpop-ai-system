#!/usr/bin/env python3
"""M-final: 本番静的サイトの救出記事を stg WP に DRAFT インポートする。

本番 /var/www/kpopjournal_site/<slug>/index.html から本文/タイトル/メタ/カテゴリを
抽出し、stg WP に wp-cli 経由で post を作成する。

- 取り込み元 = 本番静的HTML(完成形・テーマ適用済の本文を持つ)
- slug = ディレクトリ名。事故由来の異常slugは SLUG_OVERRIDE で正規化
- category = 本番HTMLの og:image サムネ種別 + CSV から推定 → stg カテゴリにマッピング
- 既存 stg 記事(タイトル一致)はスキップ(重複回避)
- 既定は --dry-run(wp-cli を実行せず計画を出力)。--apply で実投入(sudo必須)

使い方:
    python3 import_recovered_to_stg.py --dry-run            # 全49件の計画
    python3 import_recovered_to_stg.py --dry-run --slugs A,B # 指定slugのみ
    sudo python3 import_recovered_to_stg.py --apply --slugs A,B  # 実投入(サンプル)
"""
import argparse
import csv
import html
import os
import re
import subprocess
import sys

PROD_ROOT = "/var/www/kpopjournal_site"
WP_PATH = "/var/www/wp_stg"
CSV_PATH = "/home/aiuser/.kpop_recovery/recovered_articles.csv"

# 事故由来の異常slug → 正規化(build_static_site.py の SLUG_OVERRIDE と整合)
SLUG_OVERRIDE = {
    "13-20260413": "top-13years-arirang-release-2026",
    "6-3-bts-20260413": "bts-comeback-3days-2026",
    "aespa-4-20260413": "aespa-4th-gen-first-dome-2026",
    "bts-641-000-3-1-20260413": "bts-arirang-641k-3weeks-no1-2026",
}

# カテゴリ(本番側 news/chart/guide/comeback/beauty/live)→ stg カテゴリ slug
CAT_MAP = {
    "news": "news", "chart": "chart", "guide": "guide",
    "comeback": "comeback", "beauty": "beauty", "live": "live",
}


def load_csv_meta():
    """title(正規化キー) -> {category, posted_at} を返す。"""
    meta = {}
    if os.path.exists(CSV_PATH):
        for r in csv.DictReader(open(CSV_PATH, encoding="utf-8")):
            meta[_norm(r.get("title", ""))] = {
                "category": r.get("category", "news"),
                "posted_at": r.get("posted_at", ""),
            }
    return meta


def _norm(s):
    s = html.unescape(s or "")
    return re.sub(r"[\s　【】\[\]｜|・,.!?「」、。\-–—]+", "", s).lower()


def extract(slug):
    """本番静的HTML から記事データを抽出。

    article 内には本文以外に静的サイト装飾(h1/meta div/hero img/末尾の関連記事
    カード)が含まれるため、それらを除去して本文(h2以降〜関連カード手前)だけを取る。
    """
    fp = os.path.join(PROD_ROOT, slug, "index.html")
    if not os.path.exists(fp):
        return None
    h = open(fp, encoding="utf-8", errors="replace").read()
    title = re.search(r"<title>([^<]+)</title>", h, re.I)
    title = html.unescape(title.group(1)) if title else slug
    title = re.split(r"\s*[|｜]\s*KPOP", title)[0].strip()
    metad = re.search(r'<meta name="description" content="([^"]*)"', h)
    metad = html.unescape(metad.group(1)) if metad else ""

    art = re.search(r"<article[^>]*>(.*?)</article>", h, re.DOTALL)
    body = art.group(1) if art else ""
    # 公開日: <div class="meta">YYYY-MM-DD ・ …</div> から取得
    dm = re.search(r'<div class="meta">\s*(\d{4}-\d{2}-\d{2})', body)
    pub_date = dm.group(1) if dm else ""
    # 装飾の除去: 先頭の h1 / meta div / hero img
    body = re.sub(r"<h1[^>]*>.*?</h1>", "", body, flags=re.DOTALL)
    body = re.sub(r'<div class="meta">.*?</div>', "", body, flags=re.DOTALL)
    body = re.sub(r'<img class="hero"[^>]*>', "", body)
    # 末尾の関連記事ブロック(関連カード <a class="card">…)以降を切る
    body = re.split(r'<(?:div|section|aside)[^>]*class="[^"]*(?:related|cards|related-posts)[^"]*"', body)[0]
    body = re.split(r'<a class="card"', body)[0]
    # 出典/シェア等の末尾ナビが残れば <hr> 以降の関連は保持(出典は本文の一部)
    body = body.strip()
    return {"title": title, "meta": metad, "body": body, "pub_date": pub_date,
            "text_len": len(re.sub(r"<[^>]+>", "", body)), "h2": body.count("<h2")}


def stg_existing_titles():
    """stg の既存記事タイトル(正規化)集合。重複回避用。"""
    try:
        out = subprocess.run(
            ["sudo", "-u", "www-data", "wp", "--path=" + WP_PATH,
             "post", "list", "--post_type=post", "--post_status=any",
             "--field=post_title", "--format=csv"],
            capture_output=True, text=True, timeout=60)
        return {_norm(t) for t in out.stdout.splitlines() if t}
    except Exception:
        return set()


def import_one(slug, data, cat_meta, apply):
    norm_slug = SLUG_OVERRIDE.get(slug, slug)
    csv_cat = cat_meta.get(_norm(data["title"]), {}).get("category", "news")
    wp_cat = CAT_MAP.get(csv_cat, "news")
    posted = cat_meta.get(_norm(data["title"]), {}).get("posted_at", "")

    # 公開日: HTML の meta div 由来を優先、無ければ CSV posted_at(YYYY年MM月DD日)
    pub_date = data.get("pub_date", "")
    if not pub_date and posted:
        m = re.match(r"(\d{4})年(\d{2})月(\d{2})日", posted)
        if m:
            pub_date = f"{m[1]}-{m[2]}-{m[3]}"

    if not apply:
        print(f"[DRY] {norm_slug}")
        print(f"      title: {data['title'][:50]}")
        print(f"      cat={wp_cat} / 本文{data['text_len']}字 / H2={data['h2']} / meta{len(data['meta'])}字 / pub_date={pub_date or '(なし)'}")
        return "dry"

    # wp-cli で DRAFT 作成。本文は stdin(`-`)で渡す(www-data 権限非依存)。
    cmd = ["sudo", "-u", "www-data", "wp", "--path=" + WP_PATH, "post", "create", "-",
           f"--post_title={data['title']}", "--post_status=draft",
           f"--post_name={norm_slug}", "--post_type=post",
           f"--post_category={wp_cat}",
           f"--post_excerpt={data['meta']}", "--porcelain"]
    if pub_date:
        cmd.append(f"--post_date={pub_date} 12:00:00")
    r = subprocess.run(cmd, input=data["body"], capture_output=True, text=True, timeout=60)
    pid = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""
    if not pid.isdigit():
        print(f"ERR {norm_slug}: rc={r.returncode} stdout={r.stdout.strip()[:80]} stderr={r.stderr.strip()[:160]}")
        return None
    # AIOSEO メタ description を設定
    subprocess.run(
        ["sudo", "-u", "www-data", "wp", "--path=" + WP_PATH, "post", "meta", "update",
         pid, "_aioseo_description", data["meta"]],
        capture_output=True, text=True, timeout=30)
    print(f"OK  {norm_slug} -> DRAFT post ID={pid} cat={wp_cat} date={pub_date or '-'} ({data['title'][:35]})")
    return pid


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="実投入(sudo必須)")
    ap.add_argument("--dry-run", action="store_true", help="計画のみ(既定)")
    ap.add_argument("--slugs", help="対象slugをカンマ区切りで限定")
    args = ap.parse_args()
    apply = args.apply

    cat_meta = load_csv_meta()
    existing = stg_existing_titles() if apply else set()

    if args.slugs:
        slugs = [s.strip() for s in args.slugs.split(",")]
    else:
        slugs = sorted(d for d in os.listdir(PROD_ROOT)
                       if os.path.isdir(os.path.join(PROD_ROOT, d)) and d != "assets")

    done = skipped = 0
    for slug in slugs:
        data = extract(slug)
        if not data or data["text_len"] < 300:
            print(f"SKIP {slug}: 本文不足/抽出失敗")
            skipped += 1
            continue
        if apply and _norm(data["title"]) in existing:
            print(f"SKIP {slug}: stg に既存(タイトル一致)")
            skipped += 1
            continue
        import_one(slug, data, cat_meta, apply)
        done += 1
    print(f"\n=== {'投入' if apply else 'DRY計画'}: {done}件 / スキップ {skipped}件 ===")


if __name__ == "__main__":
    main()
