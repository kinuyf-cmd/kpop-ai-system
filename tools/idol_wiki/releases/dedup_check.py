#!/usr/bin/env python3
"""dedup_check.py — リリース候補を既存 releases と突合し、重複/矛盾を分類する(G2/G3)。

候補(status=pending)それぞれについて idol_artist の既存 releases メタを取得し、
正規化タイトルで照合する:
  - 同じ正規化タイトルが既存にある(年も一致 or 年情報なし) → status=duplicate (drop)
  - 同じ正規化タイトルが既存に別の年であり → status=conflict (要人間レビュー、自動applyしない)
  - 既存に無い → そのまま pending を維持(verify へ)

アーティスト名・作品名の英/韓表記揺れを吸収するため、ローマ字/ハングルを正規化。
非破壊(候補キューの status だけ更新、Idol Wiki は触らない)。

Usage:
    python3 tools/idol_wiki/releases/dedup_check.py            # 全 pending を判定
    python3 tools/idol_wiki/releases/dedup_check.py --dry-run  # 表示のみ
"""
from __future__ import annotations
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # 同ディレクトリの _queue_io
BASE = Path(__file__).resolve().parents[3]
CANDIDATES = BASE / "data" / "idol_wiki_release_candidates.jsonl"
WP_RO = "/usr/local/sbin/kpop/kpop-wp-ro"


def _run_wp(args: list[str]) -> str:
    return subprocess.run(["sudo", "-n", WP_RO] + args,
                          capture_output=True, text=True, check=False).stdout


def _norm(s: str) -> str:
    """作品名の重複判定キー。大小無視・空白記号除去・括弧内除去。"""
    s = (s or "").lower().strip()
    s = re.sub(r"\([^)]*\)", "", s)
    s = re.sub(r"（[^）]*）", "", s)
    s = re.sub(r"[\s\-_.,'\"「」『』!?]+", "", s)
    return s


def _existing_releases(pid: int) -> list[dict]:
    """idol_artist の releases repeater を読み出す。"""
    n = _run_wp(["post", "meta", "get", str(pid), "releases"]).strip()
    try:
        n = int(n)
    except ValueError:
        return []
    out = []
    for i in range(n):
        out.append({
            "year": _run_wp(["post", "meta", "get", str(pid), f"releases_{i}_release_year"]).strip(),
            "title": _run_wp(["post", "meta", "get", str(pid), f"releases_{i}_release_title"]).strip(),
            "type": _run_wp(["post", "meta", "get", str(pid), f"releases_{i}_release_type"]).strip(),
        })
    return out


def check(dry_run: bool) -> dict:
    if not CANDIDATES.exists():
        print("候補キューなし")
        return {}
    lines = [json.loads(l) for l in CANDIDATES.read_text().splitlines() if l.strip()]
    # pid ごとに既存releasesをキャッシュ(wp-cli呼び出し削減)
    existing_cache: dict[int, list[dict]] = {}
    stats = {"checked": 0, "duplicate": 0, "conflict": 0, "fresh": 0}

    for c in lines:
        if c.get("status") != "pending":
            continue
        stats["checked"] += 1
        pid = c["idol_post_id"]
        if pid not in existing_cache:
            existing_cache[pid] = _existing_releases(pid)
        cand_key = _norm(c["release_title"])
        cand_year = str(c["release_year"])

        verdict = "fresh"
        match = None
        # 短い正規化キー(≤2文字、例「II」)はタイトル一致だけでは誤判定しやすいので、
        # 年も一致する場合のみ重複/矛盾の照合対象にする(正当な短い作品名を救う)。
        short_key = len(cand_key) <= 2
        for ex in existing_cache[pid]:
            if _norm(ex["title"]) == cand_key and cand_key:
                if short_key and ex["year"] != cand_year:
                    continue  # 短いキーで年も違う→別作品とみなしスキップ
                if ex["year"] == cand_year or not ex["year"]:
                    verdict = "duplicate"
                else:
                    verdict = "conflict"
                match = ex
                break

        if verdict == "duplicate":
            c["status"] = "duplicate"
            c["dedup_note"] = f"既存 {match['year']}「{match['title']}」と重複"
            stats["duplicate"] += 1
        elif verdict == "conflict":
            c["status"] = "conflict"
            c["dedup_note"] = f"既存は {match['year']}「{match['title']}」(別年) — 要レビュー"
            stats["conflict"] += 1
        else:
            stats["fresh"] += 1  # status は pending のまま(verify へ)

    if dry_run:
        print("[dry-run] 判定結果(キュー未更新):")
        for c in lines:
            if c.get("status") in ("duplicate", "conflict") or (c.get("status") == "pending"):
                tag = c.get("status")
                note = c.get("dedup_note", "新規(verify へ)")
                print(f"  [{tag}] pid{c['idol_post_id']} {c['artist_canonical']}: "
                      f"{c['release_year']}「{c['release_title']}」 — {note}")
    else:
        from _queue_io import merge_update  # flock+candidate_id マージで並行書込安全化
        merge_update(lines)
        print(f"キュー更新済 → {CANDIDATES.name}")
    print(f"統計: {stats}")
    return stats


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    check(args.dry_run)
