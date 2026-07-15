#!/bin/bash
# ============================================================
# kpop_breaking_monitor.sh - 速報トレンドモニター
#
# 30分ごとにトレンドをチェックし、急上昇キーワードを検知したら
# 速報記事を緊急投稿する
#
# cron: */30 6-20 * * * bash ~/kpop_breaking_monitor.sh
# ============================================================
set -euo pipefail

TODAY=$(date '+%Y年%m月%d日')
TODAY_ISO=$(date '+%Y-%m-%d')
HOUR=$(date '+%H' | sed 's/^0//')
CACHE_DIR="$HOME/.kpop_trend_cache"
LOG_FILE="$HOME/kpop_scheduler_logs/breaking_monitor_$(date '+%Y%m%d').log"
# 2026-07-15: config 一元管理へ寄せる。speed 速報は publishing_log チャンネルへ。
# resolve 失敗時のみ従来の ~/.kpop_discord_webhook 直読みへフォールバック。
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WEBHOOK=$(python3 "$SCRIPT_DIR/lib/resolve_discord_webhook.py" publishing_log 2>/dev/null || echo "")
[ -z "$WEBHOOK" ] && WEBHOOK=$(cat ~/.kpop_discord_webhook 2>/dev/null | tr -d '[:space:]' || echo "")
LOCK_FILE="/tmp/kpop_breaking.lock"

mkdir -p "$CACHE_DIR" "$HOME/kpop_scheduler_logs"

slog() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [MONITOR] $*" | tee -a "$LOG_FILE"; }

discord() {
  [ -z "$WEBHOOK" ] && return
  python3 -c "
import requests, sys
requests.post(sys.argv[1], json={'content': sys.argv[2][:1900]}, timeout=10)
" "$WEBHOOK" "$1" 2>/dev/null || true
}

# 夜間ガード
if [ "$HOUR" -ge 21 ] || [ "$HOUR" -lt 6 ]; then
  exit 0
fi

# ロック
if [ -f "$LOCK_FILE" ]; then
  LOCK_PID=$(cat "$LOCK_FILE" 2>/dev/null)
  if kill -0 "$LOCK_PID" 2>/dev/null; then
    exit 0
  fi
  rm -f "$LOCK_FILE"
fi
echo $$ > "$LOCK_FILE"
trap "rm -f '$LOCK_FILE'" EXIT

# ============================================================
# 本日投稿数チェック
# ============================================================
POST_COUNT=$(python3 - "$TODAY_ISO" << 'PY'
import sys, json, urllib.request, base64, urllib.parse
today = sys.argv[1]
after = today + "T00:00:00"
url = "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts?per_page=50&after=" + urllib.parse.quote(after) + "&status=publish"
auth = base64.b64encode(os.environ.get("WP_USER","kpop-bot").encode() + b":" + os.environ.get("WP_PASS","").encode()).decode()
req = urllib.request.Request(url, headers={"Authorization": "Basic " + auth})
try:
    with urllib.request.urlopen(req, timeout=15) as res:
        posts = json.loads(res.read())
    print(len(posts))
except Exception:
    print("0")
PY
)

if [ "$POST_COUNT" -ge 20 ]; then
  slog "投稿上限到達（${POST_COUNT}/20）→ モニター終了"
  exit 0
fi

# ============================================================
# トレンド取得 & 前回との比較
# ============================================================
slog "トレンドチェック開始..."

CURRENT_TRENDS=$(python3 ~/google_metrics/fetch_trends.py 2>/dev/null || echo '{"combined":[]}')

PREVIOUS_CACHE="$CACHE_DIR/trends_previous.json"
CURRENT_CACHE="$CACHE_DIR/trends_current.json"

