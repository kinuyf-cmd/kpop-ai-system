#!/bin/bash
# apply_releases.sh — status=approved のリリース候補だけを idol_artist の releases に冪等追記する。
#
# 安全設計:
#   - approved 以外は一切処理しない(G5)。
#   - releases repeater の末尾に追記(既存行は触らない)。件数 N→N+1。
#   - 同年同タイトルが既存にあれば skip(冪等・二重追記防止 G2/G6)。
#   - 書込は kpop-wp-rw.sh 経由(自動バックアップ付き)。
#   - dry-run 既定。実書込は --apply。
#   - ACF 管理画面互換のため _releases_N_* コンパニオン(field_release_*)も書く。
#
# Usage:
#   bash apply_releases.sh                 # 全 approved を dry-run プレビュー
#   bash apply_releases.sh --artist 64     # 特定 idol_post_id のみ
#   bash apply_releases.sh --apply         # 実書込
set -euo pipefail
cd "$(dirname "$0")"
REL_DIR="$(pwd)"   # _queue_io.py のあるディレクトリ
BASE="$(cd ../../.. && pwd)"
CANDIDATES="$BASE/data/idol_wiki_release_candidates.jsonl"
RO="/usr/local/sbin/kpop/kpop-wp-ro"
RW="/usr/local/sbin/kpop/kpop-wp-rw.sh"

APPLY=0
ONLY_PID=""
while [ $# -gt 0 ]; do
  case "$1" in
    --apply) APPLY=1 ;;
    --artist) ONLY_PID="$2"; shift ;;
  esac
  shift
done

[ -f "$CANDIDATES" ] || { echo "候補キューなし"; exit 0; }

_norm() { echo "$1" | tr 'A-Z' 'a-z' | sed -E 's/[[:space:]\-_.,]//g'; }

# approved 候補を1行ずつ処理(jq非依存: pythonで抽出)
python3 - "$CANDIDATES" "$ONLY_PID" <<'PY' | while IFS=$'\t' read -r pid year title rtype cid; do
import json, re, sys
cands = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]
only = sys.argv[2]
def clean(s):  # タブ/改行はフィールド/行区切りを壊すので空白化(シェル read 安全化)
    return re.sub(r"[\t\r\n]+", " ", str(s)).strip()
for c in cands:
    if c.get("status") != "approved":
        continue
    if only and str(c["idol_post_id"]) != only:
        continue
    pid = str(c["idol_post_id"]); year = str(c["release_year"])
    # pid/year が不正な候補は安全のため出力しない(空 year 書込を防ぐ)
    if not re.match(r"^\d+$", pid) or not re.match(r"^\d{4}$", year):
        continue
    title = clean(c["release_title"]); rtype = clean(c.get("release_type", ""))
    if not title:
        continue
    print("\t".join([pid, year, title, rtype, c["candidate_id"]]))
PY
  # 既存 releases 件数
  total="$(sudo -n "$RO" post meta get "$pid" releases 2>/dev/null || echo 0)"
  [[ "$total" =~ ^[0-9]+$ ]] || total=0

  # 冪等: 同年同タイトルが既存にあれば skip(total=0 のとき seq を回さない)
  dup=0
  if [ "$total" -gt 0 ]; then
    for i in $(seq 0 $((total-1))); do
      ey="$(sudo -n "$RO" post meta get "$pid" "releases_${i}_release_year" 2>/dev/null || echo)"
      et="$(sudo -n "$RO" post meta get "$pid" "releases_${i}_release_title" 2>/dev/null || echo)"
      if [ "$ey" = "$year" ] && [ "$(_norm "$et")" = "$(_norm "$title")" ]; then
        dup=1; break
      fi
    done
  fi
  if [ "$dup" = "1" ]; then
    echo "  [skip-dup] pid$pid $year「$title」(既存)"
    continue
  fi

  if [ "$APPLY" = "1" ]; then
    sudo -n "$RW" post meta update "$pid" "releases_${total}_release_year"  "$year"  >/dev/null
    sudo -n "$RW" post meta update "$pid" "releases_${total}_release_title" "$title" >/dev/null
    sudo -n "$RW" post meta update "$pid" "releases_${total}_release_type"  "$rtype" >/dev/null
    sudo -n "$RW" post meta update "$pid" "_releases_${total}_release_year"  field_release_year  >/dev/null
    sudo -n "$RW" post meta update "$pid" "_releases_${total}_release_title" field_release_title >/dev/null
    sudo -n "$RW" post meta update "$pid" "_releases_${total}_release_type"  field_release_type  >/dev/null
    sudo -n "$RW" post meta update "$pid" releases "$((total+1))" >/dev/null
    echo "  [APPLIED] pid$pid [$total] $year「$title」[$rtype] (releases $total→$((total+1)))"
    # 候補を applied に(flock+candidate_id マージで並行書込安全化)
    python3 - "$REL_DIR" "$cid" <<'PY2'
import sys
sys.path.insert(0, sys.argv[1])
from _queue_io import load, merge_update
cid = sys.argv[2]
upd = [c for c in load() if c.get("candidate_id") == cid]
for c in upd:
    c["status"] = "applied"
merge_update(upd)
PY2
  else
    echo "  [dry-run] pid$pid 末尾[$total]に追記予定: $year「$title」[$rtype]"
  fi
done

[ "$APPLY" = "1" ] || echo "(dry-run。実書込は --apply)"
