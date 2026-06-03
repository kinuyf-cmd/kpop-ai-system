#!/usr/bin/env python3
"""review_queue.py — リリース候補キューの閲覧と状態遷移(G5 人間レビュー)。

候補は extract→dedup→verify を経て status を持つ:
  pending / fresh(=pending) → verified / unverifiable / year_mismatch / duplicate / conflict
人間(Claude/owner)が verified 等を見て approve/reject する。apply_releases.sh は
status=approved の候補だけを Idol Wiki に書き込む(他は一切触らない)。

Usage:
    python3 review_queue.py --list                 # 全候補のサマリ
    python3 review_queue.py --show 64              # 特定idol_post_idの候補と既存releasesのdiff
    python3 review_queue.py --approve <candidate_id> [...]   # approve に遷移
    python3 review_queue.py --reject  <candidate_id> [...]   # reject に遷移
"""
from __future__ import annotations
import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # 同ディレクトリの _queue_io
BASE = Path(__file__).resolve().parents[3]
CANDIDATES = BASE / "data" / "idol_wiki_release_candidates.jsonl"
WP_RO = "/usr/local/sbin/kpop/kpop-wp-ro"


def _run_wp(args):
    return subprocess.run(["sudo", "-n", WP_RO] + args,
                          capture_output=True, text=True, check=False).stdout


def _load():
    if not CANDIDATES.exists():
        return []
    return [json.loads(l) for l in CANDIDATES.read_text().splitlines() if l.strip()]


def _save(lines):
    from _queue_io import merge_update  # flock+candidate_id マージで並行書込安全化
    merge_update(lines)


def cmd_list(lines):
    from collections import Counter
    by_status = Counter(c.get("status", "?") for c in lines)
    print(f"候補 {len(lines)}件 — status内訳: {dict(by_status)}")
    for c in lines:
        print(f"  [{c.get('status',''):13}] {c['candidate_id']} "
              f"pid{c['idol_post_id']} {c['artist_canonical']}: "
              f"{c['release_year']}「{c['release_title']}」[{c.get('release_type','')}] "
              f"conf={c.get('confidence','')}")
        note = c.get("verify_note") or c.get("dedup_note")
        if note:
            print(f"                 └ {note}")


def cmd_show(lines, pid):
    print(f"=== idol_post_id={pid} 既存releases ===")
    n = _run_wp(["post", "meta", "get", str(pid), "releases"]).strip()
    try:
        n = int(n)
    except ValueError:
        n = 0
    for i in range(n):
        y = _run_wp(["post", "meta", "get", str(pid), f"releases_{i}_release_year"]).strip()
        t = _run_wp(["post", "meta", "get", str(pid), f"releases_{i}_release_title"]).strip()
        ty = _run_wp(["post", "meta", "get", str(pid), f"releases_{i}_release_type"]).strip()
        print(f"  [{i}] {y}「{t}」[{ty}]")
    print(f"\n=== このアーティストの候補(追記すると下に並ぶ) ===")
    for c in lines:
        if c["idol_post_id"] == pid:
            note = c.get("verify_note") or c.get("dedup_note") or ""
            print(f"  [{c.get('status','')}] {c['candidate_id']}: "
                  f"{c['release_year']}「{c['release_title']}」[{c.get('release_type','')}]"
                  f" conf={c.get('confidence','')} — {note}")
            print(f"      根拠: {c.get('evidence','')} / 出典速報: {c.get('source_title','')[:50]}")


def cmd_transition(lines, ids, to_status):
    idset = set(ids)
    changed = 0
    for c in lines:
        if c["candidate_id"] in idset:
            # approve は verified からのみ許可(安全側)。reject はどこからでも可。
            if to_status == "approved" and c.get("status") not in ("verified",):
                print(f"  ⚠ {c['candidate_id']} は status={c.get('status')} のため approve 不可"
                      f"(verified のみ)。先に内容を確認のこと")
                continue
            c["status"] = to_status
            changed += 1
            print(f"  ✓ {c['candidate_id']} → {to_status}")
    _save(lines)
    print(f"{changed}件を {to_status} に更新")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--show", type=int, help="idol_post_id")
    ap.add_argument("--approve", nargs="+", metavar="CAND_ID")
    ap.add_argument("--reject", nargs="+", metavar="CAND_ID")
    args = ap.parse_args()
    lines = _load()
    if args.show:
        cmd_show(lines, args.show)
    elif args.approve:
        cmd_transition(lines, args.approve, "approved")
    elif args.reject:
        cmd_transition(lines, args.reject, "rejected")
    else:
        cmd_list(lines)
