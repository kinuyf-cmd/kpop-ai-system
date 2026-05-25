#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""logos3_wikidata_p154.py — batch_logos2 で human review reject された19組のロゴを
Wikidata top-down(group QID -> P154 logo image)で本人確定して再取得する。

背景: batch_logos2(logos2_fetch.py)は Commons テキスト検索が同名別エンティティを誤マッチし
human review で19組(73/79/89/90/94/95/104/105/260/261/262/265/266/272/290/292/294/295/303)が落ちた。
同スクリプト再実行は同じ誤マッチを再現するだけ。本スクリプトは photos2_wikidata.py の
QID解決(description=group/band検証で曖昧性解消)を流用し、その QID の P154(logo image)を直接引く
ことで同名別人問題を原理的に潰す。

方式 : resolve_group(name) -> QID -> wbgetentities -> claims.P154 -> Commons file ->
        imageinfo で free-license 確証 -> verify(Range GET) -> 600px PNG 化 -> stage。
        P154が空 / 非フリー の組は available:false でスキップ(捏造しない=メモリ方針)。
出力 : batch_logos3/<pid>_logo.png, batch_logos3/manifest.json, batch_logos3/import_credits.json
        (import_logos2_verified.sh と同じ <pid>_logo.png + credit JSON 構造で import 可能)
