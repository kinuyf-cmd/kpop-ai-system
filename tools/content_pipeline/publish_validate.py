#!/usr/bin/env python3
"""publish-validate: 下書き(または公開後の本番ページ)を描画して、公開してよいかを機械判定する。

失敗にする条件(1つでも当たれば exit 1):
  [numbers]  元の本文(DB の raw)にある URL・ID・数字が、描画後に1つでも欠けている/変わっている。
             「000000141 → 00141」のような桁落ち・置換を捕まえる。比較は多重集合(出現回数まで)。
  [faq]      FAQPage の JSON-LD が無い・JSON として壊れている・Question/Answer の形が不正・
             2個以上ある・質問文が本文に見えていない。grep ではなく json.loads でパースする。
             (ページ内の ld+json が1つでもパース不能なら失敗)
  [identity] タイトル・description・alternateName などがサイト設定(config/site_identity.json
             と WP の blogname / AIOSEO の保存値)と食い違う。

描画の取り方:
  既定(下書き): REST /posts/<id>?context=edit の content.raw(元)と content.rendered(the_content
                フィルタ適用後)、AIOSEO が返す aioseo_head(title/meta/og/JSON-LD)を使う。
                wp eval はラッパーで禁止なので、REST が正規の描画経路。
  --live:       公開URLの実HTML(キャッシュ回避パラメータ付き)をそのまま検査する。公開直後の確認用。

使い方:
  scripts/publish-validate.sh 27623
  scripts/publish-validate.sh --live 27623
  scripts/publish-validate.sh --json 27623
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import urllib.request
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.content_pipeline.common import (BASE, SITE_IDENTITY, aioseo_description,  # noqa: E402
                                            aioseo_field, wp, wp_ro)

URL_RE = re.compile(r"https?://[^\s\"'<>()\[\]{}\\]+")
# 区切り(, . : / -)を挟んだ数字列を1トークンにする: 2026.11.14 / 18:00 / 1,200 / 000000141
NUM_RE = re.compile(r"[0-9０-９]+(?:[,.:/\-][0-9０-９]+)*")
LDJSON_RE = re.compile(r"<script[^>]*type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
                       re.S | re.I)
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
SHORTCODE_RE = re.compile(r"\[/?[a-z][a-z0-9_\-]*(?:\s[^\]]*)?\]")


# ------------------------------------------------------------------ tokens
def _tokens(text: str) -> Counter:
    """URL と数字のトークン(多重集合)。URL 内の数字も数字として数える。"""
    t = html.unescape(text)
    toks = Counter()
    for u in URL_RE.findall(t):
        toks["URL " + u.rstrip(".,、。")] += 1
    for n in NUM_RE.findall(t):
        toks["NUM " + n] += 1
    return toks


def _near(tok: str, pool: Counter) -> list[str]:
    """欠けたトークンに似た描画側トークン(診断用)。先頭0を落とした値や部分一致。"""
    kind, val = tok.split(" ", 1)
    out = []
    for p in pool:
        pk, pv = p.split(" ", 1)
        if pk != kind or pv == val:
            continue
        if kind == "NUM" and (pv.lstrip("0") == val.lstrip("0") or (len(pv) > 2 and (pv in val or val in pv))):
            out.append(pv)
        elif kind == "URL" and (pv.split("?")[0] == val.split("?")[0] or pv.rstrip("/") == val.rstrip("/")):
            out.append(pv)
    return out[:3]


def check_unsafe_html(raw: str) -> list[str]:
    """本文(DB の raw)に、ld+json 以外の script・イベント属性・javascript:/data: URL・iframe 等が無いか。"""
    errs = []
    for m in re.finditer(r"<script\b([^>]*)>", raw, re.I):
        if not re.search(r"type=[\"']application/ld\+json[\"']", m.group(1), re.I):
            errs.append(f"unsafe: 本文に実行可能な <script{m.group(1)[:40]}> がある")
    for pat, why in ((r"<(iframe|object|embed|form)\b", "埋め込み/フォーム要素"),
                     (r"\son[a-z]+\s*=", "イベント属性(on*=)"),
                     (r"(href|src)\s*=\s*[\"']?\s*(javascript|data|vbscript):", "危険なURLスキーム")):
        if re.search(pat, raw, re.I):
            errs.append(f"unsafe: 本文に{why}がある")
    return errs


def check_numbers(raw: str, rendered: str, label: str) -> list[str]:
    src = COMMENT_RE.sub(" ", raw)        # ブロックエディタのコメントは描画で消えるのが正しい
    src = SHORTCODE_RE.sub(" ", src)      # ショートコードは展開される(引数の数字は消えてよい)
    want, have = _tokens(src), _tokens(rendered)
    errs = []
    for tok, n in (want - have).items():
        near = _near(tok, have)
        hint = f"(描画側の近い値: {', '.join(near)})" if near else ""
        errs.append(f"{label}: 元の {tok} が描画後に{n}個足りない{hint}")
    return errs


# ------------------------------------------------------------------ JSON-LD
def _ld_nodes(obj):
    if isinstance(obj, list):
        for x in obj:
            yield from _ld_nodes(x)
    elif isinstance(obj, dict):
        yield obj
        for k in ("@graph", "mainEntity", "itemListElement"):
            if k in obj and k != "mainEntity":
                yield from _ld_nodes(obj[k])


def _types(node) -> set:
    t = node.get("@type")
    return set(t if isinstance(t, list) else [t]) if t else set()


def parse_ldjson(doc: str) -> tuple[list, list[str]]:
    nodes, errs = [], []
    for i, block in enumerate(LDJSON_RE.findall(doc)):
        try:
            nodes.extend(_ld_nodes(json.loads(block)))
        except ValueError as e:
            errs.append(f"ld+json #{i + 1} が JSON として壊れている: {e} / 先頭: {block.strip()[:80]!r}")
    return nodes, errs


_QUOTES = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
                         "\u2032": "'", "\u2033": '"', "\u2013": "-", "\u2014": "-", "\u2026": "..."})


def _norm(s: str) -> str:
    """比較用: 実体参照を戻し、wptexturize の曲げ引用符・ダッシュ等をそろえ、空白を除く。"""
    return re.sub(r"\s+", "", html.unescape(s).translate(_QUOTES))


def _visible(doc: str) -> str:
    d = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", doc, flags=re.S | re.I)
    d = re.sub(r"<[^>]+>", " ", d)
    return _norm(d)


def check_faq(nodes: list, ld_errs: list[str], visible_doc: str) -> list[str]:
    errs = [f"faq: {e}" for e in ld_errs]
    faqs = [n for n in nodes if "FAQPage" in _types(n)]
    if not faqs:
        return errs + ["faq: FAQPage の JSON-LD が無い"]
    if len(faqs) > 1:
        errs.append(f"faq: FAQPage が {len(faqs)} 個ある(1記事1個)")
    vis = _visible(visible_doc)
    for f in faqs:
        me = f.get("mainEntity")
        if not isinstance(me, list) or not me:
            errs.append("faq: mainEntity が空か配列でない")
            continue
        for j, q in enumerate(me, 1):
            if not isinstance(q, dict) or "Question" not in _types(q):
                errs.append(f"faq: Q{j} の @type が Question でない")
                continue
            name = q.get("name")
            ans = q.get("acceptedAnswer")
            if isinstance(ans, list):
                ans = ans[0] if ans else None
            if not isinstance(name, str) or not name.strip():
                errs.append(f"faq: Q{j} の name が空")
                continue
            if not isinstance(ans, dict) or "Answer" not in _types(ans) \
                    or not isinstance(ans.get("text"), str) or not ans["text"].strip():
                errs.append(f"faq: Q{j}「{name[:30]}」の acceptedAnswer.text が無い/不正")
                continue
            if _norm(name) not in vis:
                errs.append(f"faq: Q{j}「{name[:30]}」が本文に見えていない(構造化データだけの FAQ は不可)")
            a_head = _norm(re.sub(r"<[^>]+>", " ", html.unescape(ans["text"])))[:20]
            if a_head and a_head not in vis:
                errs.append(f"faq: Q{j} の回答「{a_head}…」が本文に見えていない/本文と食い違う")
    return errs


# ------------------------------------------------------------------ identity
def _meta(doc: str, attr: str, key: str) -> str | None:
    for m in re.finditer(r"<meta\s[^>]*>", doc, re.I):
        tag = m.group(0)
        if re.search(rf'{attr}=["\']{re.escape(key)}["\']', tag, re.I):
            c = re.search(r'content=["\'](.*?)["\']', tag, re.S)
            return html.unescape(c.group(1)).strip() if c else ""
    return None


def expected_title(cfg: dict, post_title: str, seo_title: str) -> str:
    """AIOSEO の記事別タイトル(あれば)を正とし、無ければ「記事タイトル + 設定の接尾辞」。"""
    if not seo_title:
        return post_title + cfg["title_suffix"]
    sep = cfg["title_suffix"].strip().split(" ")[0] or "-"
    t = (seo_title.replace("#post_title", post_title).replace("#separator_sa", sep)
         .replace("#site_title", cfg["site_name"]))
    return re.sub(r"\s+", " ", t).strip()


def check_identity(cfg: dict, post_title: str, head_title: str | None, head_doc: str,
                   nodes: list, stored_desc: str, blogname: str, seo_title: str = "") -> list[str]:
    errs = []
    if blogname.strip() != cfg["site_name"]:
        errs.append(f"identity: WP の blogname「{blogname.strip()}」≠ 設定 site_name「{cfg['site_name']}」")
    if len(post_title) > cfg["post_title_max_chars"]:
        errs.append(f"identity: 記事タイトルが {len(post_title)} 字(上限 {cfg['post_title_max_chars']})")
    want_title = expected_title(cfg, post_title, seo_title)
    if head_title is None:
        errs.append("identity: <title> が取れない")
    elif _norm(head_title) != _norm(want_title):
        errs.append(f"identity: <title>「{head_title}」≠ 期待「{want_title}」")
    og_site = _meta(head_doc, "property", "og:site_name")
    if og_site != cfg["og_site_name"]:
        errs.append(f"identity: og:site_name「{og_site}」≠ 設定「{cfg['og_site_name']}」")
    og_title = _meta(head_doc, "property", "og:title")
    if og_title is not None and og_title not in (want_title, post_title, html.unescape(seo_title)):
        errs.append(f"identity: og:title「{og_title}」がタイトルと食い違う")

    if not stored_desc:
        errs.append("identity: AIOSEO の description(wp_aioseo_posts)が空")
    else:
        n = len(stored_desc)
        if not cfg["description_min_chars"] <= n <= cfg["description_max_chars"]:
            errs.append(f"identity: description が {n} 字(許容 {cfg['description_min_chars']}〜"
                        f"{cfg['description_max_chars']})")
        for key, attr in (("description", "name"), ("og:description", "property")):
            got = _meta(head_doc, attr, key)
            if got is not None and _norm(got) != _norm(stored_desc):
                errs.append(f"identity: {key} の出力「{got[:40]}…」≠ AIOSEO 保存値「{stored_desc[:40]}…」")
        if _meta(head_doc, "name", "description") is None:
            errs.append("identity: <meta name=description> が出ていない")

    want_alt = set(cfg["alternate_names"])
    for typ in ("WebSite", "Organization"):
        ns = [n for n in nodes if typ in _types(n)]
        if not ns:
            errs.append(f"identity: {typ} の構造化データが無い")
            continue
        for n in ns:
            if n.get("name") != cfg["site_name"]:
                errs.append(f"identity: {typ}.name「{n.get('name')}」≠「{cfg['site_name']}」")
            alt = n.get("alternateName")
            got = set(alt if isinstance(alt, list) else ([alt] if alt else []))
            if got != want_alt:
                errs.append(f"identity: {typ}.alternateName {sorted(got)} ≠ 設定 {sorted(want_alt)}")
    return errs


# ------------------------------------------------------------------ main
def _fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (kpj publish-validate)"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", errors="replace")


def validate(post_id: int, live: bool = False) -> dict:
    cfg = json.loads(SITE_IDENTITY.read_text(encoding="utf-8"))
    p = wp("GET", f"/posts/{post_id}?context=edit")
    raw = p["content"]["raw"]
    post_title = html.unescape(p["title"]["raw"]).strip()
    blogname = wp_ro("option", "get", "blogname")
    stored_desc = aioseo_description(post_id)
    seo_title = aioseo_field(post_id, "title")
    errs: list[str] = []

    if live:
        if p["status"] != "publish":
            errs.append(f"live: 記事の status が {p['status']}(公開されていない)")
        doc = _fetch(f"{p['link']}{'&' if '?' in p['link'] else '?'}kpjv={int(time.time())}")
        m = re.search(r"<title[^>]*>(.*?)</title>", doc, re.S | re.I)
        head_title = html.unescape(m.group(1)).strip() if m else None
        body_doc = doc
        head_doc = doc[: doc.lower().find("</head>")] if "</head>" in doc.lower() else doc
        errs += check_numbers(raw, doc, "本番HTML")
        errs += check_numbers(p["title"]["raw"], head_title or "", "title")
    else:
        rendered = p["content"]["rendered"]
        head_doc = p.get("aioseo_head") or ""
        hj = p.get("aioseo_head_json") or {}
        head_title = html.unescape(hj["title"]).strip() if hj.get("title") else None
        if head_title is None:
            m = re.search(r"<title[^>]*>(.*?)</title>", head_doc, re.S | re.I)
            head_title = html.unescape(m.group(1)).strip() if m else None
        body_doc = rendered
        errs += check_numbers(raw, rendered, "本文")
        errs += check_numbers(p["title"]["raw"], p["title"]["rendered"], "title")
        if not head_doc:
            errs.append("identity: REST に aioseo_head が無い(AIOSEO の head を検査できない)")

    errs += check_unsafe_html(raw)
    # 表記ガード(2026-11-18): 翻訳で化けた人名・曲名(ペク・ジヘン/体ポハゲッソ型)
    from lib.notation_guard import check_notation
    errs += [f"notation: {i['detail']}" for i in check_notation(post_title, raw)]
    nodes, ld_errs = parse_ldjson(body_doc + ("" if live else head_doc))
    errs += check_faq(nodes, ld_errs, body_doc)
    errs += check_identity(cfg, post_title, head_title, head_doc, nodes, stored_desc, blogname,
                           seo_title)
    return {"post_id": post_id, "mode": "live" if live else "draft", "status": p["status"],
            "link": p["link"], "title": post_title, "ok": not errs, "errors": errs}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("post_id", type=int)
    ap.add_argument("--live", action="store_true", help="公開URLの実HTMLを検査")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    try:
        r = validate(a.post_id, a.live)
    except Exception as e:  # noqa: BLE001  取得できない=検査できない=失敗扱い
        r = {"post_id": a.post_id, "ok": False, "errors": [f"検査不能: {e}"]}
    out = BASE / "content" / "validate"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{a.post_id}-{'live' if a.live else 'draft'}.json").write_text(
        json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
    else:
        print(f"{'PASS' if r['ok'] else 'FAIL'} post {a.post_id} ({r.get('mode', '?')}) {r.get('title', '')}")
        for e in r["errors"]:
            print("  - " + e)
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
