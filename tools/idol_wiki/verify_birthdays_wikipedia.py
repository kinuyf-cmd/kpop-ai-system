#!/usr/bin/env python3
"""Idol Wiki メンバー誕生日を Wikipedia 生wikitext と照合(点検専用・非破壊)。

使い方: python3 verify_birthdays_wikipedia.py <slug1> <slug2> ...
  /tmp/idol_current_data.json の現値と、日本語版Wikipedia の
  {{生年月日と年齢|Y|M|D}} テンプレ抽出を突合し、ズレのある組だけ報告する。

設計(誤検出を避ける保守ロジック):
  - メンバーのハングル名(이나경 等)を wikitext で探し、直後250字の生年月日テンプレを採る
  - Wikipedia にページ/テンプレが無い、ハングル名が引けない → 「判定不能(skip)」とし誤として報告しない
  - 年が一致し月日だけ違う場合のみ「mismatch」(別人誤マッチを避けるため年一致を必須化)
  - 書き込みは一切しない。報告のみ。
"""
import json
import re
import sys
import urllib.parse
import urllib.request

UA = {'User-Agent': 'Mozilla/5.0 (kpopjournal-data-audit; contact owner)'}


def fetch_wikitext(page: str) -> str | None:
    try:
        url = ("https://ja.wikipedia.org/w/api.php?action=parse&page="
               + urllib.parse.quote(page)
               + "&prop=wikitext&format=json&formatversion=2&redirects=1")
        d = json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=25))
        return d.get('parse', {}).get('wikitext')
    except Exception:
        return None


def bday_from_wikitext(wt: str, ko_name: str):
    """ハングル名近傍の生年月日テンプレ or プレーン日付を (Y,M,D) で返す。無ければ None。"""
    if not wt or not ko_name:
        return None
    m = re.search(re.escape(ko_name), wt)
    if not m:
        return None
    seg = wt[m.start():m.start() + 280]
    t = re.search(r'生年月日と年齢\|\s*(\d{4})\|\s*(\d{1,2})\|\s*(\d{1,2})', seg)
    if not t:
        t = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', seg)
    if t:
        return (int(t.group(1)), int(t.group(2)), int(t.group(3)))
    return None


def check_group(g: dict) -> dict:
    """1組を照合。mismatch/unverifiable のメンバーをリストで返す。"""
    title = g['title']
    # グループ記事の wikitext を1回取得して全メンバーを照合
    wt = fetch_wikitext(g['name_ko'] or title) or fetch_wikitext(title)
    result = {'slug': g['slug'], 'pid': g['pid'], 'title': title,
              'mismatches': [], 'unverifiable': 0, 'ok': 0}
    if not wt:
        result['page_missing'] = True
        return result
    for mem in g['members']:
        cur = mem['bday']  # YYYYMMDD or ''
        # メンバーのハングル名を members メタからは取れないので、現在値の name から
        # ハングル部分を抽出(例 "NAGYUNG (나경)")
        ko = None
        km = re.search(r'([가-힣]{2,})', mem['name'])
        if km:
            ko = km.group(1)
        wp = bday_from_wikitext(wt, ko) if ko else None
        if not cur or len(cur) != 8 or not wp:
            result['unverifiable'] += 1
            continue
        cy, cm, cd = int(cur[:4]), int(cur[4:6]), int(cur[6:8])
        wy, wm, wd = wp
        # 年一致を必須(別人誤マッチ回避)。月日だけ違えば mismatch。
        if cy == wy and (cm, cd) != (wm, wd):
            result['mismatches'].append({
                'member': mem['name'],
                'current': f'{cy:04d}-{cm:02d}-{cd:02d}',
                'wikipedia': f'{wy:04d}-{wm:02d}-{wd:02d}',
            })
        elif (cy, cm, cd) == (wy, wm, wd):
            result['ok'] += 1
        else:
            # 年も違う = 別人誤マッチの可能性 → unverifiable 扱いで人手確認に回す
            result['unverifiable'] += 1
    return result


def main():
    slugs = set(sys.argv[1:])
    data = json.load(open('/tmp/idol_current_data.json'))
    targets = [g for g in data if not slugs or g['slug'] in slugs]
    report = []
    for g in targets:
        if not any(m['bday'] for m in g['members']):
            continue  # 誕生日データ無しはスキップ
        report.append(check_group(g))
    # mismatch のある組だけ出力
    flagged = [r for r in report if r['mismatches']]
    print(json.dumps({'checked': len(report), 'flagged': flagged}, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
