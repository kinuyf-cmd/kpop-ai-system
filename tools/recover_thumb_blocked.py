#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""recover_thumb_blocked.py — サムネ失敗で draft 化された記事を救済する。

背景 (2026-08-31):
  regenerate_thumbnail_wp.py が VPS事故で消失したまま呼ばれ続け、
  サムネ品質違反の再生成が 100% 失敗 → **126件が draft のまま滞留**していた
  (うち 122件が dark_bg)。スクリプト復元後、止まっている分を遡って救済する。

安全側の制約:
  - DALL-E は1件ごとに実費(約$0.063)。**--apply が無ければ何もしない**。
  - 再生成に成功した記事だけ publish に戻す。失敗したら draft のまま
    (悪いサムネのまま公開するのが最悪の結果)。
  - 日次上限(DAILY_LIMIT=50)があるので --limit で刻む。

  python3 tools/recover_thumb_blocked.py            # 対象を数えるだけ
  python3 tools/recover_thumb_blocked.py --apply --limit 40
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

LOG = BASE / "logs" / "post_publish_enricher.log"
WP_RW = "/usr/local/sbin/kpop/kpop-wp-rw.sh"
WP_RO = "/usr/local/sbin/kpop/kpop-wp-ro"


def _raw_blocked_draft_ids():
    """THUMB_BLOCK されて **今も draft** の post_id を返す。

    ログだけで判断すると、既に手で戻された記事まで触ってしまう。
    必ず現在の post_status を DB で確かめる。
    """
    ids = sorted({int(m) for m in re.findall(r"THUMB_BLOCK: post (\d+)", LOG.read_text(errors="replace"))})
    if not ids:
        return []
    q = (f"SELECT ID FROM wp_posts WHERE ID IN ({','.join(map(str, ids))}) "
         f"AND post_status='draft'")
    out = subprocess.run(["sudo", "-n", WP_RO, "db", "query", q],
                         capture_output=True, text=True, timeout=60).stdout
    # 1行目はカラムヘッダ([[wp-ro-db-query-header-literal-newline-trap]])
    return [int(l) for l in out.splitlines()[1:] if l.strip().isdigit()]


def _dup_title_ids(ids):
    """公開済み記事と同一タイトルの draft ID を返す。

    実測(2026-08-31): 126件中7件が既存 publish と同名だった。
    両方公開するとカニバリを起こすため復旧対象から外す
    ([[seo-rewrite-over-new-articles-check-existing]])。
    """
    if not ids:
        return set()
    q = ("SELECT d.ID FROM wp_posts d JOIN wp_posts p "
         "ON p.post_title=d.post_title AND p.post_status='publish' AND p.ID<>d.ID "
         f"WHERE d.ID IN ({','.join(map(str, ids))})")
    out = subprocess.run(["sudo", "-n", WP_RO, "db", "query", q],
                         capture_output=True, text=True, timeout=60).stdout
    return {int(l) for l in out.splitlines()[1:] if l.strip().isdigit()}


def blocked_ids():
    ids = _raw_blocked_draft_ids()
    dup = _dup_title_ids(ids)
    if dup:
        print(f"  (重複タイトル {len(dup)}件を除外)")
    return [i for i in ids if i not in dup]


def regenerate(pid) -> int:
    """再生成スクリプトを呼ぶ。戻り値0が成功。"""
    r = subprocess.run([sys.executable, str(BASE / "tools/regenerate_thumbnail_wp.py"), str(pid)],
                       capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        print(f"    {r.stdout.strip()[:100] or r.stderr.strip()[:100]}")
    return r.returncode


def set_publish(pid) -> None:
    subprocess.run(["sudo", "-n", WP_RW, "post", "update", str(pid), "--post_status=publish"],
                   capture_output=True, text=True, timeout=60)


def run(apply: bool = False, limit: int = 0, exclude=None) -> int:
    exclude = set(exclude or ())
    ids = [i for i in blocked_ids() if i not in exclude]
    if limit:
        ids = ids[:limit]
    print(f"対象: {len(ids)}件" + ("" if apply else " (--apply 未指定のため何もしない)"))
    if not apply:
        return 0
    ok = 0
    for pid in ids:
        rc = regenerate(pid)
        if rc == 0:
            set_publish(pid)
            ok += 1
            print(f"  [ok] post {pid} 再生成→公開")
        else:
            print(f"  [ng] post {pid} 再生成失敗(draftのまま)")
    print(f"=== 完了: 成功 {ok}/{len(ids)} ===")
    return 0


def main():
    ap = argparse.ArgumentParser(description="サムネ失敗でdraft化された記事の救済")
    ap.add_argument("--apply", action="store_true", help="実際に再生成・公開する")
    ap.add_argument("--limit", type=int, default=0, help="処理件数の上限")
    ap.add_argument("--exclude", default="", help="除外する post_id(カンマ区切り)")
    a = ap.parse_args()
    ex = {int(x) for x in a.exclude.split(",") if x.strip().isdigit()}
    return run(apply=a.apply, limit=a.limit, exclude=ex)


if __name__ == "__main__":
    sys.exit(main())
