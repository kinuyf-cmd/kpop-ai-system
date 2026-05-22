#!/usr/bin/env python3
"""M5補完: 取り込み済み記事(アイキャッチ未設定)に汎用カテゴリpngを設定する。

既存資産を流用:
- thumbnail_media_ids.json (汎用png→media_id、既にWP登録済み 15-19)
- カテゴリ → サムネpng のマッピング(import_to_wp.py の thumb_for と整合)

取り込み済みの draft 記事(_thumbnail_id 未設定)に、カテゴリに応じた
汎用png の media_id を set-post-thumbnail する。wp-cli(sudo必須=オーナー実行)。

使い方:
    python3 set_thumbnails_imported.py --dry-run     # 計画のみ(既定、sudo不要)
    sudo python3 set_thumbnails_imported.py --apply   # 実設定
"""
import argparse
import json
import subprocess

WP_PATH = "/var/www/wp_stg"
THUMB_CACHE = "/home/aiuser/.kpop_recovery/thumbnail_media_ids.json"

# カテゴリ slug → 汎用png(thumbnail_media_ids.json のキー)
CAT_THUMB = {
    "news": "news.png", "chart": "analysis.png", "comeback": "comeback.png",
    "beauty": "beauty.png", "live": "live.png", "oshikatsu": "news.png",
    "travel": "news.png", "fashion": "beauty.png", "kdrama": "news.png",
    "popup": "news.png",
}


def wp(args, dry=False):
    cmd = ["sudo", "-u", "www-data", "wp", "--path=" + WP_PATH] + args
    if dry:
        return " ".join(cmd)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    return r.stdout.strip(), r.stderr.strip(), r.returncode


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    apply = args.apply

    cache = json.load(open(THUMB_CACHE, encoding="utf-8"))

    # 対象: draft の post で _thumbnail_id 未設定。wp-cli で一覧取得(apply時)。
    if not apply:
        print("[DRY] カテゴリ→サムネ media_id マッピング:")
        for cat, png in CAT_THUMB.items():
            mid = cache.get(png, "?")
            print(f"  {cat:10s} → {png} (media {mid})")
        print("\n[DRY] 実行時は draft の各記事のカテゴリを取得し、対応 media_id を")
        print("      wp post meta set <id> _thumbnail_id <media_id> で設定する。")
        print(f"      汎用png は既に WP登録済み(media {min(cache.values())}-{max(cache.values())})、再importなし。")
        return

    # apply: draft記事のID+カテゴリを取得
    out, err, rc = wp(["post", "list", "--post_type=post", "--post_status=draft",
                       "--field=ID", "--format=ids"])
    ids = out.split() if out else []
    done = skipped = 0
    for pid in ids:
        # 既にサムネ設定済みならスキップ
        tid, _, _ = wp(["post", "meta", "get", pid, "_thumbnail_id"])
        if tid.isdigit() and int(tid) > 0:
            skipped += 1
            continue
        # カテゴリ取得(最初の1つ)
        cats, _, _ = wp(["post", "term", "list", pid, "category",
                         "--field=slug", "--format=csv"])
        cat = (cats.splitlines()[0] if cats else "news").strip()
        png = CAT_THUMB.get(cat, "news.png")
        mid = cache.get(png)
        if not mid:
            print(f"SKIP {pid}: {png} の media_id 不明")
            skipped += 1
            continue
        o, e, rc = wp(["post", "meta", "set", pid, "_thumbnail_id", str(mid)])
        if rc == 0:
            print(f"OK  post {pid} (cat={cat}) → サムネ media {mid} ({png})")
            done += 1
        else:
            print(f"ERR post {pid}: {e[:80]}")
            skipped += 1
    print(f"\n=== サムネ設定: {done}件 / スキップ {skipped}件 ===")


if __name__ == "__main__":
    main()
