#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""saymyname_photos_fetch.py — SAY MY NAME(pid 262, 8人組)のメンバー個別ポートレートをステージ。

背景: SAY MY NAME は 2024 デビューの新人。Wikidata top-down(group QID Q130581752 →P527→P18)では
      P527 に 2 名(Hitomi/Mei)しか登録されず、P18 画像は Hitomi のみ(既に att 1131 で DB 投入済)。
      個別 person QID も DOHEE/KANNY/JUNHWI/SOHA/SHUIE/SEUNGJOO は Wikidata 未収録。
      => フリーライセンス源(Commons)では追加取得ゼロ。
方針: **オーナーが著作権リスクを承知の上で**、新人グループの個別ポートレートを出典明記付きで採用する判断
      (2026-05-26)。これは Idol Wiki の従来 Commons 限定ポリシーからの明示的な逸脱。
      一次情報(公式SNS/事務所 iNKODE)の写真を整理ホストしている kprofiles の個別ポートレートを取得し、
      credit に出典(kprofiles 経由 / 原権利は iNKODE)を明記する。
出力: photos_saymyname/<pid>_<idx>.jpg(300px 正方形・顔上寄り0.25クロップ)+ manifest.json + credits.json
      import_photos2_verified.sh と同じ <pid>_<idx>.jpg 構造で import 可能(DIR のみ差し替え)。

DB 順 index(pid 262, live DB 実測 2026-05-26):
  0 HITOMI / 1 DOHEE / 2 KANNY / 3 MEI / 4 JUNHWI / 5 SOHA / 6 SHUIE / 7 SEUNGJOO
idx 0(HITOMI)は att 1131 で投入済 → ステージしない(import 側でも冪等 skip)。
"""
import json, os, time, urllib.request
from io import BytesIO
from PIL import Image

UA  = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
OUT = "/home/aiuser/.kpop_recovery/photos_saymyname"
PID = "262"
SRC_PAGE = "https://kprofiles.com/say-my-name-members-profile/"
BASE = "https://kprofiles.com/wp-content/uploads/2024/08"

# (DB index, member_name, source filename) — idx 0 HITOMI は投入済みのため除外
TARGETS = [
    (1, "DOHEE",    "dohee3.jpg"),
    (2, "KANNY",    "kanny3.jpg"),
    (3, "MEI",      "mei4.jpg"),
    (4, "JUNHWI",   "junhwi3.jpg"),
    (5, "SOHA",     "soha4.jpg"),
    (6, "SHUIE",    "shuie3.jpeg"),
    (7, "SEUNGJOO", "seungjoo3-2.jpg"),
]

os.makedirs(OUT, exist_ok=True)


def crop_square_300(data, dest):
    im = Image.open(BytesIO(data)).convert("RGB")
    w, h = im.size
    side = min(w, h)
    left = (w - side) // 2
    top = int((h - side) * 0.25) if h > w else (h - side) // 2
    im.crop((left, top, left + side, top + side)).resize((300, 300), Image.LANCZOS).save(
        dest, "JPEG", quality=88
    )


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def main():
    mpath = os.path.join(OUT, "manifest.json")
    cpath = os.path.join(OUT, "credits.json")
    manifest = []
    credits = {}
    got = 0
    for idx, name, fname in TARGETS:
        url = f"{BASE}/{fname}"
        dest = os.path.join(OUT, f"{PID}_{idx}.jpg")
        try:
            data = fetch(url)
            crop_square_300(data, dest)
            manifest.append({"index": idx, "member_name": name, "available": True,
                             "source_file": fname, "source_url": url})
            credits[str(idx)] = {
                "member_name": name,
                "source_url": url,
                "credit": f"出典: kprofiles.com 経由（原権利: iNKODE 公式 / {SRC_PAGE}）",
            }
            got += 1
            print(f"  OK [{idx}] {name:10} <- {fname}")
            time.sleep(2.0)
        except Exception as e:
            manifest.append({"index": idx, "member_name": name, "available": False})
            print(f"  FAIL [{idx}] {name}: {e}")
    # ヘッダにグループ単位の credit 文も残す(import 側が組ごと1回入れる用)
    credits["_group_credit"] = (
        "メンバー写真: kprofiles.com 経由（原権利: SAY MY NAME 公式 / iNKODE）"
    )
    json.dump({PID: manifest}, open(mpath, "w"), ensure_ascii=False, indent=1)
    json.dump({PID: credits}, open(cpath, "w"), ensure_ascii=False, indent=1)
    print(f"\nDONE: {got}/{len(TARGETS)} staged -> {OUT}")


if __name__ == "__main__":
    main()