# 前回のトレンドと比較して新規急上昇を検出
NEW_BREAKING=$(python3 - "$CURRENT_TRENDS" "$PREVIOUS_CACHE" << 'PY'
import json, sys
from pathlib import Path

current = json.loads(sys.argv[1])
prev_file = Path(sys.argv[2])

current_kw = set(current.get("combined", []))

# 前回キャッシュ読み込み
prev_kw = set()
if prev_file.exists():
    try:
        prev = json.loads(prev_file.read_text())
        prev_kw = set(prev.get("combined", []))
    except Exception:
        pass

# K-POP関連フィルタ
kpop_markers = [
    'kpop', 'k-pop', 'bts', 'blackpink', 'twice', 'aespa', 'ive',
    'newjeans', 'le sserafim', 'stray kids', 'seventeen', 'nct',
    'riize', 'babymonster', 'illit', 'xg', 'exo', 'itzy', 'bigbang',
    'カムバック', 'カムバ', 'コンサート', 'ツアー', '来日', 'MV',
    '韓国', 'アイドル', 'K-POP', 'KPOP',
    'jimin', 'jungkook', 'jennie', 'lisa', 'rose', 'wonyoung',
    'karina', 'winter', 'hyunjin', 'felix',
]

new_keywords = current_kw - prev_kw
kpop_breaking = []

for kw in new_keywords:
    kw_lower = kw.lower()
    if any(marker in kw_lower for marker in kpop_markers):
        kpop_breaking.append(kw)

# 上位5件まで
print("\n".join(kpop_breaking[:5]) if kpop_breaking else "")
PY
)

# 現在のトレンドをキャッシュに保存
echo "$CURRENT_TRENDS" > "$CURRENT_CACHE"
cp "$CURRENT_CACHE" "$PREVIOUS_CACHE" 2>/dev/null || true

# ============================================================
# 速報判定 & 投稿トリガー
# ============================================================
if [ -z "$NEW_BREAKING" ]; then
  slog "新規K-POPトレンドなし → スキップ（本日${POST_COUNT}/20）"
  exit 0
fi

slog "⚡ K-POP速報トレンド検出!"
echo "$NEW_BREAKING" | while IFS= read -r kw; do
  slog "  → $kw"
done

# 投稿済みタイトルと重複しないかチェック
ALREADY_COVERED=$(python3 - "$TODAY_ISO" "$NEW_BREAKING" << 'PY'
import sys, json, urllib.request, base64, urllib.parse

today = sys.argv[1]
new_keywords = sys.argv[2].strip().split("\n")

after = today + "T00:00:00"
url = "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts?per_page=50&after=" + urllib.parse.quote(after) + "&status=publish"
auth = base64.b64encode(os.environ.get("WP_USER","kpop-bot").encode() + b":" + os.environ.get("WP_PASS","").encode()).decode()
req = urllib.request.Request(url, headers={"Authorization": "Basic " + auth})

try:
    with urllib.request.urlopen(req, timeout=15) as res:
        posts = json.loads(res.read())
    titles = " ".join(p.get("title", {}).get("rendered", "") for p in posts).lower()

    uncovered = []
    for kw in new_keywords:
        if kw.strip() and kw.lower() not in titles:
            uncovered.append(kw)
    print("\n".join(uncovered) if uncovered else "")
except Exception:
    print("\n".join(new_keywords))
PY
)

if [ -z "$ALREADY_COVERED" ]; then
  slog "検出トレンドは既に投稿済み → スキップ"
  exit 0
fi

# 速報投稿実行
BREAKING_TOPIC=$(echo "$ALREADY_COVERED" | head -1)
slog "⚡ 速報投稿トリガー: ${BREAKING_TOPIC}"
discord "⚡ 速報トレンド検出: ${BREAKING_TOPIC} → 緊急投稿開始"

# マスタースケジューラを速報モードで起動
bash ~/kpop_master_scheduler.sh --breaking >> "$LOG_FILE" 2>&1 || {
  slog "❌ 速報投稿失敗"
  discord "❌ 速報投稿失敗: ${BREAKING_TOPIC}"
}

slog "速報モニター完了"
