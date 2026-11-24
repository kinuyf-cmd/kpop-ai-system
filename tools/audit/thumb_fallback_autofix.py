#!/usr/bin/env python3
"""サムネの「信号artistフォールバック」誤画像を検出し、出典og画像へ差し替える(2026-11-24)。

背景: 信号のartistが記事の主役と別のとき、artist本人写真/MV画像が付く事故があった
(10/25以降31本。2xFE記事にBIGBANG)。日次サムネ監査(Vision)のunrelatedは「判別不能」も含み
誤判定が多いので、監査の判定には頼らず、公開ログの出所(artist_fallback)と題名で決定的に判定する。

検出: logs/unified_publish.jsonl の直近N時間の公開成功のうち
  1. log に artist_fallback がある(=og画像でなくartist画像が付いた)
  2. 題名からK-POPの主役(classifyのsubjects)が1つも検出できない
修復: 記事末尾の出典リンクのog画像(fetch_source_image)を kpop-featured-set.sh(https限定)で差し替える。
og画像が取れなければ何もしない(誤画像のままにせず、結果に「修復不能」と出す)。

usage: python3 tools/audit/thumb_fallback_autofix.py [--hours 48] [--apply]
"""
import argparse
import json
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "lib"))
RO = ["sudo", "-n", "/usr/local/sbin/kpop/kpop-wp-ro"]
FEATURED = "/usr/local/sbin/kpop/kpop-featured-set.sh"
OUT = BASE / "logs" / "thumb_fallback_autofix.jsonl"


def _known_names() -> list[str]:
    """題名にこの名前が出ていれば、信号artistが正しい可能性が高いので触らない(classifyがIU等を拾えない対策)"""
    names = []
    try:
        names += list(json.loads((BASE / "config" / "artist_database.json").read_text(encoding="utf-8")))
        for a in json.loads((BASE / "config" / "artist_master.json").read_text(encoding="utf-8"))["artists"]:
            names += [a.get("name_en", ""), a.get("name_ja", "")]
        kp = json.loads((BASE / "config" / "korean_proper_nouns.json").read_text(encoding="utf-8"))
        for sec in ("groups", "members", "labels", "personalities"):
            names += [v for v in (kp.get(sec) or {}).values() if isinstance(v, str)]
    except Exception:
        pass
    names += ["IU", "アイユー", "HYBE", "SM", "JYP", "YG"]
    return [n.casefold() for n in names if len(n) >= 2 and not n.startswith("_")]


def _already_fixed() -> set[int]:
    done = set()
    try:
        done |= {int(x["post_id"]) for x in json.loads((BASE / "data" / "thumb_replace_20261124.json").read_text())}
        done.add(28703)  # 2026-11-24 手動差替え
    except Exception:
        pass
    if OUT.exists():
        for line in OUT.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
                if r.get("status") == "replaced":
                    done.add(int(r["post_id"]))
            except (ValueError, KeyError):
                pass
    return done


def suspects(hours: int) -> list[dict]:
    from lib.article_topic_classifier import classify
    known, fixed = _known_names(), _already_fixed()
    since = datetime.now() - timedelta(hours=hours)
    seen, res = set(), []
    for line in (BASE / "logs" / "unified_publish.jsonl").read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
            ts = datetime.fromisoformat(r["ts"])
        except (ValueError, KeyError):
            continue
        if ts < since or not r.get("success") or not r.get("post_id") or r["post_id"] in seen:
            continue
        if "artist_fallback" not in json.dumps(r.get("log", []), ensure_ascii=False):
            continue
        title = r.get("title") or ""
        if classify(title, "").get("subjects"):
            continue
        if r["post_id"] in fixed or any(n in title.casefold() for n in known):
            continue
        seen.add(r["post_id"])
        res.append({"post_id": r["post_id"], "title": title})
    return res


def source_url(post_id: int) -> str | None:
    b = subprocess.run(RO + ["post", "get", str(post_id), "--field=post_content"],
                       capture_output=True, text=True).stdout
    m = re.search(r"情報ソース・出典(.*)", b, re.S)
    urls = [u for u in re.findall(r'href="(https?://[^"]+)"', m.group(1) if m else "")
            if "kpopjournal" not in u and "a8.net" not in u]
    return urls[0] if urls else None


def fix(post_id: int, apply: bool) -> dict:
    from lib.thumbnail_resolver import fetch_source_image
    su = source_url(post_id)
    if not su:
        return {"status": "no_source_url"}
    with tempfile.TemporaryDirectory(prefix="kpj_tfix_") as td:
        r = fetch_source_image(su, str(Path(td) / "og.jpg"))
    if not r or not r.get("image_url"):
        return {"status": "no_og_image", "source": su}
    img = r["image_url"].replace("http://", "https://", 1)
    if not apply:
        return {"status": "would_replace", "image": img}
    p = subprocess.run(["sudo", "-n", FEATURED, str(post_id), img, urlparse(img).hostname],
                       capture_output=True, text=True)
    ok = "featured 差し替え完了" in p.stdout
    return {"status": "replaced" if ok else "replace_failed", "image": img,
            "detail": "" if ok else (p.stdout + p.stderr)[-200:]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=48)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    found = suspects(a.hours)
    print(f"対象 {len(found)} 本({a.hours}h・{'apply' if a.apply else 'dry-run'})")
    with OUT.open("a", encoding="utf-8") as f:
        for s in found:
            res = fix(s["post_id"], a.apply)
            rec = {"ts": datetime.now().isoformat(timespec="seconds"), **s, **res, "apply": a.apply}
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            print(f"  {s['post_id']} {s['title'][:30]} -> {res['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
