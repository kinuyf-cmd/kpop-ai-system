#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""group_hero_probe.py — 94グループの「Wikipedia第一優先」ヒーロー(集合)写真の取得可否を
非破壊で偵察する。DLもimportもしない。Wikipediaリード画像URL + Commonsライセンス + 出所だけ収集。

方式: 各グループ名(英Wikipedia想定)を wbsearchentities でQID候補解決→description=group/band検証→
      その英Wikipediaタイトルの prop=pageimages(original) でリード画像→Commons extmetadataで
      license/artist/credit。曖昧/未解決/画像なしは status で区別(捏造しない)。
入力: data/group_hero_targets.tsv (pid\tgroup_type\tslug\ttitle)
出力: batch_group_hero/probe.tsv  と  標準出力サマリ
"""
import urllib.request, urllib.parse, json, time, sys, re
UA="KpopJournalBot/1.0 (kpopjournal.biz@gmail.com) Idol-Wiki research"
WD="https://www.wikidata.org/w/api.php"

def get(url, timeout=25):
    req=urllib.request.Request(url, headers={"User-Agent":UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()
def getj(url, timeout=25):
    return json.loads(get(url, timeout))

GROUP_HINT=re.compile(r"\b(group|band|duo|boy band|girl group|idol|musical|south korean|k-pop|kpop)\b", re.I)

def resolve_qid(name):
    """wbsearchentities → description が group/band 等のQIDを優先採用。"""
    url=(WD+"?action=wbsearchentities&format=json&language=en&type=item&limit=7&search="
         +urllib.parse.quote(name))
    try: d=getj(url)
    except Exception as e: return None,f"wd_err:{e}"
    cands=d.get("search",[])
    if not cands: return None,"no_qid"
    # group/band らしい説明を最優先、無ければ先頭
    for c in cands:
        desc=(c.get("description") or "")
        if GROUP_HINT.search(desc):
            return c["id"], desc
    return cands[0]["id"], (cands[0].get("description") or "")

def enwiki_title_from_qid(qid):
    url=(WD+"?action=wbgetentities&format=json&props=sitelinks&ids="+qid)
    try: d=getj(url)
    except Exception: return None
    sl=d.get("entities",{}).get(qid,{}).get("sitelinks",{})
    if "enwiki" in sl: return sl["enwiki"]["title"]
    if "jawiki" in sl: return ("ja",sl["jawiki"]["title"])
    return None

def lead_image(title, lang="en"):
    api=(f"https://{lang}.wikipedia.org/w/api.php?action=query&format=json&redirects=1"
         "&titles="+urllib.parse.quote(title)+"&prop=pageimages&piprop=original|name&pithumbsize=1200")
    try: d=getj(api)
    except Exception: return None,None
    for pid,pg in d.get("query",{}).get("pages",{}).items():
        if pid=="-1": return None,None
        return (pg.get("original") or {}).get("source"), pg.get("pageimage")
    return None,None

def license_of(file_title):
    api=("https://commons.wikimedia.org/w/api.php?action=query&format=json"
         "&titles="+urllib.parse.quote("File:"+file_title)+"&prop=imageinfo&iiprop=extmetadata")
    try: d=getj(api)
    except Exception: return {}
    for pid,pg in d.get("query",{}).get("pages",{}).items():
        ii=(pg.get("imageinfo") or [{}])[0]; ext=ii.get("extmetadata",{})
        def v(k): return re.sub(r"<[^>]+>","",(ext.get(k,{}) or {}).get("value","")).strip()
        return {"lic":v("LicenseShortName"),"artist":v("Artist")[:80],"licurl":v("LicenseUrl")}
    return {}

FREE=re.compile(r"(CC|Creative Commons|Public domain|CC0|FAL)", re.I)

rows=[l.rstrip("\n").split("\t") for l in open("data/group_hero_targets.tsv") if l.strip()]
out=open("batch_group_hero/probe.tsv","w")
out.write("pid\ttitle\tqid\twikititle\tstatus\tlicense\tfree\timg\tartist\n")
n_free=n_nonfree=n_none=0
for pid,gtype,slug,title in rows:
    qid,desc=resolve_qid(title)
    time.sleep(1.1)
    status="ok"; wititle=""; img=""; lic=""; free=""; artist=""
    if not qid:
        status="no_qid"
    else:
        wt=enwiki_title_from_qid(qid); time.sleep(1.1)
        if wt is None:
            status="no_sitelink"
        else:
            lang="en"
            if isinstance(wt,tuple): lang,wt=wt
            wititle=f"{lang}:{wt}"
            img,filename=lead_image(wt,lang); time.sleep(1.0)
            if not img or not filename:
                status="no_leadimg"
            else:
                meta=license_of(filename); time.sleep(1.1)
                lic=meta.get("lic",""); artist=meta.get("artist","")
                free="Y" if FREE.search(lic) else "N"
                status="has_img"
    if status=="has_img" and free=="Y": n_free+=1
    elif status=="has_img": n_nonfree+=1
    else: n_none+=1
    line=f"{pid}\t{title}\t{qid or ''}\t{wititle}\t{status}\t{lic}\t{free}\t{img}\t{artist}"
    out.write(line+"\n"); out.flush()
    print(line)
out.close()
print(f"\n=== SUMMARY: free_img={n_free}  nonfree_img={n_nonfree}  none={n_none}  total={len(rows)} ===", file=sys.stderr)
