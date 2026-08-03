#!/usr/bin/env python3
"""提携終了した A8 案件のリンクが残っていないか監査する。

背景(2026-08-03):
  DHOLIC/NUGU/カラパラ007 の提携終了後もリンクが記事に残り、A8 から
  無効クリックの通知が届いた。公開記事178本・268ブロックを除去し、
  genre_classifier.is_active_program() で注入をガードした。
  同じ事故を繰り返さないため、残存を定期検出する。

チェック内容:
  1. config 側: 終了案件の a8mat が素材ファイルに残っていないか
  2. 記事側 : 終了案件のトラッキングコードを含む投稿が無いか(要 wp-ro)

Usage:
  python3 tools/audit/affiliate_terminated_audit.py            # config のみ
  python3 tools/audit/affiliate_terminated_audit.py --with-db  # 記事も見る
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE))

from lib.revenue.genre_classifier import (  # noqa: E402
    is_active_program, load_a8_master_raw,
)

MATERIAL_FILES = [
    BASE / "config" / "affiliate" / "a8_materials.json",
    BASE / "cta" / "a8_banners.json",
]
WP_RO = "/usr/local/sbin/kpop/kpop-wp-ro"


def terminated_programs() -> dict:
    """終了案件 {key: program}。"""
    progs = load_a8_master_raw().get("programs", {})
    return {k: v for k, v in progs.items() if not is_active_program(v)}


def _a8mat_fragments(prog: dict) -> set[str]:
    """案件を一意に指すトラッキング片(457NRV+XXXXX の2要素目)を集める。"""
    frags = set()
    for m in re.finditer(r'[A-Z0-9]+\+([A-Z0-9]+)\+', json.dumps(prog)):
        frags.add(m.group(1))
    return frags


def audit_config(term: dict) -> list[str]:
    problems = []
    for path in MATERIAL_FILES:
        if not path.exists():
            continue
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw).get("programs", {})
        for key, prog in term.items():
            # 素材(html/sizes)が残っていれば注入されうる
            entry = data.get(key)
            if entry and (entry.get("html_material") or entry.get("sizes")):
                problems.append(f"{path.name}: 終了案件 {key} に素材が残存")
    return problems


def audit_posts(term: dict) -> list[str]:
    """記事本文に終了案件のコードが残っていないか(wp-ro 経由)。"""
    frags = set()
    for prog in term.values():
        frags |= _a8mat_fragments(prog)
    # master から a8mat を抜いてある場合は素材ファイルの履歴が拾えないため、
    # note に記録された既知コードも見る
    if not frags:
        return ["終了案件のトラッキングコードを特定できず(記事側は未検査)"]

    where = " OR ".join(f"post_content LIKE '%{f}%'" for f in sorted(frags))
    sql = ("SELECT COUNT(*) FROM wp_posts WHERE post_type='post' "
           f"AND post_status='publish' AND ({where})")
    try:
        out = subprocess.run(["sudo", "-n", WP_RO, "db", "query", sql],
                             capture_output=True, text=True, timeout=120)
    except Exception as e:  # noqa: BLE001
        return [f"DB 検査を実行できず: {e}"]
    lines = [x.strip() for x in out.stdout.splitlines() if x.strip().isdigit()]
    if not lines:
        return [f"DB 検査の出力を解釈できず: {out.stdout[:120]}"]
    n = int(lines[0])
    return [f"公開記事 {n} 件に終了案件のリンクが残存"] if n else []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-db", action="store_true", help="記事本文も検査する")
    args = ap.parse_args()

    term = terminated_programs()
    print(f"終了案件: {len(term)} 件 {sorted(term)}")

    problems = audit_config(term)
    if args.with_db:
        problems += audit_posts(term)

    if problems:
        print("\n[NG] 以下の問題が残っています:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\n[OK] 終了案件の残存はありません")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
