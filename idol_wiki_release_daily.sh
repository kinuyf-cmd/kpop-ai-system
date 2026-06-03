#!/bin/bash
# idol_wiki_release_daily.sh — 速報ニュース→Idol Wiki releases 候補を毎日自動生成する。
#
# extract(LLM抽出) → dedup_check → verify_releases を順に実行し、verified候補を
# キューに溜める。**apply(実書込)は含めない** — 正本汚染を防ぐため人間承認(review_queue
# --approve → apply_releases.sh)を必須に保つ(今日の検証でLLMが粒度を誤ると実証済み)。
#
# コスト集中を防ぐため1日のLLM抽出を MAX 件に制限(残りは翌日に回る=marker未記録)。
# venv_kpi 必須(ANTHROPIC_API_KEY)。cost_guard(DAILY_BUDGET_USD)も二重で効く。
set -euo pipefail
cd "$(dirname "$0")"

PY=venv_kpi/bin/python3
REL=tools/idol_wiki/releases
MAX="${IDOL_WIKI_DAILY_MAX:-30}"   # 1日のLLM抽出上限(env で調整可)
LOG_DIR="$HOME/.kpop_recovery/idol_wiki"
mkdir -p "$LOG_DIR"
TS=$(date '+%Y-%m-%d %H:%M:%S')
echo "[$TS] ===== idol_wiki_release_daily 開始 (max=$MAX) ====="

# 名前解決索引が無ければ構築(idol_artist 追加に追従)
[ -f data/artist_name_index.json ] || $PY lib/artist_resolver.py --rebuild

# 1) 抽出(全アーティスト・LLM上限あり)
echo "[$TS] --- extract (max $MAX) ---"
$PY "$REL/extract_releases.py" --max "$MAX" 2>&1 | tail -3

# 2) 重複/矛盾チェック
echo "[$TS] --- dedup_check ---"
$PY "$REL/dedup_check.py" 2>&1 | tail -2

# 3) Wikipedia 照合(非破壊)
echo "[$TS] --- verify_releases ---"
$PY "$REL/verify_releases.py" 2>&1 | tail -2

# 4) verified(=approve待ち)件数を集計してログ
VERIFIED=$($PY -c "
import json
n=0
try:
    for l in open('data/idol_wiki_release_candidates.jsonl'):
        if json.loads(l).get('status')=='verified': n+=1
except: pass
print(n)
" 2>/dev/null || echo 0)
echo "[$TS] verified(approve待ち)候補: ${VERIFIED}件"
echo "$VERIFIED" > "$LOG_DIR/verified_count.txt"

echo "[$TS] ===== idol_wiki_release_daily 完了 ====="
echo "  → レビュー: $PY $REL/review_queue.py --list"
echo "  → 承認後:   bash $REL/apply_releases.sh --apply"