レート: Wikidata API 1.0-1.5s / Commons API・DL 3.0-3.5s、429/HTML で15-20sバックオフ。
引数 : 対象pidを絞れる  python3 logos3_wikidata_p154.py 79 89 90
"""
import json, sys, time, random, re, os, urllib.parse, urllib.request
from io import BytesIO
from PIL import Image

UA  = "KpopJournalBot/1.0 (kpopjournal.biz@gmail.com) Idol-Wiki research"
WD  = "https://www.wikidata.org/w/api.php"
CM  = "https://commons.wikimedia.org/w/api.php"
OUT = "/home/aiuser/.kpop_recovery/batch_logos3"
os.makedirs(OUT, exist_ok=True)

# batch_logos2 reject の19組。name は Wikidata 検索クエリ用の英語名 + 曖昧回避ヒント。
# hints は description に group/band 語が出ない / 同名が多い組向けの追加クエリ。
TARGETS = [
 ("73","KISS OF LIFE",   ["Kiss of Life (group)", "Kiss of Life South Korean"]),
 ("79","SEVENTEEN",      ["Seventeen (South Korean band)", "Seventeen K-pop"]),
 ("89","SUPER JUNIOR",   ["Super Junior"]),
 ("90","BIGBANG",        ["Big Bang (South Korean band)", "Bigbang K-pop"]),
 ("94","Wanna One",      []),
 ("95","INFINITE",       ["Infinite (band)", "Infinite South Korean band"]),
 ("104","SuperM",        []),
 ("105","2PM",           ["2PM (band)"]),
 ("260","MOMOLAND",      ["Momoland"]),
 ("261","TVXQ",          ["TVXQ", "TVXQ!", "Tong Vfang Xien Qi"]),
 ("262","SAY MY NAME",   ["Say My Name (South Korean group)"]),
 ("265","&TEAM",         ["&Team", "and Team band"]),
 ("266","TREASURE",      ["Treasure (group)", "Treasure South Korean band"]),
 ("272","KiiiKiii",      ["Kiiikiii"]),
 ("290","KARA",          ["Kara (South Korean group)"]),
 ("292","f(x)",          ["F(x) (group)", "F(x) band"]),
 ("294","miss A",        ["Miss A"]),
 ("295","Highlight",     ["Highlight (band)", "Highlight South Korean band"]),
 ("303","Block B",       ["Block B"]),
]

FREE_RE = re.compile(r"(public domain|pd-|cc[-\s]?(by|zero|0)|cc0|creative commons)", re.I)
GROUP_WORDS = ("group","band","girl","boy","duo","k-pop","kpop","musical","idol",
               "ensemble","collective","unit","trio","quartet","quintet","septet")

def http_json(url):
    for _ in range(6):
        try:
            req=urllib.request.Request(url, headers={"User-Agent":UA})
            with urllib.request.urlopen(req, timeout=40) as r:
                raw=r.read().decode("utf-8","replace")
            if raw.lstrip().startswith("<") or "Too Many Requests" in raw:
                w=random.uniform(15,20); print(f"    [429/HTML] backoff {w:.1f}",file=sys.stderr); time.sleep(w); continue
            return json.loads(raw)
        except urllib.error.HTTPError as e:
            if e.code==429:
                w=random.uniform(15,20); print(f"    [429] backoff {w:.1f}",file=sys.stderr); time.sleep(w); continue
            time.sleep(random.uniform(2,4))
        except Exception as e:
            print(f"    [err {e}] retry",file=sys.stderr); time.sleep(random.uniform(2,4))
    return {}

def wd_pace(): time.sleep(random.uniform(1.0,1.5))
def cm_pace(): time.sleep(random.uniform(3.0,3.5))

def wd_search(q, limit=8):
    d=http_json(WD+"?"+urllib.parse.urlencode(
        {"action":"wbsearchentities","search":q,"language":"en","format":"json","limit":limit,"type":"item"}))
    wd_pace(); return d.get("search",[])

def wd_entity(qid):
    d=http_json(WD+"?"+urllib.parse.urlencode(
        {"action":"wbgetentities","ids":qid,"format":"json","props":"claims|labels|descriptions"}))
    wd_pace(); return d.get("entities",{}).get(qid,{})

def resolve_group(name_en, hints):
    """description が group/band 系の語を含む候補のみ採用=同名別エンティティ(俳優/曲/地名)を排除。"""
    tries=[name_en, f"{name_en} band", f"{name_en} group", f"{name_en} (band)", f"{name_en} K-pop"]+hints
    seen=set()
    for q in tries:
        for r in wd_search(q):
            qid=r["id"]
            if qid in seen: continue
            seen.add(qid)
            d=(r.get("description","") or "").lower()
            if any(w in d for w in GROUP_WORDS) and ("korean" in d or "k-pop" in d or "kpop" in d or "boy" in d or "girl" in d):
                return qid, r.get("label"), r.get("description")
    # 二段目: korean 縛りを外して group/band 語だけで拾う(SuperM等 description簡素な組向け)
    for q in tries:
        for r in wd_search(q):
            d=(r.get("description","") or "").lower()
            if any(w in d for w in GROUP_WORDS):
                return r["id"], r.get("label"), r.get("description")
    return None,None,None

def p154_of(ent):
    """P154 = logo image. 複数あれば preferred / 先頭。"""
    claims=ent.get("claims",{}).get("P154",[])
    # preferred rank を優先
    claims=sorted(claims, key=lambda c: 0 if c.get("rank")=="preferred" else 1)
    for c in claims:
        try:
            if c["mainsnak"].get("snaktype")=="value":
                return c["mainsnak"]["datavalue"]["value"]
        except Exception: continue
    return None

def commons_info(filename):
    """Commons imageinfo: free-license 判定 + url/thumburl/credit を取得。"""
    title="File:"+filename
    d=http_json(CM+"?"+urllib.parse.urlencode(
        {"action":"query","titles":title,"prop":"imageinfo",
         "iiprop":"url|extmetadata|mime|size","iiurlwidth":600,"format":"json"}))
    cm_pace()
    for _,p in d.get("query",{}).get("pages",{}).items():
        ii=p.get("imageinfo",[{}]); info=ii[0] if ii else {}
        ext=info.get("extmetadata",{})
        return {"url":info.get("url"),"thumburl":info.get("thumburl"),"mime":info.get("mime"),
                "lic":(ext.get("LicenseShortName",{}) or {}).get("value",""),
                "license":(ext.get("License",{}) or {}).get("value",""),
                "usage":(ext.get("UsageTerms",{}) or {}).get("value",""),
                "artist":(ext.get("Artist",{}) or {}).get("value","")}
    return {}

def is_free(info):
    blob=" ".join(str(info.get(k,"")) for k in ("lic","license","usage"))
    return bool(FREE_RE.search(blob))

def strip_html(s): return re.sub(r"<[^>]+>","",s or "").strip()

def verify(url):
    for _ in range(4):
        try:
            req=urllib.request.Request(url, headers={"User-Agent":UA,"Range":"bytes=0-2047"})
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.status in (200,206) and r.headers.get("Content-Type","").startswith("image/")
        except urllib.error.HTTPError as e:
            if e.code==429: time.sleep(random.uniform(15,20)); continue
            return False
        except Exception:
            time.sleep(random.uniform(3,6))
    return False

def download_png(info, dest):
    url=info.get("thumburl") or info.get("url")
    for _ in range(4):
        try:
            req=urllib.request.Request(url, headers={"User-Agent":UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                data=r.read()
            im=Image.open(BytesIO(data)).convert("RGBA")
            if im.width>600:
                h=int(im.height*600/im.width); im=im.resize((600,h), Image.LANCZOS)
            im.save(dest,"PNG")
            return True
        except urllib.error.HTTPError as e:
            if e.code==429: time.sleep(random.uniform(15,20)); continue
            return False
        except Exception as e:
            print(f"    [dl err {e}]",file=sys.stderr); time.sleep(random.uniform(3,6))
    return False

def main():
    only=set(sys.argv[1:])
    manifest={}; credits={}; done=0
    for pid,name,hints in TARGETS:
        if only and pid not in only: continue
        print(f"\n##### {pid} {name} #####",file=sys.stderr)
        dest=os.path.join(OUT,f"{pid}_logo.png")
        if os.path.exists(dest):
            print("  already staged, skip",file=sys.stderr); continue
        qid,label,desc=resolve_group(name,hints)
        if not qid:
            manifest[pid]={"name":name,"available":False,"note":"Wikidata group QID未解決"}
            print("  -- QID未解決",file=sys.stderr); continue
        print(f"  QID {qid} ({label} / {desc})",file=sys.stderr)
        ent=wd_entity(qid)
        fn=p154_of(ent)
        if not fn:
            manifest[pid]={"name":name,"available":False,"qid":qid,"note":"P154(logo)無し=Wikidataにロゴ未登録"}
            print("  -- P154 無し",file=sys.stderr); continue
        info=commons_info(fn)
        if not info or not (info.get("url") or info.get("thumburl")):
            manifest[pid]={"name":name,"available":False,"qid":qid,"commons_file":fn,"note":"Commons imageinfo取得失敗"}
            print(f"  -- imageinfo失敗 {fn}",file=sys.stderr); continue
        if not is_free(info):
            manifest[pid]={"name":name,"available":False,"qid":qid,"commons_file":fn,
                           "note":f"非フリーライセンス({info.get('lic')})=採用不可"}
            print(f"  -- 非フリー {fn} ({info.get('lic')})",file=sys.stderr); continue
        vurl=info.get("thumburl") or info.get("url")
        if not verify(vurl):
            manifest[pid]={"name":name,"available":False,"qid":qid,"commons_file":fn,"note":"URL verify失敗"}
            print(f"  -- verify失敗 {fn}",file=sys.stderr); continue
        if not download_png(info, dest):
            manifest[pid]={"name":name,"available":False,"qid":qid,"commons_file":fn,"note":"DL失敗"}
            print(f"  -- DL失敗 {fn}",file=sys.stderr); continue
        credit=f"Wikimedia Commons「File:{fn}」(Wikidata {qid} P154)"
        artist=strip_html(info.get("artist"))
        if artist: credit+=f" / {artist}"
        manifest[pid]={"name":name,"available":True,"qid":qid,"commons_file":fn,
                       "license":info.get("lic") or info.get("license"),
                       "source_url":info.get("url"),"credit":credit}
        credits[pid]={"credit":credit}
        print(f"  OK {fn}  ({info.get('lic')})  via {qid} P154",file=sys.stderr)
        done+=1
        json.dump(manifest, open(os.path.join(OUT,"manifest.json"),"w"), ensure_ascii=False, indent=1)
        json.dump(credits, open(os.path.join(OUT,"import_credits.json"),"w"), ensure_ascii=False, indent=1)
    # 最終flush
    json.dump(manifest, open(os.path.join(OUT,"manifest.json"),"w"), ensure_ascii=False, indent=1)
    json.dump(credits, open(os.path.join(OUT,"import_credits.json"),"w"), ensure_ascii=False, indent=1)
    avail=sum(1 for v in manifest.values() if v.get("available"))
    print(f"\nDONE: {avail} logos staged / {len(manifest)} processed -> {OUT}",file=sys.stderr)
    print("次: human review(誤ロゴ混入チェック)後、import_logos2_verified.sh の DIR を batch_logos3 に向けて owner 実行。",file=sys.stderr)

if __name__=="__main__":
    main()
