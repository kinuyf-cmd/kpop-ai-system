#!/usr/bin/env python3
"""公開記事のアイキャッチ解像度を一括スキャンする。

2026-08-20 追加。Google のモバイル検索 / Discover で大きなサムネイル表示に
なる要件は幅1200px。これを下回ると順位が取れていてもクリックされない。
発見時、imp>=300 の50記事中22本(imp合計 75,973)が1200px未満だった。

Usage:
  python3 lib/thumbnail_resolution_scan.py            # 全公開記事
  python3 lib/thumbnail_resolution_scan.py --limit 50 # 上位N件のみ
  python3 lib/thumbnail_resolution_scan.py --json     # JSON出力
"""
import argparse
import io
import json
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.thumbnail_audit import check_resolution, MIN_THUMBNAIL_WIDTH  # noqa: E402

WP_RO = "/usr/local/sbin/kpop/kpop-wp-ro"
UPLOADS = "https://www.kpopjournal.tokyo/wp-content/uploads/"

SQL = (
    "SELECT p.post_name, pm2.meta_value FROM wp_posts p "
    "JOIN wp_postmeta pm ON pm.post_id=p.ID AND pm.meta_key='_thumbnail_id' "
    "JOIN wp_postmeta pm2 ON pm2.post_id=pm.meta_value AND pm2.meta_key='_wp_attached_file' "
    "WHERE p.post_status='publish' AND p.post_type='post'"
)


def fetch_rows():
    out = subprocess.run(["sudo", "-n", WP_RO, "db", "query", SQL],
                         capture_output=True, text=True, timeout=120).stdout
    rows = []
    for line in out.splitlines()[1:]:
        parts = line.rstrip("\n").split("\t")
        if len(parts) >= 2 and parts[1]:
            rows.append((parts[0], parts[1]))
    return rows


def build_image_url(rel_path):
    """uploads 配下の相対パスから画像URLを組み立てる。

    2026-08-23: 日本語ファイル名(「名称未設定のデザイン.jpg」等)をそのまま
    urlopen に渡すと取得に失敗し、14件が 0x0(=取得失敗)と報告されていた。
    「取得できない」と「本当に1200px未満」が混ざって実寸法が分からなくなるため、
    パス部分だけを percent-encode する(/ は残す。既にエンコード済みの %XX は
    二重エンコードしない)。
    """
    return UPLOADS + urllib.parse.quote(str(rel_path), safe="/%")


def probe(url):
    try:
        from PIL import Image
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = r.read()
        return Image.open(io.BytesIO(data)).size
    except Exception:
        return (0, 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    rows = fetch_rows()
    if a.limit:
        rows = rows[:a.limit]

    bad = []
    for name, f in rows:
        w, h = probe(build_image_url(f))
        res = check_resolution(w, h)
        if not res["ok"]:
            bad.append({"slug": name, "file": f, "width": w, "height": h,
                        "issue": res["issue"]})

    if a.json:
        print(json.dumps({"checked": len(rows), "below_min": len(bad),
                          "min_width": MIN_THUMBNAIL_WIDTH, "items": bad},
                         ensure_ascii=False))
    else:
        print(f"検査 {len(rows)}件 / 幅{MIN_THUMBNAIL_WIDTH}px未満 {len(bad)}件")
        for b in bad[:40]:
            print(f"  {b['width']:5d}x{b['height']:<5d} {b['slug']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
