#!/usr/bin/env python3
"""internal_link_boost.py — 需要の大きい記事へ内部リンクを寄せる

背景 (2026-08-23 実測):
  鉄槌教師クラスタの検索需要は
    声優/吹替 10,962imp(70%) / 相関図 3,762imp(24%) / 完全ガイド ほぼ0
  なのに被リンクは 声優3本 < 完全ガイド6本 と逆転していた。
  サイト内リンクの評価が、最大需要の記事に集まっていない。

  記事を新規に足すより、既にある「需要のある記事」へ評価を集約するほうが
  確実(その記事は既に上位に出ており、需要も実証済みのため)。

Usage:
  python3 lib/internal_link_boost.py --plan     # 変更計画を表示(書き込まない)
  python3 lib/internal_link_boost.py --apply
"""
from __future__ import annotations

import argparse
import base64
import re
import subprocess
import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

SITE = "https://www.kpopjournal.tokyo"
RO = "/usr/local/sbin/kpop/kpop-wp-ro"
RW = "/usr/local/sbin/kpop/kpop-wp-rw.sh"


def already_links_to(html: str, slug: str) -> bool:
    return f"/{slug}/" in str(html or "")


def add_link_sentence(html: str, slug: str, anchor: str, lead: str) -> str:
    """本文末尾に1文だけ内部リンクを足す。既にあれば何もしない。"""
    html = str(html or "")
    if already_links_to(html, slug):
        return html
    p = (f'<p>{lead}、<a href="{SITE}/{slug}/">{anchor}</a>'
         f'もあわせてご覧ください。</p>')
    return html.rstrip() + "\n\n" + p


def _db(sql: str) -> str:
    return subprocess.run(["sudo", "-n", RO, "db", "query", sql],
                          capture_output=True, text=True, timeout=90).stdout


def _fetch_content(pid: int) -> str:
    out = _db(f"SELECT TO_BASE64(post_content) FROM wp_posts WHERE ID={pid}")
    raw = "".join(out.splitlines()[1:]).replace("\\n", "")
    raw = re.sub(r"[^A-Za-z0-9+/=]", "", raw)
    return base64.b64decode(raw).decode("utf-8", "replace") if raw else ""


def _write(pid: int, html: str) -> bool:
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False,
                                     dir="/tmp", encoding="utf-8") as f:
        f.write(html)
        tmp = f.name
    Path(tmp).chmod(0o644)
    r = subprocess.run(["sudo", "-n", RW, "post", "update", str(pid), tmp],
                       capture_output=True, text=True, timeout=180)
    Path(tmp).unlink(missing_ok=True)
    return r.returncode == 0


# (リンク元slug, リンク先slug, アンカー, 導入文)
PLAN = [
    ("tyrant-chef-cast-chart", "tettsui-kyoshi-dub-episodes",
     "『鉄槌教師』日本語吹き替え声優一覧", "字幕ではなく吹き替えで見たい人は"),
    ("perfect-crown-21st-century-drama-guide", "tettsui-kyoshi-dub-episodes",
     "『鉄槌教師』日本語吹き替え声優一覧", "日本語吹き替えの担当声優が気になる人は"),
    ("agent-kim-reactivated-guide", "tettsui-kyoshi-dub-episodes",
     "『鉄槌教師』日本語吹き替え声優一覧", "同じNetflix作品の吹き替えキャストなら"),
    ("agent-kim-reactivated-viewing-guide", "tettsui-kyoshi-dub-episodes",
     "『鉄槌教師』日本語吹き替え声優一覧", "吹き替えのキャストまで知りたい人は"),
    ("my-royal-nemesis-cast-chart", "tettsui-kyoshi-cast-chart",
     "『鉄槌教師』キャスト相関図", "同じNetflixの話題作では"),
]


def _pid(slug: str):
    out = _db(f"SELECT ID FROM wp_posts WHERE post_name='{slug}' "
              f"AND post_status='publish'").splitlines()
    return int(out[1]) if len(out) > 1 and out[1].strip().isdigit() else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    done = 0
    for src, dst, anchor, lead in PLAN:
        pid = _pid(src)
        if not pid:
            print(f"  skip {src}: 記事が見つからない")
            continue
        html = _fetch_content(pid)
        if not html:
            print(f"  skip {src}: 本文取得失敗")
            continue
        if already_links_to(html, dst):
            print(f"  skip {src} → {dst}: 既にリンク済み")
            continue
        new = add_link_sentence(html, dst, anchor, lead)
        # 安全確認: 既存本文が丸ごと保持され、増分だけであること
        if not new.startswith(html.rstrip()[:200]) or len(new) < len(html):
            print(f"  ✗ {src}: 本文が保持されていないため中止")
            continue
        if not a.apply:
            print(f"  [plan] {src} → {dst} (+{len(new)-len(html)}字)")
            continue
        if _write(pid, new):
            print(f"  ✓ {src} → {dst}")
            done += 1
        else:
            print(f"  ✗ {src}: 書き込み失敗")
    print(f"\n{'適用' if a.apply else '計画'} {done if a.apply else len(PLAN)}件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
