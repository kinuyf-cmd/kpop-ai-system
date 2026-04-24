#!/bin/bash
# ============================================================
# run_seo_daily.sh — SEO日次自動最適化オーケストレーター
#
# 実行順序:
#   1. GSCメトリクス取得（gsc_metrics_fetcher.py）
#   2. 競合キーワード分析（seo_competitor_analyzer.py）
#   3. ロングテールテーマ生成＋auto_directives注入（seo_longtail_generator.py）
#   4. 内部リンク最適化（seo_internal_link_engine.py）
#   5. Discord通知
#
# cron: 30 5 * * *（毎日05:30 JST = GSCデータ更新後）
# ============================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

VENV="$SCRIPT_DIR/.venv/bin/activate"
[[ -f "$VENV" ]] && source "$VENV"
[[ -f "$SCRIPT_DIR/env_loader.sh" ]] && source "$SCRIPT_DIR/env_loader.sh" 2>/dev/null || true

LOG="$SCRIPT_DIR/logs/seo_daily.log"
mkdir -p "$(dirname "$LOG")"

NOW=$(date '+%Y-%m-%d %H:%M:%S JST')
echo "" >> "$LOG"
echo "========================================" >> "$LOG"
echo "SEO日次最適化 開始: $NOW" >> "$LOG"
echo "========================================" >> "$LOG"

ERRORS=0
SUCCESSES=0

run_step() {
  local name="$1"
  local cmd="$2"
  echo "--- [$name] ---" >> "$LOG"
  local out
  if out=$(eval "$cmd" 2>&1); then
    echo "$out" >> "$LOG"
    echo "  ✅ $name 完了" | tee -a "$LOG"
    SUCCESSES=$((SUCCESSES + 1))
  else
    echo "$out" >> "$LOG"
    echo "  ❌ $name 失敗" | tee -a "$LOG"
    ERRORS=$((ERRORS + 1))
  fi
}

# Step 0: CTR効果測定（内部でGSC取得も行う → Step1のGSC取得と兼用）
run_step "CTR効果測定" "python3 lib/ctr_effect_measurer.py --auto"

# Step 1: GSCメトリクス取得（CTR効果測定で既に取得済みだが、--days 28 で追加取得）
run_step "GSCメトリクス取得" "python3 lib/gsc_metrics_fetcher.py --days 28"

# Step 2: 競合キーワード分析 + CEO提案キュー投入
run_step "競合分析" "python3 lib/seo_competitor_analyzer.py --to-ceo --actionable"

# Step 3: ロングテールテーマ生成 + auto_directives注入
run_step "ロングテール生成" "python3 lib/seo_longtail_generator.py --inject --generate-prompts"

# Step 4: 内部リンク最適化（本番: --dry-runなし、最大100記事）
run_step "内部リンク最適化" "python3 lib/seo_internal_link_engine.py --limit 100"

# Step 5: SEOレポートサマリをDiscordに送信
SEO_SUMMARY=""
if [ -f "$SCRIPT_DIR/logs/seo_competitor_report.json" ]; then
  SEO_SUMMARY=$(python3 -c "
import json
r = json.load(open('logs/seo_competitor_report.json'))
s = r.get('summary', {})
print(f\"機会KW: {s.get('total_opportunity_keywords',0)}件 (+{s.get('total_click_gap',0)}clicks)\")
print(f\"ギャップ: {s.get('content_gaps_count',0)}件\")
print(f\"カニバリ: {s.get('cannibalization_artists',0)}件\")
top3 = s.get('top3_opportunity', [])
if top3: print(f\"TOP3: {', '.join(top3[:3])}\")
" 2>/dev/null || echo "")
fi

LONGTAIL_SUMMARY=""
if [ -f "$SCRIPT_DIR/logs/seo_longtail_themes.json" ]; then
  LONGTAIL_SUMMARY=$(python3 -c "
import json
r = json.load(open('logs/seo_longtail_themes.json'))
themes = r.get('themes', [])[:3]
print(f\"テーマ: {r.get('total_themes',0)}件\")
for t in themes:
    print(f\"  - {t['query']} (pos={t['position']} imp={t['impressions']})\")
" 2>/dev/null || echo "")
fi

# Discord通知
source "$SCRIPT_DIR/lib/discord_channels.sh" 2>/dev/null || true
WEBHOOK=$(get_discord_webhook "seo_insights" 2>/dev/null || echo "")
[ -z "$WEBHOOK" ] && WEBHOOK="${DISCORD_WEBHOOK:-}"
[ -z "$WEBHOOK" ] && [ -f ~/.kpop_discord_webhook ] && WEBHOOK=$(cat ~/.kpop_discord_webhook | tr -d '[:space:]')

if [ -n "$WEBHOOK" ]; then
  MSG="🔍 SEO日次最適化 完了 ($(date '+%m/%d %H:%M'))
成功: ${SUCCESSES} / 失敗: ${ERRORS}

📊 競合分析:
${SEO_SUMMARY}

📝 ロングテール:
${LONGTAIL_SUMMARY}"

  curl -s -o /dev/null -X POST "$WEBHOOK" \
    -H "Content-Type: application/json" \
    -d "$(python3 -c "import json,sys; print(json.dumps({'content': sys.argv[1][:1950]}))" "$MSG")" 2>/dev/null
  echo "  ✅ Discord送信完了" | tee -a "$LOG"
fi

echo "" >> "$LOG"
echo "SEO日次最適化 完了: $(date '+%Y-%m-%d %H:%M:%S JST') (成功=$SUCCESSES 失敗=$ERRORS)" >> "$LOG"
echo "========================================" >> "$LOG"
