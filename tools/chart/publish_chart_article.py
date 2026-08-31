#!/usr/bin/env python3
"""publish_chart_article.py — チャート更新時に週次まとめ記事を投稿する

owner依頼 (2026-08-23): チャート更新のたびに、その内容の記事を作る。

冪等: 同じ週の記事が既にあれば、新規作成せず本文を更新する(重複記事を作らない)。
前週データ: data/soompi_chart_prev.json があれば前週比を出す。

Usage:
  python3 tools/chart/publish_chart_article.py            # 投稿/更新
  python3 tools/chart/publish_chart_article.py --dry-run  # 生成物を表示のみ
"""
from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

from lib.chart_article import (build_article, build_title, build_slug,  # noqa: E402
                               build_meta_description)

CHART = BASE / "data" / "soompi_chart_top10.json"
PREV = BASE / "data" / "soompi_chart_prev.json"
RW = "/usr/local/sbin/kpop/kpop-wp-rw.sh"
RO = "/usr/local/sbin/kpop/kpop-wp-ro"
CATEGORY = "chart"   # 既存の「チャート」カテゴリ(term_id 6)


def _ro(*args) -> str:
    return subprocess.run(["sudo", "-n", RO, *args],
                          capture_output=True, text=True, timeout=90).stdout


def _rw(*args) -> tuple[int, str]:
    p = subprocess.run(["sudo", "-n", RW, *args],
                       capture_output=True, text=True, timeout=180)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def find_existing(slug: str):
    out = _ro("post", "list", "--post_type=post", "--post_status=any",
              f"--name={slug}", "--field=ID", "--format=csv")
    for line in out.splitlines():
        line = line.strip()
        if line.isdigit():
            return int(line)
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if not CHART.exists():
        print("[error] チャートJSONが無い"); return 1
    chart = json.loads(CHART.read_text(encoding="utf-8"))
    prev = None
    if PREV.exists():
        try:
            prev = json.loads(PREV.read_text(encoding="utf-8"))
            # 同じ週なら前週扱いしない
            if prev.get("url") == chart.get("url"):
                prev = None
        except json.JSONDecodeError:
            prev = None

    title = build_title(chart)
    slug = build_slug(chart)
    meta_desc = build_meta_description(chart)
    body = build_article(chart, prev=prev)

    if a.dry_run:
        print(f"title: {title}\nslug : {slug}\nprev : {'あり' if prev else 'なし'}")
        print(f"meta : {meta_desc}")
        print(f"body : {len(body)}B")
        return 0

    pid = find_existing(slug)
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False,
                                     dir="/tmp", encoding="utf-8") as f:
        f.write(body)
        tmp = f.name
    Path(tmp).chmod(0o644)

    if pid:
        rc, out = _rw("post", "update", str(pid), tmp,
                      f"--post_title={title}")
        print(f"[update] post {pid}: {out.strip()[:120]}")
    else:
        rc, out = _rw("post", "create", tmp, f"--post_title={title}",
                      f"--post_name={slug}", "--post_status=publish",
                      "--post_type=post", "--porcelain")
        pid = out.strip().splitlines()[-1] if rc == 0 else None
        print(f"[create] post {pid}: {out.strip()[:120]}")
    Path(tmp).unlink(missing_ok=True)
    if rc != 0 or not pid:
        return 1

    # AIOSEO メタ説明。2026-08-31 まで チャート経路だけ設定が無く、
    # 毎週2本が恒常的にメタ欠落していた。REST は黙って破棄されるので
    # 必ず DB 経路で書き、DB実値で検証する([[aioseo-desc-write-traps]])。
    try:
        from tools.backfill_aioseo_description import set_description_for_post
        r = set_description_for_post(pid, desc=meta_desc)
        print(f"[meta] {'ok' if r.get('ok') else 'NG'}: {r}")
    except Exception as e:
        print(f"[meta] 失敗: {type(e).__name__}: {str(e)[:80]}")

    # アイキャッチ(1200x630)。幅1200px未満はモバイルCTRが半減するため毎回生成する
    try:
        from tools.chart.make_chart_thumb import render as render_thumb
        thumb = Path(tempfile.gettempdir()) / f"{slug}.jpg"
        if render_thumb(chart, thumb):
            thumb.chmod(0o644)
            arc, aout = _rw("media", "import", str(thumb),
                            f"--title=K-POPチャート {build_title(chart)}",
                            "--porcelain")
            aid = aout.strip().splitlines()[-1] if arc == 0 else ""
            if aid.isdigit():
                _rw("post", "meta", "update", str(pid), "_thumbnail_id", aid)
                print(f"[thumb] attachment={aid}")
            else:
                print(f"[warn] サムネ import 失敗: {aout.strip()[:100]}")
            thumb.unlink(missing_ok=True)
    except Exception as e:
        print(f"[warn] サムネ処理skip: {e}")

    # カテゴリ付与(未設定だと「未分類」になり回遊もSEOも損なう)
    trc, tout = _rw("post", "term", "set", str(pid), "category", CATEGORY)
    if trc != 0:
        print(f"[warn] カテゴリ設定失敗: {tout.strip()[:100]}")

    # 今回分を「前週」として退避(次回の前週比に使う)
    PREV.write_text(json.dumps(chart, ensure_ascii=False), encoding="utf-8")
    print(f"[ok] {title} → /{slug}/")
    print(f"     GSC申請: venv_kpi/bin/python3 lib/gsc_indexing.py --url "
          f"https://www.kpopjournal.tokyo/{slug}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
