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

echo "レポート出力: $LOG"
