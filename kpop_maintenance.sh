#!/bin/bash

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# K-POP メンテナンス: ログローテーション + アーカイブ自動削除
# 毎週月曜 5:00 自動実行（週次レビューの前に実行）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

TODAY=$(date '+%Y年%m月%d日')
LOG_DIR=~
ARCHIVE_BASE=~/kpop_archives

echo "========================================"
echo " K-POP メンテナンス: $TODAY"
echo "========================================"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [1] ログローテーション（7日超 → 圧縮 → 30日超 → 削除）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo ""
echo "=== [1] ログローテーション ==="

LOGS=(
  "$LOG_DIR/kpop_pipeline.log"
  "$LOG_DIR/kpop_strategy_pipeline.log"
  "$LOG_DIR/kpop_chart_pipeline.log"
  "$LOG_DIR/kpop_weekly_review.log"
  "$LOG_DIR/kpop_apply_improvements.log"
)

for LOG in "${LOGS[@]}"; do
  if [[ ! -f "$LOG" ]]; then
    continue
  fi

  SIZE=$(wc -c < "$LOG" | tr -d ' ')
  NAME=$(basename "$LOG" .log)
  STAMP=$(date '+%Y%m%d')

  # 10MB超 または 7日以上蓄積したら圧縮ローテーション
  if [[ "$SIZE" -gt 10485760 ]] || find "$LOG" -mtime +7 -print -quit 2>/dev/null | grep -q .; then
    ROTATED="${LOG_DIR}/${NAME}_${STAMP}.log"
    cp "$LOG" "$ROTATED"
    gzip -f "$ROTATED"
    : > "$LOG"  # ファイルを空にする（truncate）
    echo "  ✓ ローテーション: $(basename "$LOG") → ${NAME}_${STAMP}.log.gz"
  else
    echo "  → $(basename "$LOG") (${SIZE} bytes) ローテーション不要"
  fi
done

# 30日超の圧縮ログを削除
DELETED_LOGS=0
while IFS= read -r f; do
  rm -f "$f"
  DELETED_LOGS=$((DELETED_LOGS + 1))
  echo "  🗑 削除: $(basename "$f")"
done < <(find "$LOG_DIR" -maxdepth 1 -name "kpop_*.log.gz" -mtime +30 2>/dev/null)

echo "  圧縮ログ削除: ${DELETED_LOGS}件"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [2] アーカイブ自動削除（30日超）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo ""
echo "=== [2] アーカイブ自動削除（30日超） ==="

if [[ ! -d "$ARCHIVE_BASE" ]]; then
  echo "  アーカイブディレクトリなし → スキップ"
else
  BEFORE=$(ls "$ARCHIVE_BASE" | wc -l | tr -d ' ')
  DELETED_ARCHIVES=0

  while IFS= read -r dir; do
    dir_name=$(basename "$dir")
    rm -rf "$dir"
    DELETED_ARCHIVES=$((DELETED_ARCHIVES + 1))
    echo "  🗑 削除: $dir_name"
  done < <(find "$ARCHIVE_BASE" -maxdepth 1 -mindepth 1 -type d -mtime +30 2>/dev/null)

  AFTER=$(ls "$ARCHIVE_BASE" 2>/dev/null | wc -l | tr -d ' ')
  echo "  削除: ${DELETED_ARCHIVES}件 / 残存: ${AFTER}件"

  # アーカイブの合計サイズを表示
  TOTAL_SIZE=$(du -sh "$ARCHIVE_BASE" 2>/dev/null | cut -f1)
  echo "  アーカイブ合計サイズ: ${TOTAL_SIZE}"
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [3] weekly_reviews 古いファイル削除（90日超）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo ""
echo "=== [3] 週次レビュー 古いファイル削除（90日超） ==="

REVIEW_DIR=~/weekly_reviews
if [[ -d "$REVIEW_DIR" ]]; then
  DELETED_REVIEWS=0
  while IFS= read -r f; do
    rm -f "$f"
    DELETED_REVIEWS=$((DELETED_REVIEWS + 1))
  done < <(find "$REVIEW_DIR" -type f -mtime +90 2>/dev/null)
  echo "  削除: ${DELETED_REVIEWS}件"
else
  echo "  週次レビューディレクトリなし → スキップ"
fi

echo ""
echo "========================================"
echo " ✅ メンテナンス完了"
echo "========================================"
