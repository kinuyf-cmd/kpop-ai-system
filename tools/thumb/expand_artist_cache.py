#!/usr/bin/env python3
"""expand_artist_cache.py — 本人写真cacheの半自動拡充(2026-07-02)

DALL-Eサムネ多発の真因である「artist_cache枯渇」を解消するツール。
Wikidata P18(本人確定手法 [[idol-wiki-images-wikidata-p18-method]]:
group QID → P527メンバー → 各P18)で候補画像を取得する。

安全設計 — 同名別人誤マッチ事故([[thumbnail-stage2-artist-canonical-fix]])防止:
  * 2段階制。fetch はstagingに保存するだけで cache には入れない。
    人間(またはClaude)が全画像を視認してから commit で cache へ移す。
  * QIDは自動選択しない。search で候補一覧を出し、descriptionを見て
    人間が --qid を明示指定する(cortisol と CORTIS の同名事故を防ぐ)。

使い方(3ステップ):
  1) venv_kpi/bin/python3 tools/thumb/expand_artist_cache.py search "TREASURE"
       → QID候補と説明の一覧。正しいK-POPグループのQIDを目で選ぶ
  2) venv_kpi/bin/python3 tools/thumb/expand_artist_cache.py fetch <QID> --slug treasure
       → staging(assets/artist_cache_staging/<slug>/)にDL。全画像を視認すること
  3) venv_kpi/bin/python3 tools/thumb/expand_artist_cache.py commit <slug>
       → 視認済み前提でJPEG最適化して assets/artist_cache/ へ配置
     不要画像は commit 前に staging から rm しておけば除外される。

Wikimedia Commonsへの読み取りアクセスのみ。課金なし。書込はローカルのみ。
"""
import argparse
import hashlib
import json
import shutil
import ssl
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent
CACHE = BASE / "assets" / "artist_cache"
STAGING = BASE / "assets" / "artist_cache_staging"
UA = {"User-Agent": "KPOPJournal-cache-expand/1.0 (kinu.yf@gmail.com)"}
CTX = ssl.create_default_context()


def _get(url, timeout=25, retries=3):
    for i in range(retries):
        try:
            return urllib.request.urlopen(
                urllib.request.Request(url, headers=UA), timeout=timeout, context=CTX).read()
        except Exception as e:
            if "429" in str(e) and i < retries - 1:
                time.sleep(4)
                continue
            raise


