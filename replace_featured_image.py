#!/usr/bin/env python3
"""指定 post の featured 画像を、指定 URL の画像で差し替える汎用ツール。

breaking パイプラインが不適切な画像(UIバナー等の顔検出誤判定)を featured に
設定してしまった記事の手当て用。

注意: lib.popup_event_to_post.download_and_attach_thumbnail は _thumbnail_id を
INSERT する(UPDATE でない)popup 専用設計。既に featured を持つ post に使うと
_thumbnail_id 行が二重になり、WP は古い行を読み続けて差し替えが効かない。
このツールは画像 DL/attachment 登録だけ既存関数に任せ、_thumbnail_id は
`wp post meta update`(冪等)で確実に張り替え、alt も正しい出典に直す。

実行(www-data で。uploads書込 + DB接続のため):
  sudo -u www-data python3 replace_featured_image.py <POST_ID> <IMAGE_URL> [SOURCE_DOMAIN]
"""
import os, sys, subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib.popup_event_to_post as P

WP_PATH = "/var/www/wp_stg"


def wp(*args):
    return subprocess.run(["wp", f"--path={WP_PATH}", *args],
                          capture_output=True, text=True, timeout=120)


def main():
    if len(sys.argv) < 3:
        print("usage: replace_featured_image.py <POST_ID> <IMAGE_URL> [SOURCE_DOMAIN]")
        return 2
    pid = int(sys.argv[1])
    url = sys.argv[2]
    src_domain = sys.argv[3] if len(sys.argv) > 3 else ""

    title = wp("post", "get", str(pid), "--field=post_title").stdout.strip()
    old_thumb = wp("post", "meta", "get", str(pid), "_thumbnail_id").stdout.strip()
    print(f"[post {pid}] {title[:50]}")
    print(f"  旧 featured attachment: {old_thumb or 'なし'}")
    print(f"  新 画像URL: {url}")

    # 画像 DL + attachment 登録(この関数の _thumbnail_id INSERT は後で上書きするので無害)
    att = P.download_and_attach_thumbnail(pid, url, {"title": title})
    if not att:
        print("  ❌ 取得/添付に失敗")
        return 1

    # _thumbnail_id を確実に張り替え(INSERT 二重を掃除して UPDATE 相当に)
    # popup関数が追加した重複行を消し、新 attachment 1本だけ残す
    wp("post", "meta", "delete", str(pid), "_thumbnail_id")
    wp("post", "meta", "add", str(pid), "_thumbnail_id", str(att))

    # alt を正しい出典に修正(popup関数は「出典: kbuzzlab.com」固定で誤り)
    if src_domain:
        alt = f"出典: {src_domain} - {title}"[:120]
        wp("post", "meta", "update", str(att), "_wp_attachment_image_alt", alt)

    # metadata 再生成(width=1 回避)
    rc = wp("media", "regenerate", str(att), "--yes", "--skip-delete")
    print(f"  metadata regenerate: {'OK' if rc.returncode == 0 else rc.stderr.strip()[:80]}")

    new_thumb = wp("post", "meta", "get", str(pid), "_thumbnail_id").stdout.strip()
    ok = (new_thumb == str(att))
    print(f"  {'✅' if ok else '❌'} featured: _thumbnail_id={new_thumb} (期待={att})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
