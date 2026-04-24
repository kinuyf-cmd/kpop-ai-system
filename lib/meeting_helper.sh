#!/bin/bash
# ============================================================
# meeting_helper.sh — 部署別会議の共通基盤
# ============================================================

MEETING_BASE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$MEETING_BASE/lib/discord_channels.sh" 2>/dev/null || true

# 失敗しても継続するclaude呼び出し
# usage: safe_claude <agent> <prompt> <output_file>
safe_claude() {
  local agent="$1"
  local prompt="$2"
  local out="$3"
  local result
  if result=$(claude --dangerously-skip-permissions --agent "$agent" -p "$prompt" 2>&1); then
    echo "$result" > "$out"
    return 0
  else
    cat > "$out" <<EOF
【担当】${agent}
【結論】⚠ エージェント呼び出し失敗（非致命）
【詳細】$(echo "$result" | head -5)
【優先度】低
EOF
    return 1
  fi
}

# Discord送信（チャネル名とメッセージを受け取る）
meeting_discord_post() {
  local channel="$1"
  local msg="$2"
  local url
  url=$(get_discord_webhook "$channel" 2>/dev/null || echo "")
  [ -z "$url" ] && return 0
  curl -s -o /dev/null -X POST "$url" \
    -H "Content-Type: application/json" \
    -d "$(python3 -c "import json,sys; print(json.dumps({'content': sys.argv[1][:1950]}))" "$msg")" 2>/dev/null || true
}

# Phase 4: 前週KPIブリーフ取得（部署名を渡すと部署別に最適化）
# usage: weekly_kpi_brief [dept]
weekly_kpi_brief() {
  local dept="${1:-general}"
  python3 "$MEETING_BASE/lib/weekly_kpi_context.py" --brief --dept "$dept" 2>/dev/null || echo "【前週KPI】取得不可"
}

# 直近N日の投稿からカテゴリ分布を動的取得（ハードコード議題を回避）
category_balance_summary() {
  local days="${1:-3}"
  python3 - "$days" <<'PY'
import json, sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
JST = timezone(timedelta(hours=9))
now = datetime.now(JST)
cutoff = (now - timedelta(days=int(sys.argv[1]))).strftime("%Y-%m-%d")
kpi = Path("/home/aiuser/kpop-ai-system/logs/kpi_posts.jsonl")
cats = {}
titles = []
if kpi.exists():
    for line in kpi.read_text(errors="replace").splitlines():
        try:
            r = json.loads(line.strip())
            if r.get("date","") >= cutoff:
                c = r.get("article_type", "unknown")
                cats[c] = cats.get(c, 0) + 1
                titles.append(f"  [{c}] {r.get('title','')[:50]}")
        except: pass
total = sum(cats.values())
if total == 0:
    print("【直近投稿】データなし")
else:
    print(f"【直近{sys.argv[1]}日の投稿 {total}件 カテゴリ分布】")
    for c, n in sorted(cats.items(), key=lambda x: -x[1]):
        pct = n/total*100
        flag = " ⚠偏り" if pct >= 40 else ""
        print(f"  {c}: {n}本 ({pct:.0f}%){flag}")
    print("【直近タイトル】")
    print("\n".join(titles[-10:]))
PY
}
