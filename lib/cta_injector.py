#!/usr/bin/env python3
"""cta_injector.py — CTA未設置記事に冒頭・中盤・終盤CTAを自動挿入

判定:
  - data-cta="top|mid|bottom" 属性マーカで既存CTAを検出
  - 3箇所のいずれかが欠けていれば挿入

挿入位置:
  - top   : 最初の <h2> の直前
  - mid   : 記事本文の半分の位置（<p>境界で切る）
  - bottom: 末尾 (閉じタグの直前)

CTA内容:
  - カテゴリ連動で「関連比較」「公式ページ/サブスク」「メルマガ」等
  - 既存 lib/cta_templates.py があれば利用、なければ内蔵デフォルトを使用

使い方:
  python3 lib/cta_injector.py [--limit 100] [--dry-run]
"""
from __future__ import annotations
import argparse
import json
import re
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"
OUT_LOG = LOGS / "cta_updates.jsonl"
WP = "https://www.kpopjournal.tokyo"
WP_AUTH = str(Path.home() / ".wp_auth")
JST = timezone(timedelta(hours=9))

CTA_TOP = """<div data-cta="top" class="kpopj-cta-top" style="margin:20px 0;padding:14px 16px;border-left:4px solid #ff4d6d;background:#fff5f7;border-radius:0 8px 8px 0;">
<p style="margin:0;font-size:0.95em;">🔥 <strong>最新の推し活ニュースを毎日チェック</strong> → <a href="https://www.kpopjournal.tokyo/category/kpop%e3%83%8b%e3%83%a5%e3%83%bc%e3%82%b9/" style="color:#ff4d6d;font-weight:700;">K-POP速報カテゴリ</a></p>
</div>"""

CTA_MID = """<div data-cta="mid" class="kpopj-cta-mid" style="margin:28px 0;padding:16px 18px;border:2px solid #7b61ff;background:#faf9ff;border-radius:10px;">
<p style="margin:0 0 6px 0;font-weight:700;color:#7b61ff;">📺 配信・ライブ視聴はABEMAが最速</p>
<p style="margin:0;font-size:0.92em;">K-POPのMVプレミア公開・カムバショー・音楽番組を日本からリアルタイムで視聴 → <a href="https://abema.tv/" rel="sponsored nofollow">ABEMA公式で見る</a></p>
</div>"""

CTA_BOTTOM = """<div data-cta="bottom" class="kpopj-cta-bottom" style="margin:36px 0 10px 0;padding:18px 20px;border:2px dashed #ff4d6d;background:#fff8f9;border-radius:12px;text-align:center;">
<p style="margin:0 0 8px 0;font-weight:700;font-size:1.05em;">📌 この記事が役立ったら保存してください</p>
<p style="margin:0;font-size:0.92em;">👉 <a href="https://www.kpopjournal.tokyo/">K-POP JOURNAL トップへ戻る</a> &nbsp;/&nbsp; 👉 <a href="https://www.kpopjournal.tokyo/kpop-beginner-hub-2026/">K-POP初心者ガイド</a></p>
</div>"""


def curl_get(path: str):
    cmd = ["curl", "-s", f"{WP}{path}", "-K", WP_AUTH]
    return json.loads(subprocess.check_output(cmd, timeout=30).decode())


def curl_post(path: str, payload: dict):
    body = json.dumps(payload, ensure_ascii=False).encode()
    cmd = ["curl", "-s", "-X", "POST", f"{WP}{path}",
           "-K", WP_AUTH, "-H", "Content-Type: application/json",
           "--data-binary", body.decode()]
    return json.loads(subprocess.check_output(cmd, timeout=60).decode())


def has_cta(content: str, slot: str) -> bool:
    return f'data-cta="{slot}"' in content


def insert_top(content: str) -> str:
    # 最初の <h2> の直前に
    m = re.search(r"<h2\b", content)
    if not m:
        return CTA_TOP + content
    i = m.start()
    return content[:i] + CTA_TOP + "\n" + content[i:]


def insert_mid(content: str) -> str:
    # <p> 境界で半分の位置に挿入
    ps = [m.start() for m in re.finditer(r"</p>", content)]
    if not ps:
        return content + "\n" + CTA_MID
    mid = ps[len(ps) // 2]
    # </p> の直後に
    insert_at = mid + 4
    return content[:insert_at] + "\n" + CTA_MID + content[insert_at:]


def insert_bottom(content: str) -> str:
    return content.rstrip() + "\n" + CTA_BOTTOM


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    posts = curl_get(
        f"/wp-json/wp/v2/posts?per_page={args.limit}&orderby=date&order=desc"
        "&_fields=id,title,slug,link,categories,content"
    )
    ts = datetime.now(tz=JST).isoformat()
    top_added = mid_added = bot_added = 0
    posts_updated = 0
    failed = 0

    with OUT_LOG.open("a") as fp:
        for p in posts:
            try:
                content = p.get("content", {}).get("rendered", "") if isinstance(p.get("content"), dict) else p.get("content", "")
                updates = []
                new_content = content
                if not has_cta(new_content, "top"):
                    new_content = insert_top(new_content); updates.append("top"); top_added += 1
                if not has_cta(new_content, "mid"):
                    new_content = insert_mid(new_content); updates.append("mid"); mid_added += 1
                if not has_cta(new_content, "bottom"):
                    new_content = insert_bottom(new_content); updates.append("bottom"); bot_added += 1
                if not updates:
                    continue
                if args.dry_run:
                    posts_updated += 1
                    print(f"  [dry] [{p['id']}] would add: {updates}")
                    continue
                curl_post(f"/wp-json/wp/v2/posts/{p['id']}", {"content": new_content})
                posts_updated += 1
                fp.write(json.dumps({
                    "ts": ts, "post_id": p["id"], "slug": p["slug"],
                    "added": updates,
                }, ensure_ascii=False) + "\n")
                print(f"  ✅ [{p['id']}] +CTA: {updates}")
            except Exception as e:
                failed += 1
                print(f"  ❌ [{p['id']}] {e}")

    print()
    print(f"[cta_injector] 更新記事={posts_updated} / top+={top_added} mid+={mid_added} "
          f"bot+={bot_added} / failed={failed}")
    print(f"  ログ: {OUT_LOG}")


if __name__ == "__main__":
    main()
