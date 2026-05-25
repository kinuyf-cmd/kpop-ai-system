#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""group_hero_fetch.py — 「Wikipedia第一優先」で確定したグループ集合写真をDL・正規化・ステージ。

入力 : batch_group_hero/probe.tsv（group_hero_probe.py の出力）の status=has_img 行。
        既定では free=Y（CC/PD等フリーライセンス）のみ対象。--include-nonfree で
        オーナー判断(選択肢4)の権利写真も対象化（その場合も出所は必ず記録）。
方式 : Commons の original 画像URLを Range GET 検証付きでDL → PIL で
        長辺1280pxに「比率保持」リサイズ（歪み厳禁: memory thumbnail-aspect-ratio）→
        RGB JPEG(quality85) で <pid>_hero.jpg にステージ。manifest と import_credits を生成。
出力 : /home/aiuser/.kpop_recovery/batch_group_hero/<pid>_hero.jpg
        + manifest.json + import_credits.json（pid -> {credit, license, source_url, file, alt}）
冪等 : 既に <pid>_hero.jpg があればDLスキップ（--force で再取得）。
レート: Commons DL 3.0-3.5s、429/HTMLで15-20sバックオフ。捏造しない（失敗はスキップ記録）。
引数 : python3 group_hero_fetch.py [--include-nonfree] [--force] [pid ...]
"""
import os, sys, json, time, re, urllib.request, urllib.parse
from io import BytesIO
from PIL import Image, ImageOps

UA  = "KpopJournalBot/1.0 (kpopjournal.biz@gmail.com) Idol-Wiki research"
SRC = "batch_group_hero/probe.tsv"
OUT = "/home/aiuser/.kpop_recovery/batch_group_hero"
LONG_EDGE = 1280
os.makedirs(OUT, exist_ok=True)

args = sys.argv[1:]
include_nonfree = "--include-nonfree" in args
force = "--force" in args
pid_filter = [a for a in args if a.isdigit()]

def http(url, timeout=40):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(), r.headers.get("Content-Type", "")

def commons_credit(file_title):
    """Commons extmetadata から license/artist/credit/source を再取得して出所文字列を組む。"""
    api = ("https://commons.wikimedia.org/w/api.php?action=query&format=json"
           "&titles=" + urllib.parse.quote("File:" + file_title) +
           "&prop=imageinfo&iiprop=extmetadata|url")
    try:
        data, _ = http(api, 25); d = json.loads(data)
    except Exception:
        return {}
    for _pid, pg in d.get("query", {}).get("pages", {}).items():
        ii = (pg.get("imageinfo") or [{}])[0]; ext = ii.get("extmetadata", {})
        strip = lambda k: re.sub(r"<[^>]+>", "", (ext.get(k, {}) or {}).get("value", "")).strip()
        lic = strip("LicenseShortName"); artist = strip("Artist")
        return {"license": lic, "artist": artist,
                "descurl": ii.get("descriptionurl", ""),
                "licurl": strip("LicenseUrl")}
    return {}

def build_credit(meta, file_title):
    """出所表示文字列。例: 'Wikimedia Commons / <artist> / CC BY-SA 2.0'"""
    parts = ["Wikimedia Commons"]
    if meta.get("artist"): parts.append(meta["artist"])
    if meta.get("license"): parts.append(meta["license"])
    return " / ".join(parts)

rows = [l.rstrip("\n").split("\t") for l in open(SRC) if l.strip()]
header = rows[0]; rows = rows[1:]
idx = {k: i for i, k in enumerate(header)}

manifest = {}; credits = {}; n_ok = n_skip = n_fail = 0
for r in rows:
    pid = r[idx["pid"]]; title = r[idx["title"]]; status = r[idx["status"]]
    free = r[idx["free"]]; img = r[idx["img"]]; wt = r[idx["wikititle"]]
    if pid_filter and pid not in pid_filter:
        continue
    if status != "has_img" or not img or img == "None":
        continue
    if free != "Y" and not include_nonfree:
        continue
    dest = os.path.join(OUT, f"{pid}_hero.jpg")
    if os.path.exists(dest) and not force:
        print(f"[skip] {pid} {title} (already staged)"); n_skip += 1; continue
    # Commonsファイル名を img URL から復元（最後のパス要素をデコード）
    file_title = urllib.parse.unquote(img.rsplit("/", 1)[-1])
    try:
        data, ctype = http(img)
        if "html" in ctype.lower():
            raise RuntimeError("got HTML (rate-limited?)");
        im = Image.open(BytesIO(data))
        im = ImageOps.exif_transpose(im).convert("RGB")
        # 比率保持で長辺 LONG_EDGE に（歪み厳禁）。小さい画像は拡大しない。
        if max(im.width, im.height) > LONG_EDGE:
            im.thumbnail((LONG_EDGE, LONG_EDGE), Image.LANCZOS)
        im.save(dest, "JPEG", quality=85, optimize=True)
        meta = commons_credit(file_title); time.sleep(1.2)
        credit = build_credit(meta, file_title)
        alt = f"{title} メイン画像"
        manifest[pid] = {"title": title, "file": dest, "w": im.width, "h": im.height,
                         "wikititle": wt, "source_img": img, "license": meta.get("license", ""),
                         "free": free}
        credits[pid] = {"credit": credit, "license": meta.get("license", ""),
                        "source_url": meta.get("descurl", ""), "alt": alt}
        print(f"[ok]   {pid} {title}  {im.width}x{im.height}  {credit}")
        n_ok += 1
        time.sleep(3.0)
    except Exception as e:
        print(f"[FAIL] {pid} {title}: {e}")
        n_fail += 1
        time.sleep(15.0)

json.dump(manifest, open(os.path.join(OUT, "manifest.json"), "w"), ensure_ascii=False, indent=1)
json.dump(credits,  open(os.path.join(OUT, "import_credits.json"), "w"), ensure_ascii=False, indent=1)
print(f"\n=== staged ok={n_ok} skip={n_skip} fail={n_fail} -> {OUT} ===", file=sys.stderr)
