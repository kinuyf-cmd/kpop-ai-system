#!/bin/bash
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 成長加速・収益多様化 日次自動実行
# Phase 3 統合ランナー
#
# 実行内容:
#   1. AdSense RPM計測 + 広告スロット最適化
#   2. アフィリエイトリンク自動挿入（直近30記事）
#   3. バイラルスコア計測 + SNSシェアトラッキング
#   4. Premium会員誘導CTA挿入
#   5. メディアキット更新（月1回）
#
# cron: 毎日 5:30
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/env_loader.sh"

LOG_FILE="$SCRIPT_DIR/logs/growth_monetization.log"
mkdir -p "$SCRIPT_DIR/logs"

echo "" >> "$LOG_FILE"
echo "=== $(date '+%Y-%m-%d %H:%M:%S') Growth & Monetization Run ===" >> "$LOG_FILE"

# 1. AdSense RPM計測
echo "[1/5] AdSense RPM計測..." | tee -a "$LOG_FILE"
python3 "$SCRIPT_DIR/lib/adsense_optimizer.py" measure --days 7 >> "$LOG_FILE" 2>&1 || echo "  ⚠️ RPM計測スキップ" >> "$LOG_FILE"

# 2. AdSense広告スロット最適化 → 停止（2026-04-19）
# Next.jsフロントエンドがsanitizeContent()でWP content内のAdSenseを全除去し、
# 独自のReactコンポーネント(AdSenseInArticle)で広告配置を制御しているため、
# WP raw contentへのAdSense挿入は完全に無駄。raw contentの肥大化のみ引き起こす。
echo "[2/5] AdSense広告スロット最適化: 停止（フロントエンドで制御）" | tee -a "$LOG_FILE"

# 3. アフィリエイトリンク自動挿入
echo "[3/5] アフィリエイトリンク自動挿入..." | tee -a "$LOG_FILE"
python3 "$SCRIPT_DIR/lib/affiliate_auto_linker.py" inject --limit 20 >> "$LOG_FILE" 2>&1 || echo "  ⚠️ アフィリエイト挿入スキップ" >> "$LOG_FILE"

# 4. バイラルスコア + SNSシェアトラッキング
echo "[4/5] バイラル・SNSトラッキング..." | tee -a "$LOG_FILE"
python3 "$SCRIPT_DIR/lib/viral_engine.py" track --days 7 >> "$LOG_FILE" 2>&1 || echo "  ⚠️ SNSトラッキングスキップ" >> "$LOG_FILE"

# 5. メディアキット更新（毎月1日のみ）
DAY_OF_MONTH=$(date '+%d')
if [[ "$DAY_OF_MONTH" == "01" ]]; then
  echo "[5/5] メディアキット月次更新..." | tee -a "$LOG_FILE"
  python3 "$SCRIPT_DIR/lib/sponsor_portal.py" update-kit >> "$LOG_FILE" 2>&1 || echo "  ⚠️ メディアキット更新スキップ" >> "$LOG_FILE"
  python3 "$SCRIPT_DIR/lib/media_kit_generator.py" >> "$LOG_FILE" 2>&1 || echo "  ⚠️ メディアキット生成スキップ" >> "$LOG_FILE"
else
  echo "[5/5] メディアキット更新: 月初のみ → スキップ" | tee -a "$LOG_FILE"
fi

echo "=== Growth & Monetization 完了 ===" | tee -a "$LOG_FILE"
