#!/usr/bin/env python3
"""M5補完: 取り込み済み記事にアーティスト名+トピックのタグを付与する。

タイトルからグループ名/トピックを検出してタグ付け。既存 stg のタグ taxonomy
(BTS/BLACKPINK/aespa... カムバック/速報 等)と整合する命名を使う。

タグ辞書は soompi_collector の KPOP_KW(アーティスト名)を流用 + 日本語表記。
wp-cli post term add(sudo必須=オーナー実行)。--dry-run/--apply。

使い方:
    python3 set_tags_imported.py --dry-run   # 計画(既定、sudo不要)
    sudo python3 set_tags_imported.py --apply
"""
import argparse
import subprocess

WP_PATH = "/var/www/wp_stg"

# タグ辞書: 検出キー(英/日 表記ゆれ) → 正規タグ名(既存taxonomyと整合)
ARTIST_TAGS = {
    "BTS": ["BTS", "防弾"], "BLACKPINK": ["BLACKPINK", "ブラックピンク"],
    "aespa": ["aespa", "エスパ"], "NewJeans": ["NewJeans", "ニュージーンズ"],
    "SEVENTEEN": ["SEVENTEEN", "セブチ"], "TWICE": ["TWICE"], "IVE": ["IVE", "アイブ"],
    "LE SSERAFIM": ["LE SSERAFIM", "ルセラフィム"], "ILLIT": ["ILLIT", "アイリット"],
    "ITZY": ["ITZY"], "Stray Kids": ["Stray Kids", "STRAY KIDS", "スキズ"],
    "TXT": ["TXT", "TOMORROW X TOGETHER"], "ENHYPEN": ["ENHYPEN"], "NCT": ["NCT"],
    "ATEEZ": ["ATEEZ"], "RIIZE": ["RIIZE", "ライズ"], "KATSEYE": ["KATSEYE"],
    "BABYMONSTER": ["BABYMONSTER", "ベイビモン"], "NMIXX": ["NMIXX"],
    "KISS OF LIFE": ["KISS OF LIFE"], "TREASURE": ["TREASURE"], "PLAVE": ["PLAVE"],
    "STAYC": ["STAYC"], "ONF": ["ONF"], "RESCENE": ["RESCENE"],
    "Hearts2Hearts": ["Hearts2Hearts"], "AKMU": ["AKMU"], "TOP": ["T.O.P", "TOP"],
    "Mark Lee": ["Mark Lee", "マーク"], "Super Junior": ["Super Junior", "スーパージュニア"],
}
TOPIC_TAGS = {
    "カムバック": ["カムバック", "comeback", "新譜", "ミニアルバム", "アルバム"],
    "ツアー": ["ツアー", "ワールドツアー", "tour", "コンサート"],
    "Billboard": ["Billboard", "ビルボード", "Hot 100"],
    "兵役": ["兵役", "入隊", "除隊"],
}


def wp(args):
    cmd = ["sudo", "-u", "www-data", "wp", "--path=" + WP_PATH] + args
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    return r.stdout.strip(), r.stderr.strip(), r.returncode


def tags_for(title):
    tags = []
    for canon, keys in ARTIST_TAGS.items():
        if any(k.lower() in title.lower() for k in keys):
            tags.append(canon)
    for canon, keys in TOPIC_TAGS.items():
        if any(k.lower() in title.lower() for k in keys):
            tags.append(canon)
    return tags


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not args.apply:
        # dry-run: stg DB に依存せず、本番静的HTMLのタイトルでは確認しづらいので
        # apply時に wp post list でタイトル取得する。ここでは辞書を提示。
        print("[DRY] タグ辞書(検出→正規タグ):")
        print(f"  アーティスト: {len(ARTIST_TAGS)}組 ({', '.join(list(ARTIST_TAGS)[:8])}...)")
        print(f"  トピック: {', '.join(TOPIC_TAGS)}")
        print("[DRY] apply時: draft各記事のタイトルからタグ検出 → wp post term add")
        return

    out, _, _ = wp(["post", "list", "--post_type=post", "--post_status=draft",
                    "--fields=ID,post_title", "--format=csv"])
    lines = out.splitlines()[1:]  # ヘッダ除く
    done = notag = 0
    for line in lines:
        parts = line.split(",", 1)
        if len(parts) < 2:
            continue
        pid, title = parts[0], parts[1].strip('"')
        tags = tags_for(title)
        if not tags:
            notag += 1
            continue
        o, e, rc = wp(["post", "term", "add", pid, "post_tag"] + tags)
        if rc == 0:
            print(f"OK  post {pid}: {', '.join(tags)}  ({title[:30]})")
            done += 1
        else:
            print(f"ERR post {pid}: {e[:80]}")
    print(f"\n=== タグ付与: {done}件 / タグなし {notag}件 ===")


if __name__ == "__main__":
    main()