def _entity(qid):
    return json.loads(_get(f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"))["entities"][qid]


def _claims(qid, prop):
    out = []
    for c in _entity(qid).get("claims", {}).get(prop, []):
        try:
            out.append(c["mainsnak"]["datavalue"]["value"])
        except Exception:
            pass
    return out


def _label(ent):
    for lang in ("en", "ja", "ko"):
        v = ent.get("labels", {}).get(lang, {}).get("value")
        if v:
            return v
    return "?"


def _commons_url(filename):
    f = filename.replace(" ", "_")
    h = hashlib.md5(f.encode("utf-8")).hexdigest()
    return f"https://upload.wikimedia.org/wikipedia/commons/{h[0]}/{h[0:2]}/{urllib.parse.quote(f)}"


def cmd_search(term):
    """QID候補を一覧表示。K-POPグループらしきものに★を付けるが、選択は人間"""
    u = "https://www.wikidata.org/w/api.php?" + urllib.parse.urlencode({
        "action": "wbsearchentities", "search": term, "language": "en",
        "format": "json", "limit": 10, "type": "item"})
    rows = json.loads(_get(u)).get("search", [])
    # 英語で出なければ韓国語でも検索
    if not any(("group" in (r.get("description") or "").lower() or
                "band" in (r.get("description") or "").lower()) for r in rows):
        u2 = "https://www.wikidata.org/w/api.php?" + urllib.parse.urlencode({
            "action": "wbsearchentities", "search": term, "language": "ko",
            "format": "json", "limit": 10, "type": "item"})
        rows += json.loads(_get(u2)).get("search", [])
    print(f"=== '{term}' のQID候補(descriptionを見て正しいK-POPグループを選ぶこと) ===")
    seen = set()
    for r in rows:
        if r["id"] in seen:
            continue
        seen.add(r["id"])
        desc = r.get("description", "") or "(説明なし)"
        mark = "★" if any(k in desc.lower() for k in
                          ("boy band", "girl group", "boy group", "south korean")) else " "
        print(f"  {mark} {r['id']:<12} {r.get('label','?'):<20} {desc[:70]}")
    print("\n次: fetch <QID> --slug <cache用slug(英小文字)>")


def cmd_fetch(qid, slug):
    """group P18 + P527メンバーのP18 を staging にDL(cacheには入れない)"""
    ent = _entity(qid)
    name = _label(ent)
    print(f"[fetch] {qid} = {name!r} → staging/{slug}/")
    dest = STAGING / slug
    dest.mkdir(parents=True, exist_ok=True)
    jobs = [(f"{slug}_group", f) for f in _claims(qid, "P18")]
    members = _claims(qid, "P527")
    print(f"  members(P527): {len(members)}人")
    for m in members:
        mid = m.get("id") if isinstance(m, dict) else m
        try:
            ment = _entity(mid)
            mname = _label(ment).lower().replace(" ", "_").replace(".", "")
            for f in _claims(mid, "P18")[:1]:
                jobs.append((f"{slug}_{mname}", f))
            time.sleep(1)
        except Exception as e:
            print(f"    WARN member {mid}: {str(e)[:40]}")
    if not jobs:
        print("  P18画像なし — このQIDからは取得できない")
        return
    meta = {}
    for tag, fn in jobs:
        try:
            raw = _get(_commons_url(fn), timeout=40)
            p = dest / f"{tag}{Path(fn).suffix.lower() or '.jpg'}"
            p.write_bytes(raw)
            meta[p.name] = {"commons_file": fn, "qid": qid, "entity": name}
            print(f"  OK {p.name} ({len(raw)//1024}KB)")
            time.sleep(1.5)
        except Exception as e:
            print(f"  FAIL {tag}: {str(e)[:50]}")
    (dest / "_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[必須] 全画像を視認して本人確認すること。")
    print(f"  不要/別人画像は rm で削除 → その後: commit {slug}")


def cmd_commit(slug):
    """staging の画像を視認済み前提でJPEG最適化して cache へ"""
    from PIL import Image
    src = STAGING / slug
    imgs = [p for p in src.glob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")]
    if not imgs:
        print(f"[ERR] staging/{slug} に画像なし。先に fetch を実行"); sys.exit(2)
    print(f"[commit] {len(imgs)}枚を cache へ(視認済み前提)")
    for p in imgs:
        im = Image.open(p).convert("RGB")
        if max(im.size) > 1600:
            r = 1600 / max(im.size)
            im = im.resize((int(im.width * r), int(im.height * r)), Image.LANCZOS)
        h = hashlib.md5(p.stem.encode()).hexdigest()[:8]
        dst = CACHE / f"{p.stem}_{h}.jpg"
        im.save(dst, "JPEG", quality=88, optimize=True)
        print(f"  ✓ {dst.name} ({dst.stat().st_size//1024}KB)")
    # resolverが実際に拾うか検証
    sys.path.insert(0, str(BASE)); sys.path.insert(0, str(BASE / "lib"))
    from thumbnail_source_resolver import resolve_fallback_photo
    seen = set()
    for _ in range(8):
        r = resolve_fallback_photo(slug.replace("_", " ").upper())
        if r:
            seen.add(Path(r["image_path"]).name)
    print(f"\n[検証] resolverが拾うユニーク画像: {len(seen)}枚")
    for f in sorted(seen):
        print(f"    - {f}")
    shutil.rmtree(src)
    print(f"[done] staging/{slug} を掃除。cache拡充完了")


def main():
    ap = argparse.ArgumentParser(description="artist_cache半自動拡充(P18)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s1 = sub.add_parser("search"); s1.add_argument("term")
    s2 = sub.add_parser("fetch"); s2.add_argument("qid"); s2.add_argument("--slug", required=True)
    s3 = sub.add_parser("commit"); s3.add_argument("slug")
    a = ap.parse_args()
    if a.cmd == "search":
        cmd_search(a.term)
    elif a.cmd == "fetch":
        if not a.qid.startswith("Q"):
            print("[ERR] QIDはQで始まる(例: Q65229673)"); sys.exit(2)
        cmd_fetch(a.qid, a.slug)
    elif a.cmd == "commit":
        cmd_commit(a.slug)


if __name__ == "__main__":
    main()
