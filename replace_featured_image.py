#!/usr/bin/env python3
"""指定 post の featured 画像を、指定 URL の画像で差し替える汎用ツール。

breaking パイプラインが不適切な画像(UIバナー等の顔検出誤判定)を featured に
設定してしまった記事の手当て用。download_and_attach_thumbnail を再利用し、
出典ドメインを alt に正しく反映する。

実行(www-data で。uploads書込 + DB接続のため):
  sudo -u www-data python3 replace_featured_image.py <POST_ID> <IMAGE_URL> [SOURCE_DOMAIN]

新 attachment を featured にセットし直す(旧 attachment は残すが _thumbnail_id を更新)。
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

    # alt 用に出典ドメインを title 経由で渡す(関数は sig['title'] を alt に使う)
    sig_title = f"{title}" if not src_domain else f"{src_domain} - {title}"
    att = P.download_and_attach_thumbnail(pid, url, {"title": sig_title})
    if not att:
        print("  ❌ 取得/添付に失敗")
        return 1
    # metadata 再生成(width=1 回避)
    rc = wp("media", "regenerate", str(att), "--yes", "--skip-delete")
    print(f"  metadata regenerate: {'OK' if rc.returncode == 0 else rc.stderr.strip()[:80]}")
    new_thumb = wp("post", "meta", "get", str(pid), "_thumbnail_id").stdout.strip()
    print(f"  ✅ featured 差し替え完了: {old_thumb} → {new_thumb} (attachment={att})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
