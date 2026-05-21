#!/usr/bin/env bash
# kpop_auto_push.sh — Day11 M11.5: rebuild-20260521 の日次自動 push
#
# 方針(memory: github-main-is-pre-vps-incident-backbone):
#   - 作業ブランチ rebuild-20260521 のみ push。origin/main(本流アーカイブ)は触らない。
#   - force-push は絶対にしない(通常 push のみ)。
#   - 変更が無ければ何もしない(空コミットを作らない)。
#   - commit 前に secrets ガード(webhook 実URL / sk-/ghp_/AKIA トークン)を走らせ、
#     検出したら commit/push を中止してログに残す(誤って機密を上げない)。
#   - SSH deploy key(config Host github-kpop-ai-system)で認証。
set -uo pipefail

REPO="/home/aiuser/kpop-ai-system"
BRANCH="rebuild-20260521"
LOG="/home/aiuser/.kpop_recovery/cron_push.log"
SSH_CMD="ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15"

log(){ echo "[$(date '+%F %T')] $*" >> "$LOG"; }

cd "$REPO" || { log "ERROR: cd $REPO 失敗"; exit 1; }

# 作業ブランチ以外では何もしない(main 等で誤動作させない)
CUR="$(git branch --show-current)"
if [ "$CUR" != "$BRANCH" ]; then
  log "skip: current branch=$CUR (≠ $BRANCH)"
  exit 0
fi

# 変更が無ければ終了
if [ -z "$(git status --porcelain)" ]; then
  log "no changes — skip"
  exit 0
fi

# --- secrets ガード(staged 前に working tree 全体を検査)---
HITS="$(git diff --staged --no-color; git diff --no-color; \
        git ls-files --others --exclude-standard | xargs -r grep -lE \
        'https://discord(app)?\.com/api/webhooks/[0-9]|sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}' 2>/dev/null)"
if printf '%s' "$HITS" | grep -qE 'https://discord(app)?\.com/api/webhooks/[0-9]|sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}'; then
  log "ABORT: secrets 検出 — commit/push を中止。手動確認が必要。"
  exit 2
fi

# commit（日付スタンプ）
git add -A
if git commit -q -m "auto: 日次スナップショット $(date '+%F %T')

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"; then
  log "commit: $(git rev-parse --short HEAD)"
else
  log "commit なし（add後に差分消失）"
  exit 0
fi

# push（通常 push のみ。--force は使わない）
if GIT_SSH_COMMAND="$SSH_CMD" git push origin "$BRANCH" >>"$LOG" 2>&1; then
  log "push OK → origin/$BRANCH"
else
  log "WARN: push 失敗（次回再試行。手動確認推奨）"
  exit 1
fi

log "=== 完了 ==="
