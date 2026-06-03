#!/usr/bin/env python3
"""artist_resolver.py — アーティスト名(英/韓/日)→ idol_artist post_id 解決の単一の真実。

速報ニュースは artist 名が英(aespa)・韓(에스파)・日で揺れる。これを idol_artist CPT
(正本データ・123組)の post_id に**完全一致のみ**で解決する。曖昧・複数候補・未知名は
None を返す(誤った post_id への追記=正本汚染の最悪事故を避けるため、保守側に倒す)。

解決マップは idol_artist 各postの name_en/name_ko/name_ja + post_title から構築し、
data/artist_name_index.json にキャッシュする(--rebuild で再構築)。

Usage:
    from lib.artist_resolver import resolve
    r = resolve("에스파")   # -> {"post_id": 64, "canonical": "aespa", "matched_on": "name_ko"}
    r = resolve("知らない人")  # -> None

    python3 lib/artist_resolver.py --rebuild      # 索引を再構築
    python3 lib/artist_resolver.py エスパ aespa RIIZE 라이즈  # 解決テスト
"""
from __future__ import annotations
import json
import re
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
WP_RO = "/usr/local/sbin/kpop/kpop-wp-ro"
INDEX_PATH = BASE / "data" / "artist_name_index.json"


def _run_wp(args: list[str]) -> str:
    """wp-cli 読み取り専用ラッパー(birthday_collector._run_wp と同形)。"""
    cmd = ["sudo", "-n", WP_RO] + args
    return subprocess.run(cmd, capture_output=True, text=True, check=False).stdout


def _norm(name: str) -> str:
    """照合用の正規化キー。大小無視・空白/記号除去・全角半角ゆれ吸収。

    完全一致の土台。過剰な正規化(部分一致用)はしない — 別アーティストの
    誤一致を生むため、あくまで「同じ名前の表記揺れ」のみ吸収する。
    """
    if not name:
        return ""
    s = name.strip().lower()
    # 全角英数→半角
    s = s.translate(str.maketrans(
        "ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ"
        "ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ"
        "０１２３４５６７８９",
        "abcdefghijklmnopqrstuvwxyz" "abcdefghijklmnopqrstuvwxyz" "0123456789"))
    # 空白・記号・括弧内(英語表記の補足等)を除去
    s = re.sub(r"\([^)]*\)", "", s)        # 全角/半角括弧内
    s = re.sub(r"（[^）]*）", "", s)
    s = re.sub(r"[\s\-_.,'&!]+", "", s)
    return s


def _meta(pid: int, key: str) -> str:
    return _run_wp(["post", "meta", "get", str(pid), key]).strip()


def build_index() -> dict:
    """idol_artist 全postから name(英/韓/日)→post_id の解決マップを構築。

    1つの正規化キーに複数の post_id がぶつかった場合は ambiguous として記録し、
    resolve() では None を返す(誤マッチ防止)。
    """
    # birthday_collector._list_idol_artists と同じ取得
    out = _run_wp(["post", "list", "--post_type=idol_artist",
                   "--posts_per_page=300", "--format=csv",
                   "--fields=ID,post_title", "--orderby=ID"])
    rows = []
    for line in out.strip().splitlines()[1:]:
        m = re.match(r'^(\d+),"?(.+?)"?$', line)
        if m:
            rows.append((int(m.group(1)), m.group(2)))

    key_to_pids: dict[str, set[int]] = {}
    canonical: dict[int, str] = {}

    def add(name: str, pid: int):
        k = _norm(name)
        if not k:
            return
        key_to_pids.setdefault(k, set()).add(pid)

    for pid, title in rows:
        canonical[pid] = title
        add(title, pid)
        for mk in ("name_en", "name_ko", "name_ja"):
            v = _meta(pid, mk)
            if v:
                add(v, pid)

    # 一意なキーのみ採用。衝突キーは ambiguous に退避。
    resolved = {}
    ambiguous = {}
    for k, pids in key_to_pids.items():
        if len(pids) == 1:
            resolved[k] = next(iter(pids))
        else:
            ambiguous[k] = sorted(pids)

    index = {
        "resolved": resolved,            # 正規化キー -> post_id
        "ambiguous": ambiguous,          # 衝突キー -> [post_id,...] (resolve では None)
        "canonical": {str(p): t for p, t in canonical.items()},
        "count_artists": len(rows),
        "count_keys": len(resolved),
    }
    INDEX_PATH.write_text(json.dumps(index, ensure_ascii=False, indent=1))
    return index


def _load_index() -> dict:
    if not INDEX_PATH.exists():
        return build_index()
    try:
        return json.loads(INDEX_PATH.read_text())
    except Exception:
        return build_index()


def resolve(name: str) -> dict | None:
    """名前を idol_artist post_id に解決。完全一致のみ。曖昧/未知は None。

    Returns: {"post_id": int, "canonical": str, "key": str} または None
    """
    idx = _load_index()
    k = _norm(name)
    if not k:
        return None
    if k in idx.get("ambiguous", {}):
        return None  # 複数候補 → 誤マッチ回避のため解決しない
    pid = idx.get("resolved", {}).get(k)
    if pid is None:
        return None
    return {
        "post_id": pid,
        "canonical": idx.get("canonical", {}).get(str(pid), name),
        "key": k,
    }


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] == "--rebuild":
        idx = build_index()
        print(f"索引構築: {idx['count_artists']}組 / 解決キー{idx['count_keys']}件 "
              f"/ 曖昧キー{len(idx['ambiguous'])}件")
        print(f"  → {INDEX_PATH}")
        if args and args[0] == "--rebuild":
            sys.exit(0)
        args = args  # rebuild only
    else:
        for name in args:
            r = resolve(name)
            if r:
                print(f"  ✓ {name!r} → pid={r['post_id']} ({r['canonical']})")
            else:
                print(f"  ✗ {name!r} → 解決不能(未知/曖昧)")
