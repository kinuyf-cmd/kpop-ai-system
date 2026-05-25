#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""solo_hero_probe.py — ソロ24組の「Wikipedia第一優先」ヒーロー写真の取得可否を偵察。

ソロは芸名が曖昧(V/Crush/DEAN/Jennie…)なため、logos4_solo_p18.py の本名ヒントを
流用して person を確定する。各候補クエリで en/ja Wikipedia のリード画像を順に試し、
person/singer らしいページのフリー画像を採用する。捏造しない(未解決はskip記録)。

出力: batch_solo_hero/probe.tsv (pid\ttitle\twikititle\tstatus\tlicense\tfree\timg\tartist)
"""
import urllib.request, urllib.parse, json, time, re, sys
UA="KpopJournalBot/1.0 (kpopjournal.biz@gmail.com) Idol-Wiki research"

# (pid, 表示名, [Wikipedia記事候補(英語優先・singer文脈付き)]) — logos4_solo_p18.py のヒント由来
TARGETS=[
 ("113","Chungha",        ["Chungha","Kim Chung-ha"]),
 ("114","Taeyeon",        ["Taeyeon","Kim Tae-yeon"]),
 ("115","IU",             ["IU (singer)","Lee Ji-eun"]),
 ("116","Jihyo",          ["Jihyo","Park Ji-hyo"]),
 ("117","Jennie",         ["Jennie (singer)","Jennie Kim"]),
 ("118","Rosé",           ["Rosé (singer)","Roseanne Park"]),
 ("119","LISA",           ["Lisa (rapper)","Lalisa Manobal"]),
 ("120","Jisoo",          ["Jisoo","Kim Ji-soo (singer, born 1995)"]),
 ("121","Jungkook",       ["Jungkook","Jeon Jung-kook"]),
 ("122","Jimin",          ["Jimin","Park Ji-min (singer, born 1995)"]),
 ("123","V",              ["V (singer)","Kim Tae-hyung"]),
 ("124","Agust D",        ["Suga (rapper)","Min Yoon-gi"]),
 ("125","WOODZ",          ["Woodz","Cho Seung-youn"]),
 ("126","Park Ji Hoon",   ["Park Ji-hoon (entertainer)","Park Ji-hoon (singer)"]),
 ("127","Jang Won Young", ["Jang Won-young","Wonyoung"]),
 ("263","ジェジュン (Jaejoong)",["Kim Jae-joong","Jaejoong"]),
 ("305","Taemin",         ["Taemin","Lee Tae-min"]),
 ("306","BoA",            ["BoA","Kwon Bo-a"]),
 ("307","Sunmi",          ["Sunmi (singer)","Lee Sun-mi"]),
 ("308","HyunA",          ["Hyuna","Kim Hyun-a"]),
 ("309","Zico",           ["Zico (rapper)","Woo Ji-ho"]),
 ("310","Crush",          ["Crush (singer)","Shin Hyo-seob"]),
 ("311","DEAN",           ["Dean (South Korean singer)","Kwon Hyuk"]),
 ("312","BIBI",           ["Bibi (singer)","Kim Hyung-seo"]),
]

def getj(url,t=25):
    req=urllib.request.Request(url,headers={"User-Agent":UA})
    with urllib.request.urlopen(req,timeout=t) as r: return json.loads(r.read())

def lead(title,lang="en"):
    api=(f"https://{lang}.wikipedia.org/w/api.php?action=query&format=json&redirects=1"
         "&titles="+urllib.parse.quote(title)+"&prop=pageimages|pageprops&piprop=original|name&pithumbsize=1200")
    try: d=getj(api)
    except Exception: return None
    for pid,pg in d.get("query",{}).get("pages",{}).items():
        if pid=="-1": return None
        return {"title":pg.get("title"),"img":(pg.get("original") or {}).get("source"),"file":pg.get("pageimage")}
    return None

def lic(file_title):
    api=("https://commons.wikimedia.org/w/api.php?action=query&format=json"
         "&titles="+urllib.parse.quote("File:"+file_title)+"&prop=imageinfo&iiprop=extmetadata")
    try: d=getj(api)
    except Exception: return {}
    for pid,pg in d.get("query",{}).get("pages",{}).items():
        ext=(pg.get("imageinfo") or [{}])[0].get("extmetadata",{})
        s=lambda k: re.sub(r"<[^>]+>","",(ext.get(k,{}) or {}).get("value","")).strip()
        return {"lic":s("LicenseShortName"),"artist":s("Artist")[:80]}
    return {}

FREE=re.compile(r"(CC|Creative Commons|Public domain|CC0|FAL|Attribution)", re.I)
out=open("batch_solo_hero/probe.tsv","w")
out.write("pid\ttitle\twikititle\tstatus\tlicense\tfree\timg\tartist\n")
nf=nn=nz=0
for pid,name,cands in TARGETS:
    found=None
    for c in cands:
        for lang in ("en","ja"):
            r=lead(c,lang); time.sleep(0.9)
            if r and r.get("img") and r.get("file"):
                l=lic(r["file"]); time.sleep(0.9)
                if FREE.search(l.get("lic","")):
                    found=(f"{lang}:{r['title']}", r["img"], l.get("lic",""), l.get("artist",""))
                    break
        if found: break
    if found:
        wt,img,license,artist=found
        free="Y"; status="has_img"; nf+=1
        line=f"{pid}\t{name}\t{wt}\t{status}\t{license}\t{free}\t{img}\t{artist}"
    else:
        status="none"; nz+=1
        line=f"{pid}\t{name}\t\t{status}\t\t\t\t"
    out.write(line+"\n"); out.flush(); print(line)
out.close()
print(f"\n=== SOLO SUMMARY: free={nf} none={nz} total={len(TARGETS)} ===", file=sys.stderr)
