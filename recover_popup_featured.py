#!/usr/bin/env python3
"""featured image が欠落した popup記事に A+F方式で featured を復活させる(教訓#68 / Phase28)。

既存の lib/popup_event_to_post.download_and_attach_thumbnail() を再利用:
  popup_source_url(ACF) → 出典ページの og:image → uploads複製 → attachment登録 → _thumbnail_id。
出典明記(alt「出典: kbuzzlab.com - <title>」)も既存関数が付与。

実行(www-data で。uploads書込 + DB接続のため):
  確認(サンプル1件): sudo -u www-data DRY_RUN=0 LIMIT=1 python3 recover_popup_featured.py
  全件(20件):       sudo -u www-data DRY_RUN=0 LIMIT=0 python3 recover_popup_featured.py
  dry-run(取得せず計画のみ): sudo -u www-data DRY_RUN=1 python3 recover_popup_featured.py

冪等: 既に _thumbnail_id がある popup はスキップ。失敗(取得不可等)はスキップして継続。
"""
import os, sys, re, urllib.request, subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib.popup_event_to_post as P   # DB creds は import 時に自己ロード

LIMIT = int(os.environ.get("LIMIT", "1"))   # 既定はサンプル1件
WP_PATH = "/var/www/wp_stg"

HEADERS = {"meta_value", "ID", "post_title", "post_status"}

def mysql(sql):
    """run_mysql は `mysql -e` 形式で、出力がある時は必ず1行目に列名ヘッダが付く。
    そのヘッダ行を除去して値だけ返す(空結果は空文字)。"""
    out = P.run_mysql(sql)
    lines = out.splitlines()
    if lines and lines[0].strip() in HEADERS:
        lines = lines[1:]
    return "\n".join(lines).strip()

def og_image_of(url):
    """出典ページの og:image を取得。"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "KpopJournalBot/1.0 (+https://www.kpopjournal.tokyo/about; research)"})
        with urllib.request.urlopen(req, timeout=20) as r:
            html = r.read(400000).decode("utf-8", "ignore")
    except Exception as e:
        print(f"    出典取得失敗: {e}"); return ""
    m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', html)
    if not m:
        m = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', html)
    return m.group(1) if m else ""

def main():
    # popup category の publish 投稿 ID 一覧
    ids = mysql(
        "SELECT p.ID FROM wp_posts p "
        "JOIN wp_term_relationships tr ON p.ID=tr.object_id "
        "JOIN wp_term_taxonomy tt ON tr.term_taxonomy_id=tt.term_taxonomy_id "
        "JOIN wp_terms t ON tt.term_id=t.term_id "
        "WHERE t.slug='popup' AND tt.taxonomy='category' "
        "AND p.post_type='post' AND p.post_status='publish' ORDER BY p.ID DESC;"
    )
    ids = [l.strip() for l in ids.splitlines() if l.strip().isdigit()]
    print(f"=== popup publish: {len(ids)}件 / DRY_RUN={P.DRY_RUN} LIMIT={LIMIT} ===")

    done = 0
    for pid in ids:
        # featured 有ならスキップ(冪等)
        tid = mysql(f"SELECT meta_value FROM wp_postmeta WHERE post_id={pid} AND meta_key='_thumbnail_id' LIMIT 1;")
        if tid.strip():
            continue
        # 出典URL(ACF popup_source_url)
        src = mysql(f"SELECT meta_value FROM wp_postmeta WHERE post_id={pid} AND meta_key='popup_source_url' LIMIT 1;").strip()
        title = mysql(f"SELECT post_title FROM wp_posts WHERE ID={pid} LIMIT 1;").strip()
        print(f"\n[popup {pid}] {title[:40]}")
        if not src:
            print("    SKIP: popup_source_url なし(ケースC)"); continue
        print(f"    source: {src}")
        ogimg = og_image_of(src)
        if not ogimg:
            print("    SKIP: 出典 og:image 取得不可"); continue
        print(f"    og:image: {ogimg}")
        # 既存 A+F 関数で複製+featured(sig は title のみ必要)
        att = P.download_and_attach_thumbnail(int(pid), ogimg, {"title": title})
        if att:
            done += 1
            print(f"    ✅ featured set: attachment={att}")
        if LIMIT and done >= LIMIT:
            print(f"\n=== LIMIT={LIMIT} 到達。停止(サンプル確認用)===")
            break
    print(f"\n=== 完了: {done}件に featured 設定 ===")

if __name__ == "__main__":
    main()
