#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""thumbnail_audit.py — 本番記事の生成サムネ(thumb_*.jpg)を一覧化し、無関係画像の疑いを洗い出す。
RED TEAM監査(2026-05-25)で、thumbnail_resolver の顔fallbackが OSEN等の関連ニュース
サイドバーの別アーティスト顔を誤採用していた事故を発見(TREASUREに女性、LE SSERAFIMに男性等)。

本ツールは: sitemap全記事 → og:image収集 → 生成サムネ(thumb_*)を抽出 → 寸法/圧縮率で
機械フラグ(低解像・高圧縮)+ コンタクトシート画像を生成し、人間が被写体関連性を目視判定する。
完全自動の被写体判定はしない(性別/メンバー数照合は誤判定リスク)。目視ゲート前提。

出力: /tmp/thumb_audit/contact_sheet.png(ラベル付き一覧)+ flags.json
使い方: python3 tools/audit/thumbnail_audit.py
"""
import urllib.request, re, time, json, os
from io import BytesIO
from PIL import Image, ImageDraw

SITE="https://www.kpopjournal.tokyo"
UA={'User-Agent':'KpopJournalBot/1.0 thumbnail-audit'}
OUT="/tmp/thumb_audit"; os.makedirs(OUT, exist_ok=True)
LOC=re.compile(r'<loc>\s*(?:<!\[CDATA\[)?\s*([^<\]]+?)\s*(?:\]\]>)?\s*</loc>',re.I)

def fetch(u):
    try: return urllib.request.urlopen(urllib.request.Request(u,headers=UA),timeout=20).read()
    except: return b''

def fetch_text(u): return fetch(u).decode('utf-8','replace')

def collect_posts():
    sm=fetch_text(f"{SITE}/sitemap.xml"); posts=set()
    for s in [u for u in LOC.findall(sm) if u.endswith('.xml')]:
        for u in LOC.findall(fetch_text(s)):
            if not u.endswith('.xml') and '/category/' not in u and u.rstrip('/').count('/')>=3:
                posts.add(u)
        time.sleep(0.12)
    return sorted(posts)

def main():
    posts=collect_posts()
    print(f"記事 {len(posts)} 件、生成サムネ(thumb_*)を抽出中…")
    gen=[]
    for i,u in enumerate(posts):
        h=fetch_text(u)
        og=re.search(r'<meta property="og:image" content="([^"]*)"', h)
        if og and 'thumb_' in og.group(1):
            gen.append({'url':u.replace(SITE+'/',''), 'thumb':og.group(1)})
        if i%40==0: print(f"  {i+1}/{len(posts)}", flush=True)
        time.sleep(0.07)
    print(f"生成サムネ記事 {len(gen)} 件 → 寸法/圧縮フラグ + コンタクトシート")

    cw,ch,cols=300,180,3
    rows_n=(len(gen)+cols-1)//cols
    sheet=Image.new('RGB',(cw*cols, ch*rows_n),(20,20,24)); d=ImageDraw.Draw(sheet)
    flags=[]
    for i,r in enumerate(gen):
        data=fetch(r['thumb'])
        if not data: continue
        try: im=Image.open(BytesIO(data)); w,hh=im.size
        except: continue
        bpp=len(data)/(w*hh) if w*hh else 0
        fl=[]
        if w<1200 or hh<630: fl.append('低解像')
        if bpp<0.10: fl.append('高圧縮')
        r['size']=[w,hh]; r['bpp']=round(bpp,3); r['flags']=fl
        flags.append(r)
        x=(i%cols)*cw; y=(i//cols)*ch
        sheet.paste(im.convert('RGB').resize((cw,ch-20)),(x,y))
        slug=r['url'].rstrip('/').split('/')[-1][:30]
        d.rectangle([x,y+ch-20,x+cw,y+ch],fill=(0,0,0))
        d.text((x+3,y+ch-16),f"t{i:02d} {slug} {'/'.join(fl)}",fill=(255,230,120) if fl else (255,255,255))
    sheet.save(f"{OUT}/contact_sheet.png")
    json.dump(flags, open(f"{OUT}/flags.json",'w'), ensure_ascii=False, indent=1)
    fcount=sum(1 for r in flags if r['flags'])
    print(f"\n機械フラグ(低解像/高圧縮): {fcount} 件")
    for r in flags:
        if r['flags']: print(f"  {r['url'][:48]:<50} {r['size']} {r['flags']}")
    print(f"\nコンタクトシート: {OUT}/contact_sheet.png ← 被写体の関連性は目視で判定")
    print("(被写体が記事のアーティストと一致するか=性別/メンバー数/別人混入を人間がチェック)")

if __name__=="__main__":
    main()
