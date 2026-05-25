#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""logos4_solo_p18.py — ソロK-popアーティスト25組(画像ゼロ・members=0)の本人ポートレートを
Wikidata P18 で本人確定取得し、logo_image スロット用に 600px 正規化PNGでステージ。

背景: ソロは members=0 でメンバー写真リピータを持たない。オーナー決定により本人写真は
logo_image フィールドに入れる(スキーマ変更なし)。芸名は wbsearchentities で曖昧
(V→Vietnam, Crush→Jennifer Paige曲, DEAN→人名)なため、本名/別名ヒントで person QID を確定。

方式 : resolve_person(芸名+本名ヒント) -> person QID(description=Korean+singer/rapper/idol等で検証)
        -> wbgetentities -> claims.P18(image) -> Commons free-license検証 -> verify -> 600px PNG。
        解決不能 / P18無し / 非フリー は available:false でスキップ(捏造しない)。
出力 : batch_solo_portraits/<pid>_logo.png + manifest.json + import_credits.json
        (import_logos2_verified.sh と同じ <pid>_logo.png 構造で import 可能)
レート: Wikidata 1.0-1.5s / Commons・DL 3.0-3.5s、429/HTML で15-20sバックオフ。
引数 : 対象pidを絞れる  python3 logos4_solo_p18.py 115 117 119
"""
import json, sys, time, random, re, os, urllib.parse, urllib.request
from io import BytesIO
from PIL import Image

UA  = "KpopJournalBot/1.0 (kpopjournal.biz@gmail.com) Idol-Wiki research"
WD  = "https://www.wikidata.org/w/api.php"
CM  = "https://commons.wikimedia.org/w/api.php"
OUT = "/home/aiuser/.kpop_recovery/batch_solo_portraits"
os.makedirs(OUT, exist_ok=True)

# (pid, 主芸名, [本名/別名/文脈ヒント]) — ヒントは曖昧芸名のQID確定用。
TARGETS = [
 ("113","Chungha",        ["Kim Chung-ha", "Chungha singer"]),
 ("114","Taeyeon",        ["Kim Tae-yeon", "Taeyeon Girls' Generation"]),
 ("115","IU",             ["Lee Ji-eun", "IU singer"]),
 ("116","Jihyo",          ["Park Ji-hyo", "Jihyo Twice"]),
 ("117","Jennie",         ["Jennie Kim", "Jennie Blackpink"]),
 ("118","Rosé",           ["Roseanne Park", "Park Chae-young", "Rosé Blackpink"]),
 ("119","Lisa",           ["Lalisa Manobal", "Lisa Blackpink"]),
 ("120","Jisoo",          ["Kim Ji-soo", "Jisoo Blackpink"]),
 ("121","Jungkook",       ["Jeon Jung-kook", "Jungkook BTS"]),
 ("122","Jimin",          ["Park Ji-min", "Jimin BTS"]),
 ("123","V",              ["Kim Tae-hyung", "V BTS singer"]),
 ("124","Agust D",        ["Min Yoon-gi", "Suga BTS", "Agust D"]),
 ("125","WOODZ",          ["Cho Seung-youn", "Woodz singer"]),
 ("126","Park Ji Hoon",   ["Park Ji-hoon singer", "Park Ji-hoon Wanna One"]),
 ("127","Jang Won Young", ["Jang Won-young", "Wonyoung IVE"]),
 ("263","Jaejoong",       ["Kim Jae-joong", "Jaejoong JYJ"]),
 ("305","Taemin",         ["Lee Tae-min", "Taemin Shinee"]),
 ("306","BoA",            ["Kwon Bo-a", "BoA singer"]),
 ("307","Sunmi",          ["Lee Sun-mi", "Sunmi singer"]),
 ("308","HyunA",          ["Kim Hyun-a", "HyunA singer"]),
 ("309","Zico",           ["Woo Ji-ho", "Zico rapper"]),
 ("310","Crush",          ["Shin Hyo-seob", "Crush South Korean singer"]),
 ("311","DEAN",           ["Kwon Hyuk", "Dean South Korean singer"]),
 ("312","BIBI",           ["Kim Hyung-seo", "Bibi South Korean singer"]),
]
# 除外: 102 PLAVE(group members=5→メンバー写真経路) / 313 AKMU(duo members=0スキーマ不整合→別扱い)

FREE_RE = re.compile(r"(public domain|pd-|cc[-\s]?(by|zero|0)|cc0|creative commons)", re.I)
PERSON_WORDS = ("singer","rapper","idol","songwriter","dancer","musician","actor","actress","artist","member")
KO_WORDS = ("korean","k-pop","kpop","south korea")

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

def resolve_person(stage, hints):
    """description が Korean + person(singer等)を含む人物のみ採用=同名の地名/曲/外国人を排除。
       芸名bare→芸名+singer→本名ヒント の順で試す。"""
    tries=[stage, f"{stage} singer", f"{stage} rapper", f"{stage} South Korean singer"]+hints
    seen=set()
    # 一段目: Korean + person 両方を要求(厳格)
    for q in tries:
        for r in wd_search(q):
            qid=r["id"]
            if qid in seen: continue
            seen.add(qid)
            d=(r.get("description","") or "").lower()
            if any(w in d for w in PERSON_WORDS) and any(k in d for k in KO_WORDS):
                return qid, r.get("label"), r.get("description")
    # 二段目: 本名ヒント由来で person 語だけでも採用(本名はそもそも一意性が高い)
    for q in hints:
        for r in wd_search(q):
            d=(r.get("description","") or "").lower()
            if any(w in d for w in PERSON_WORDS):
                return r["id"], r.get("label"), r.get("description")
    return None,None,None

def p18_of(ent):
    claims=ent.get("claims",{}).get("P18",[])
    claims=sorted(claims, key=lambda c: 0 if c.get("rank")=="preferred" else 1)
    for c in claims:
        try:
            if c["mainsnak"].get("snaktype")=="value":
                return c["mainsnak"]["datavalue"]["value"]
        except Exception: continue
    return None

def commons_info(filename):
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
            im=Image.open(BytesIO(data)).convert("RGB")
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
    for pid,stage,hints in TARGETS:
        if only and pid not in only: continue
        print(f"\n##### {pid} {stage} #####",file=sys.stderr)
        dest=os.path.join(OUT,f"{pid}_logo.png")
        if os.path.exists(dest):
            print("  already staged, skip",file=sys.stderr); continue
        qid,label,desc=resolve_person(stage,hints)
        if not qid:
            manifest[pid]={"name":stage,"available":False,"note":"Wikidata person QID未解決"}
            print("  -- QID未解決",file=sys.stderr); continue
        print(f"  QID {qid} ({label} / {desc})",file=sys.stderr)
        ent=wd_entity(qid)
        fn=p18_of(ent)
        if not fn:
            manifest[pid]={"name":stage,"available":False,"qid":qid,"note":"P18(image)無し"}
            print("  -- P18 無し",file=sys.stderr); continue
        info=commons_info(fn)
        if not info or not (info.get("url") or info.get("thumburl")):
            manifest[pid]={"name":stage,"available":False,"qid":qid,"commons_file":fn,"note":"imageinfo取得失敗"}
            print(f"  -- imageinfo失敗 {fn}",file=sys.stderr); continue
        if not is_free(info):
            manifest[pid]={"name":stage,"available":False,"qid":qid,"commons_file":fn,
                           "note":f"非フリー({info.get('lic')})"}
            print(f"  -- 非フリー {fn} ({info.get('lic')})",file=sys.stderr); continue
        vurl=info.get("thumburl") or info.get("url")
        if not verify(vurl):
            manifest[pid]={"name":stage,"available":False,"qid":qid,"commons_file":fn,"note":"verify失敗"}
            print(f"  -- verify失敗 {fn}",file=sys.stderr); continue
        if not download_png(info, dest):
            manifest[pid]={"name":stage,"available":False,"qid":qid,"commons_file":fn,"note":"DL失敗"}
            print(f"  -- DL失敗 {fn}",file=sys.stderr); continue
        credit=f"Wikimedia Commons「File:{fn}」(Wikidata {qid} P18)"
        artist=strip_html(info.get("artist"))
        if artist: credit+=f" / {artist}"
        manifest[pid]={"name":stage,"available":True,"qid":qid,"commons_file":fn,
                       "license":info.get("lic") or info.get("license"),
                       "source_url":info.get("url"),"credit":credit}
        credits[pid]={"credit":credit}
        print(f"  OK {fn}  ({info.get('lic')})  via {qid} P18",file=sys.stderr)
        done+=1
        json.dump(manifest, open(os.path.join(OUT,"manifest.json"),"w"), ensure_ascii=False, indent=1)
        json.dump(credits, open(os.path.join(OUT,"import_credits.json"),"w"), ensure_ascii=False, indent=1)
    json.dump(manifest, open(os.path.join(OUT,"manifest.json"),"w"), ensure_ascii=False, indent=1)
    json.dump(credits, open(os.path.join(OUT,"import_credits.json"),"w"), ensure_ascii=False, indent=1)
    avail=sum(1 for v in manifest.values() if v.get("available"))
    print(f"\nDONE: {avail} portraits staged / {len(manifest)} processed -> {OUT}",file=sys.stderr)
    print("次: human review(本人確認=同名別人混入チェック)後、batch_solo_portraits を import。",file=sys.stderr)

if __name__=="__main__":
    main()
