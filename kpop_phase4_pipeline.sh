#!/usr/bin/env bash
# =============================================================================
# kpop_phase4_pipeline.sh — Phase 4 自律機能オーケストレーター
#
# 1. トレンド予測AI          → 3日後バズ記事の先読み
# 2. A/Bテスト完全自動化      → サムネ・メタディスクリプション含む
# 3. 記事ROI自動計算          → TOP10/BOTTOM10 週次レポート
# 4. コスト最適化             → 月次レポート・予算超過アラート
#
# Usage:
#   bash kpop_phase4_pipeline.sh                 # 全機能実行
#   bash kpop_phase4_pipeline.sh trend           # トレンド予測のみ
#   bash kpop_phase4_pipeline.sh ab-test         # A/Bテストのみ
#   bash kpop_phase4_pipeline.sh roi             # ROI計算のみ
#   bash kpop_phase4_pipeline.sh cost            # コスト最適化のみ
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"

TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
PHASE4_LOG="$LOG_DIR/phase4_pipeline.log"

# ─── 排他制御 ───
LOCKFILE="/tmp/kpop_phase4.flock"
exec 200>"$LOCKFILE"
if ! flock -n 200; then
    echo "[$TIMESTAMP] Phase 4 pipeline already running → skip" >> "$PHASE4_LOG"
    exit 0
fi

log() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $1"
    echo "$msg" | tee -a "$PHASE4_LOG"
}

run_step() {
    local name="$1"
    shift
    log "=== $name 開始 ==="
    if "$@" >> "$PHASE4_LOG" 2>&1; then
        log "=== $name 完了 ✅ ==="
    else
        log "=== $name 失敗 ❌ (exit=$?) ==="
    fi
}

MODE="${1:-all}"

# ─── 1. トレンド予測AI ───
if [[ "$MODE" == "all" || "$MODE" == "trend" ]]; then
    run_step "トレンド予測AI" python3 lib/trend_predictor.py --top 5
fi

# ─── 2. A/Bテスト ───
if [[ "$MODE" == "all" || "$MODE" == "ab-test" ]]; then
    DOW=$(date +%u)  # 1=月 ... 7=日

    if [[ "$DOW" == "3" ]]; then
        # 水曜: テスト設計 + 適用
        run_step "A/Bテスト設計（メタ+サムネ）" python3 lib/ab_test_manager.py design --type all --top 5
        run_step "A/Bテスト適用" python3 lib/ab_test_manager.py apply
    elif [[ "$DOW" == "5" ]]; then
        # 金曜: 判定 + 勝ちパターン注入
        run_step "A/Bテスト判定" python3 lib/ab_test_manager.py judge
        run_step "A/B勝ちパターン注入" python3 lib/ab_test_manager.py inject-learnings
    fi

    # 毎日: レポート
    run_step "A/Bテストレポート" python3 lib/ab_test_manager.py report
fi

# ─── 3. 記事ROI ───
if [[ "$MODE" == "all" || "$MODE" == "roi" ]]; then
    DOW=$(date +%u)
    if [[ "$DOW" == "1" ]]; then
        # 月曜: フル実行（リライトキュー更新あり）
        run_step "記事ROI（週次フル）" python3 lib/article_roi_calculator.py --queue-rewrite
    else
        # それ以外: レポートのみ
        run_step "記事ROI（レポート）" python3 lib/article_roi_calculator.py --report
    fi
fi

# ─── 4. コスト最適化 ───
if [[ "$MODE" == "all" || "$MODE" == "cost" ]]; then
    DOM=$(date +%d)  # 日

    # 毎日: 予算超過アラートチェック
    run_step "コスト日次チェック" python3 lib/cost_optimizer.py --daily

    if [[ "$DOM" == "01" ]]; then
        # 月初: フル月次レポート + mewtwo注入
        run_step "コスト月次レポート" python3 lib/cost_optimizer.py --inject
    fi
fi

log "Phase 4 pipeline 完了 ($MODE)"
