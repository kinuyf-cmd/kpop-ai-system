#!/bin/bash
# 日次CTR最適化ループ
cd /home/aiuser/kpop-ai-system

TODAY=$(date +%Y%m%d)
LOG="logs/daily_report_${TODAY}.md"

echo "# 日次最適化レポート ${TODAY}" > "$LOG"

# 1. audit_72h
python3 lib/audit_72h.py >> "$LOG" 2>&1

# 2. thumbnail_audit（既存のaudit_thumbnailsを呼ぶ形）
python3 -c "from lib.audit_72h import audit_thumbnails; import json; print(json.dumps(audit_thumbnails(), ensure_ascii=False, indent=2))" >> "$LOG" 2>&1

# 3. x_post_audit
python3 -c "from lib.audit_72h import audit_x_posts; import json; print(json.dumps(audit_x_posts(), ensure_ascii=False, indent=2))" >> "$LOG" 2>&1

# 4. ctr_rewrite_detector
python3 lib/ctr_rewrite_detector.py >> "$LOG" 2>&1

# 5. winning_pattern_tracker
echo "" >> "$LOG"
echo "## 勝ちパターン学習" >> "$LOG"
python3 lib/winning_pattern_tracker.py >> "$LOG" 2>&1

# 6. post_publish_evaluator
echo "" >> "$LOG"
echo "## 公開後評価 (24h/48h/72h)" >> "$LOG"
python3 lib/post_publish_evaluator.py >> "$LOG" 2>&1

# 7. regeneration_queue_builder
echo "" >> "$LOG"
echo "## 再生成キュー" >> "$LOG"
python3 lib/regeneration_queue_builder.py >> "$LOG" 2>&1

# 8. template_optimizer
echo "" >> "$LOG"
echo "## カテゴリ別テンプレート最適化" >> "$LOG"
python3 lib/template_optimizer.py >> "$LOG" 2>&1

# 9. auto_rewriter
echo "" >> "$LOG"
echo "## 自動リライト実行" >> "$LOG"
python3 lib/auto_rewriter.py >> "$LOG" 2>&1

# 10. dashboard生成 & オンライン公開
echo "" >> "$LOG"
echo "## ダッシュボード更新・公開" >> "$LOG"
python3 generate_dashboard.py >> "$LOG" 2>&1
python3 lib/deploy_dashboard.py >> "$LOG" 2>&1

echo "レポート出力: $LOG"
