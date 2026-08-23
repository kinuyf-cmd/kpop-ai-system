#!/usr/bin/env python3
"""make_chart_thumb.py — チャート記事のアイキャッチ(1200x630)を生成する

サムネ幅1200px未満はモバイルCTRが半減する([[thumbnail-resolution-1200px-gate]])。
チャート記事は毎週作られるので、TOP5を図解した画像を毎回自動生成する。
"""
from __future__ import annotations

import html as _html
import json
import subprocess
import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))
from lib.chart_article import week_label  # noqa: E402

CSS = """
*{margin:0;padding:0;box-sizing:border-box}
body{width:1200px;height:630px;font-family:"Noto Sans CJK JP","Hiragino Sans",sans-serif;
 background:linear-gradient(140deg,#10131f 0%,#1e2340 50%,#3a2a63 100%);color:#fff;
 padding:52px 56px 34px;display:flex;flex-direction:column}
h1{font-size:41px;font-weight:800;text-align:center;letter-spacing:-.5px}
h1 .y{color:#ffd43b}
.sub{text-align:center;font-size:19px;color:#b9c0e0;margin:12px 0 34px;font-weight:600}
.r{display:flex;align-items:center;gap:18px;background:rgba(255,255,255,.08);
 border:1px solid rgba(255,255,255,.16);border-radius:11px;padding:13px 20px;margin-bottom:11px}
.r.top{background:rgba(255,212,59,.16);border-color:#ffd43b}
.no{font-size:29px;font-weight:800;color:#ffd43b;width:54px;text-align:center;flex-shrink:0}
.r:not(.top) .no{color:#8f9bd0;font-size:25px}
.s{font-size:23px;font-weight:800;line-height:1.2}
.a{font-size:15px;color:#c3cbe8;margin-top:2px}
.ft{text-align:center;font-size:15px;color:#8f97bd;margin-top:auto;padding-top:14px;font-weight:600}
"""


def build_html(chart: dict, top_n: int = 5) -> str:
    label = week_label(chart.get("title", "")) or "最新週"
    rows = []
    for it in (chart.get("items") or [])[:top_n]:
        cls = "r top" if it.get("rank") == 1 else "r"
        rows.append(
            f'<div class="{cls}"><div class="no">{it.get("rank")}</div>'
            f'<div><div class="s">{_html.escape(str(it.get("song","")))}</div>'
            f'<div class="a">{_html.escape(str(it.get("artist","")))}</div></div></div>')
    return ("<!doctype html><meta charset=\"utf-8\"><style>" + CSS + "</style>"
            f'<h1>K-POPチャート <span class="y">TOP{top_n}</span></h1>'
            f'<div class="sub">{_html.escape(label)}</div>'
            + "".join(rows)
            + '<div class="ft">KPOP JOURNAL ｜ kpopjournal.tokyo</div>')


def render(chart: dict, out_jpg: Path) -> bool:
    html = build_html(chart)
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False,
                                     encoding="utf-8") as f:
        f.write(html)
        src = f.name
    png = str(Path(src).with_suffix(".png"))
    script = (
        "from playwright.sync_api import sync_playwright\n"
        "with sync_playwright() as p:\n"
        "    b=p.chromium.launch()\n"
        "    pg=b.new_page(viewport={'width':1200,'height':630})\n"
        f"    pg.goto('file://{src}'); pg.wait_for_timeout(600)\n"
        f"    pg.screenshot(path='{png}'); b.close()\n")
    try:
        subprocess.run([str(BASE / "venv_kpi" / "bin" / "python3"), "-c", script],
                       check=True, capture_output=True, timeout=300)
        from PIL import Image
        Image.open(png).convert("RGB").save(
            out_jpg, quality=90, optimize=True, subsampling=0)
        return out_jpg.exists()
    except Exception as e:
        print(f"[warn] サムネ生成失敗: {e}")
        return False
    finally:
        Path(src).unlink(missing_ok=True)
        Path(png).unlink(missing_ok=True)


if __name__ == "__main__":
    c = json.loads((BASE / "data" / "soompi_chart_top10.json").read_text())
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/chart_thumb.jpg")
    print("OK" if render(c, out) else "NG", out)
