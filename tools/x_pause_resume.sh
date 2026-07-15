#!/bin/bash
# X投稿 自動再開スクリプト
# [X-PAUSE 2026-06-26] シャドーバン疑いで72h停止した X投稿cron を復活させる。
# crontab 内の "# [X-PAUSE ...] " マーカー行からマーカーを除去してアクティブに戻し、
# 再開用のリマインダー行(x-pause-resume-cron)自身も削除する。
# 実行後は Discord へ完了通知。冪等(対象が無ければ何もしない)。
set -euo pipefail

MARK_RE='^# \[X-PAUSE [^]]*\] '
RESUME_TAG='x-pause-resume-cron'
TMP="$(mktemp /tmp/cron_resume.XXXXXX)"

crontab -l > "$TMP" 2>/dev/null || true

python3 - "$TMP" "$RESUME_TAG" <<'PY'
import re, sys
path, resume_tag = sys.argv[1], sys.argv[2]
mark_re = re.compile(r'^# \[X-PAUSE [^\]]*\] ')
out = []
restored = 0
for line in open(path).read().splitlines():
    # 再開リマインダー自身は除去(one-shot)
    if resume_tag in line:
        continue
    m = mark_re.match(line)
    if m:
        out.append(line[m.end():])
        restored += 1
    else:
        out.append(line)
open(path, "w").write("\n".join(out) + "\n")
print(f"restored {restored} line(s)")
PY

crontab "$TMP"
rm -f "$TMP"

# 完了通知(失敗しても再開処理は止めない)
cd /home/aiuser/kpop-ai-system 2>/dev/null || true
MSG="✅ [X-PAUSE解除] 72時間停止していたX投稿cronを自動再開しました（x_scheduled_poster / grant-ops x_daily_scheduler / auto_article_x_linker）。シャドーバンが解消しているか実投稿後に確認してください。"
if [ -f lib/resolve_discord_webhook.py ]; then
  python3 - "$MSG" <<'PY' 2>/dev/null || true
import sys, json, urllib.request
sys.path.insert(0, "/home/aiuser/kpop-ai-system")
try:
    # 2026-07-15: モジュールが公開するのは resolve(channel) のみ。
    # 存在しない resolve_discord_webhook() を呼んでいたため通知が飛んでいなかった。
    from lib.resolve_discord_webhook import resolve
    url = resolve("urgent_errors")
except Exception:
    url = None
if url:
    req = urllib.request.Request(
        url, data=json.dumps({"content": sys.argv[1]}).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "kpop-x-pause-resume/1.0"},
    )
    urllib.request.urlopen(req, timeout=10)
PY
fi

echo "$(date '+%Y-%m-%d %H:%M:%S') X-PAUSE resume executed" >> /home/aiuser/.kpop_recovery/x_pause_resume.log
