#!/usr/bin/env python3
"""popup_thumbnail_backfill.py — 公開済 popup のサムネ(featured_image)一括設定

背景(2026-06-15):
  滞留 draft を是正・公開した 21 件はサムネ未設定。各 source_url の og:image は
  全件取得可能だが、保存先 /var/www/wp_stg/wp-content/uploads は www-data 所有で
  aiuser からは書けない。→ 本スクリプトは **owner が sudo で実行**する想定。

処理(popup タグ + publish + _thumbnail_id 無し の各記事):
  1. popup_source_url の詳細ページから og:image / og:title を取得
  2. lib.download_and_attach_thumbnail で uploads 複製 + attachment 登録 +
     _thumbnail_id セット(画質維持・既存パイプライン再利用)

冪等: 既に _thumbnail_id がある記事はスキップ。DRY_RUN=1 で取得確認のみ。
og:image が取れない記事はスキップ(=サムネ無しのまま、方針どおり様子見)。

owner 実行例:
  DRY_RUN=1 sudo -u www-data venv_kpi/bin/python3 tools/popup_thumbnail_backfill.py  # 確認
  sudo -u www-data venv_kpi/bin/python3 tools/popup_thumbnail_backfill.py            # 実行
  ※ venv_kpi の python と /tmp/wp_stg.txt(DB creds)に www-data がアクセスできること。
    権限の都合で sudo 直実行が難しい場合は、uploads/2026 配下を aiuser 書込可にして
    から通常実行でもよい(owner 判断)。
"""
from __future__ import annotations
import os
import re
import ssl
import sys
import html
import urllib.request
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DRY = bool(int(os.environ.get("DRY_RUN", "0")))

spec = importlib.util.spec_from_file_location("p2p", ROOT / "lib" / "popup_event_to_post.py")
p2p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p2p)

_CA = ROOT / "data" / "ca" / "kpop_ca_bundle.pem"
_CTX = ssl.create_default_context(cafile=str(_CA)) if _CA.is_file() else None


def fetch_og(url: str) -> tuple[str, str]:
    """(og:image, og:title) を返す。取得失敗は ("","")。"""
    if not url:
        return "", ""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        h = urllib.request.urlopen(req, timeout=15, context=_CTX).read().decode("utf-8", "replace")
    except Exception as e:
        print(f"    fetch失敗: {type(e).__name__}")
        return "", ""
    img = re.search(r'og:image["\'][^>]*content=["\'](.*?)["\']', h)
    ttl = re.search(r'og:title["\'][^>]*content=["\'](.*?)["\']', h)
    return (
        html.unescape(img.group(1).strip()) if img else "",
        html.unescape(ttl.group(1).strip()) if ttl else "",
    )


def targets() -> list[dict]:
    """サムネ未設定の publish 済 popup を返す。"""
    sql = (
        "SELECT p.ID, "
        "(SELECT meta_value FROM wp_postmeta WHERE post_id=p.ID AND meta_key='popup_source_url' LIMIT 1), "
        "(SELECT meta_value FROM wp_postmeta WHERE post_id=p.ID AND meta_key='popup_organizer' LIMIT 1) "
        "FROM wp_posts p "
        "JOIN wp_term_relationships tr ON tr.object_id=p.ID "
        "JOIN wp_term_taxonomy tt ON tt.term_taxonomy_id=tr.term_taxonomy_id "
        "JOIN wp_terms t ON t.term_id=tt.term_id "
        "WHERE t.slug='popup' AND p.post_type='post' AND p.post_status='publish' "
        "AND NOT EXISTS (SELECT 1 FROM wp_postmeta m WHERE m.post_id=p.ID AND m.meta_key='_thumbnail_id') "
        "ORDER BY p.ID DESC;"
    )
    out = []
    for line in p2p.run_mysql(sql).splitlines():
        parts = line.split("\t")
        if parts and parts[0].strip().isdigit():
            out.append({"id": int(parts[0]),
                        "src": parts[1].strip() if len(parts) > 1 else "",
                        "media": parts[2].strip() if len(parts) > 2 else ""})
    return out


def main() -> int:
    tg = targets()
    print(f"サムネ未設定の publish popup: {len(tg)} 件")
    done = skip = 0
    for t in tg:
        img, ttl = fetch_og(t["src"])
        if not img:
            print(f"  SKIP id={t['id']} : og:image 無し(様子見)")
            skip += 1
            continue
        media = t["media"] or "出典元"
        print(f"  id={t['id']} : og:image → {img[:60]}")
        if DRY:
            done += 1
            continue
        # download_and_attach_thumbnail の alt は sig['title'] と媒体名を使う
        sig = {"title": ttl or "", "source_media": media}
        att = p2p.download_and_attach_thumbnail(t["id"], img, sig)
        if att:
            done += 1
        else:
            print(f"    WARN: 設定失敗(uploads 書込権限 or DL失敗) id={t['id']}")
            skip += 1
    print(f"\n=== 結果: 設定={done} / skip={skip} ({'DRY_RUN' if DRY else '実行済'}) ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
