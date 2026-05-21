#!/usr/bin/env python3
"""サムネイル一括設定スクリプト"""
import subprocess, urllib.request, json, re, os, time

WP_API = "https://www.kpopjournal.tokyo/wp-json/wp/v2"
MEDIA_API = f"{WP_API}/media"
with open(os.path.expanduser("~/.wp_auth")) as f:
    for line in f:
        m = re.match(r'header\s*=\s*"Authorization:\s*Basic\s+([^"]+)"', line.strip())
        if m:
            token = m.group(1).strip(); break

articles = [
    {"id": 2432, "text": "K-POPとは？\n初心者ガイド\n2026年版"},
    {"id": 2433, "text": "カムバックとは\n活動サイクル\n入門ガイド"},
    {"id": 2434, "text": "音楽番組の\n仕組みを\n解説"},
    {"id": 2435, "text": "Weverse\n使い方\n入門"},
    {"id": 2436, "text": "ライブ初\n参戦ガイド\nK-POP"},
    {"id": 2437, "text": "K-POP世代\n1〜5世代\nガイド"},
    {"id": 2438, "text": "推し活入門\nファンダム\n応援文化"},
    {"id": 2439, "text": "韓国語なし\nでK-POPを\n楽しむ方法"},
    {"id": 2440, "text": "事務所入門\nHYBE SM\nJYP YG"},
    {"id": 2441, "text": "ABEMA\nLemino\n入門ガイド"},
    {"id": 2442, "text": "K-POP入門\nガイドまとめ\n2026年版"},
]

BASE = "/home/aiuser/kpop-ai-system"
results = []

for art in articles:
    pid = art["id"]
    text = art["text"]
    print(f"\n[post_id={pid}] サムネ生成中: {text[:20].replace(chr(10),' ')}...")

    # サムネ生成
    result = subprocess.run(
        ["python3", "make_thumbnail.py", text, "--genre", "live"],
        cwd=BASE, capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"  ERROR 生成失敗: {result.stderr[:100]}")
        results.append({"post_id": pid, "media_id": None, "error": "thumb_gen_failed"})
        continue

    # WPにアップロード
    thumb_path = os.path.join(BASE, "thumbnail.webp")
    with open(thumb_path, "rb") as tf:
        thumb_data = tf.read()

    upload_req = urllib.request.Request(
        MEDIA_API,
        data=thumb_data,
        headers={
            "Authorization": f"Basic {token}",
            "Content-Disposition": f'attachment; filename="thumb-beginner-{pid}.webp"',
            "Content-Type": "image/webp"
        },
        method="POST"
    )
    try:
        with urllib.request.urlopen(upload_req, timeout=30) as resp:
            media = json.loads(resp.read())
            media_id = media["id"]
            print(f"  アップロード完了: media_id={media_id}")
    except Exception as e:
        print(f"  ERROR アップロード失敗: {e}")
        results.append({"post_id": pid, "media_id": None, "error": str(e)})
        continue

    # 記事にfeatured_media設定
    update_data = json.dumps({"featured_media": media_id}, ensure_ascii=False).encode("utf-8")
    update_req = urllib.request.Request(
        f"{WP_API}/posts/{pid}",
        data=update_data,
        headers={
            "Authorization": f"Basic {token}",
            "Content-Type": "application/json; charset=utf-8"
        },
        method="POST"
    )
    try:
        with urllib.request.urlopen(update_req, timeout=30) as resp:
            d = json.loads(resp.read())
            print(f"  featured_media 設定完了: {d['featured_media']}")
            results.append({"post_id": pid, "media_id": d['featured_media']})
    except Exception as e:
        print(f"  ERROR featured_media設定失敗: {e}")
        results.append({"post_id": pid, "media_id": media_id, "error": f"set_failed:{e}"})

    time.sleep(1)

print("\n\n=== サムネ設定結果 ===")
for r in results:
    status = "OK" if r.get("media_id") and not r.get("error") else f"NG:{r.get('error')}"
    print(f"post_id={r['post_id']} media_id={r.get('media_id')} [{status}]")

with open("/tmp/beginner_thumb_results.json", "w") as f:
    json.dump(results, f, indent=2)
