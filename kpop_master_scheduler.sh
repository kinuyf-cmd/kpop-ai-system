#!/bin/bash
# ============================================================
# kpop_master_scheduler.sh - マスター投稿スケジューラ
#
# 1日8〜20本の記事を6:00〜20:59に戦略的に投稿する
# cronから毎時呼び出され、時間帯に応じて最適なパイプラインを実行
#
# 使い方:
#   bash ~/kpop_master_scheduler.sh              # 通常実行
#   bash ~/kpop_master_scheduler.sh --breaking   # 速報モード（速報モニターから呼出）
#   bash ~/kpop_master_scheduler.sh --council    # 合議モード（高品質記事）
# ============================================================
set -euo pipefail

HOUR=$(date '+%H' | sed 's/^0//')
MINUTE=$(date '+%M')
TODAY=$(date '+%Y年%m月%d日')
TODAY_ISO=$(date '+%Y-%m-%d')
LOG_DIR="$HOME/kpop_scheduler_logs"
LOG_FILE="$LOG_DIR/scheduler_$(date '+%Y%m%d').log"
LOCK_FILE="/tmp/kpop_scheduler.lock"
WEBHOOK=$(cat ~/.kpop_discord_webhook 2>/dev/null | tr -d '[:space:]' || echo "")
MODE="${1:-auto}"

mkdir -p "$LOG_DIR"

slog() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"; }

discord() {
  [ -z "$WEBHOOK" ] && return
  python3 -c "
import requests, sys
requests.post(sys.argv[1], json={'content': sys.argv[2][:1900]}, timeout=10)
" "$WEBHOOK" "$1" 2>/dev/null || true
}

# ============================================================
# ロック機構（同時実行防止）
# ============================================================
if [ -f "$LOCK_FILE" ]; then
  LOCK_PID=$(cat "$LOCK_FILE" 2>/dev/null)
  if kill -0 "$LOCK_PID" 2>/dev/null; then
    slog "⚠ 別のスケジューラが実行中 (PID: $LOCK_PID) → スキップ"
    exit 0
  else
    slog "⚠ 古いロックファイル検出 → 削除"
    rm -f "$LOCK_FILE"
  fi
fi
echo $$ > "$LOCK_FILE"
trap "rm -f '$LOCK_FILE'" EXIT

# ============================================================
# 夜間ガード（21:00〜5:59は実行しない）
# ============================================================
if [ "$HOUR" -ge 21 ] || [ "$HOUR" -lt 6 ]; then
  slog "🌙 夜間帯（${HOUR}時）→ 投稿スキップ"
  exit 0
fi

# ============================================================
# 本日の投稿数チェック（WordPress API）
# ============================================================
get_today_post_count() {
  python3 - "$TODAY_ISO" << 'PY'
import sys, json, urllib.request, base64, urllib.parse
from datetime import datetime, timezone

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
}

POST_COUNT=$(get_today_post_count)
slog "📊 本日の投稿数: ${POST_COUNT}/8"

# 上限チェック（§5: 安定期は最大8本）
if [ "$POST_COUNT" -ge 8 ]; then
  slog "🛑 本日の投稿上限（8本）に到達 → 終了"
  discord "🛑 投稿上限到達（${POST_COUNT}/8）→ 本日の投稿終了"
  exit 0
fi

# ============================================================
# 最終投稿時刻チェック（連投防止: 最低20分間隔）
# ============================================================
LAST_POST_MINUTES=$(python3 - "$TODAY_ISO" << 'PY'
import sys, json, urllib.request, base64, urllib.parse
from datetime import datetime, timezone

today = sys.argv[1]
after = today + "T00:00:00"
url = "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts?per_page=1&after=" + urllib.parse.quote(after) + "&orderby=date&order=desc&status=publish"
auth = base64.b64encode(os.environ.get("WP_USER","kpop-bot").encode() + b":" + os.environ.get("WP_PASS","").encode()).decode()
req = urllib.request.Request(url, headers={"Authorization": "Basic " + auth})
try:
    with urllib.request.urlopen(req, timeout=15) as res:
        posts = json.loads(res.read())
    if posts:
        post_date = posts[0].get("date_gmt", "")
        post_dt = datetime.fromisoformat(post_date.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        diff = (now - post_dt).total_seconds() / 60
        print(int(diff))
    else:
        print("999")
except Exception:
    print("999")
PY
)

if [ "$MODE" != "--breaking" ] && [ "$LAST_POST_MINUTES" -lt 20 ]; then
  slog "⏳ 前回投稿から${LAST_POST_MINUTES}分 → 間隔不足（20分以上必要）→ スキップ"
  exit 0
fi

# ============================================================
# 昨日のCTR/メトリクスデータからコンテンツ方針を補強
# ============================================================
CTR_INSIGHTS=$(python3 - << 'PY'
import json
from pathlib import Path

metrics_file = Path.home() / "google_metrics" / "metrics_yesterday.json"
if not metrics_file.exists():
    print("メトリクスデータなし")
    exit()

d = json.loads(metrics_file.read_text())
gsc = d.get("gsc", {})
ga4 = d.get("ga4", {})

insights = []

# GSC: 高CTRクエリ → 需要あり、追加記事が有効
top_queries = gsc.get("top_queries", [])
high_ctr = [q for q in top_queries if q.get("ctr", 0) > 0.1 and q.get("impressions", 0) > 5]
if high_ctr:
    kws = ", ".join(q["query"] for q in high_ctr[:5])
    insights.append(f"高CTRキーワード（追加記事推奨）: {kws}")

# GSC: 高imp低CTR → タイトル改善 or 新規記事で補完
low_ctr_high_imp = [q for q in top_queries if q.get("ctr", 0) < 0.03 and q.get("impressions", 0) > 20]
if low_ctr_high_imp:
    kws = ", ".join(q["query"] for q in low_ctr_high_imp[:5])
    insights.append(f"高表示低CTR（競合が強い→差別化記事推奨）: {kws}")

# GSC: 高PVページのカテゴリ傾向
top_pages = gsc.get("top_pages", [])
if top_pages:
    # URLからカテゴリキーワードを抽出
    import re
    cats = {}
    for p in top_pages[:10]:
        url = p.get("page", "")
        slug = url.rstrip("/").split("/")[-1]
        for kw in ["event", "chart", "beauty", "cosme", "drama", "travel", "tour", "comeback"]:
            if kw in slug.lower():
                cats[kw] = cats.get(kw, 0) + p.get("clicks", 0)
    if cats:
        top_cat = max(cats, key=cats.get)
        insights.append(f"昨日の最人気カテゴリ: {top_cat}（クリック集中）")

# GA4: セッション数トップランディングページ
ga4_pages = ga4.get("top_landing_pages", [])
if ga4_pages and isinstance(ga4_pages, list) and len(ga4_pages) > 0:
    top = ga4_pages[0] if isinstance(ga4_pages[0], dict) else {}
    page = top.get("page", top.get("landingPagePlusQueryString", ""))
    if page:
        insights.append(f"昨日のPV1位: {page}")

print("\n".join(insights) if insights else "特記事項なし")
PY
)

# ============================================================
# 時間帯別コンテンツ戦略
# ============================================================
# ゴールデンタイム: 7-9, 12-13, 17-20 → 複数本投稿可能
# 通常タイム: 6, 10-11, 14-16 → 1本
#
# コンテンツタイプ:
#   breaking   - K-POP速報（kpop_pipeline.sh）
#   strategy   - 戦略記事・深掘り（kpop_strategy_pipeline.sh）
#   council    - 合議制高品質記事（agent_council.sh）
#   beauty     - 美容・コスメ系SEO記事
#   chart      - チャート・ランキング分析
#   lifestyle  - ドラマ・旅行・カフェ等

determine_content() {
  local hour=$1
  local post_count=$2

  case $hour in
    6)
      echo "beauty|kpop_pipeline|朝の美容記事：韓国スキンケア・基礎化粧品・モーニングルーティン系SEO記事（通勤時間帯の検索需要）※10時の美容記事とは切り口を変えること"
      ;;
    7)
      echo "breaking|kpop_pipeline|K-POP朝の速報・カムバック・ツアー情報"
      ;;
    8)
      if [ "$((post_count % 2))" -eq 0 ]; then
        echo "strategy|kpop_strategy|K-POPアーティスト深掘り・考察・比較記事"
      else
        echo "breaking|kpop_pipeline|K-POP最新ニュース・SNSで話題"
      fi
      ;;
    9)
      echo "breaking|kpop_pipeline|K-POP速報・韓国エンタメ最新情報"
      ;;
    10)
      echo "beauty|kpop_pipeline|美容記事：アイドルメイク・ヘアスタイル・ファッションコスメ系（6時のスキンケア記事とは別の切り口にすること）"
      ;;
    11)
      echo "strategy|kpop_strategy|K-POPアーティスト特集・ファンダム分析"
      ;;
    12)
      echo "chart|kpop_pipeline|チャート速報・ランキング・音楽番組結果（昼休み需要）"
      ;;
    13)
      echo "council|agent_council|合議制高品質K-POP記事（昼の高トラフィック帯）"
      ;;
    14)
      echo "breaking|kpop_pipeline|K-POP午後の速報・アーティスト最新ニュース"
      ;;
    15)
      echo "lifestyle|kpop_pipeline|ライフスタイル記事：韓国旅行・ソウルカフェ・グルメ・ポップアップストア（ドラマ記事は20時枠に回すこと）"
      ;;
    16)
      echo "strategy|kpop_strategy|K-POP比較・まとめ・考察記事"
      ;;
    17)
      echo "breaking|kpop_pipeline|K-POP夕方速報（帰宅時間帯の高需要）"
      ;;
    18)
      echo "council|agent_council|合議制高品質記事：ファッション・スタイル分析・衣装解説など（夜のゴールデンタイム）"
      ;;
    19)
      echo "breaking|kpop_pipeline|K-POP夜の速報・コンサート・イベントレポ"
      ;;
    20)
      echo "lifestyle|kpop_pipeline|ライフスタイル記事：韓国ドラマレビュー・配信視聴ガイド（15時の旅行・カフェ記事とは別ジャンルにすること）"
      ;;
    *)
      echo "breaking|kpop_pipeline|K-POP最新ニュース"
      ;;
  esac
}

# ============================================================
# パイプライン実行
# ============================================================
run_pipeline() {
  local content_type="$1"
  local pipeline="$2"
  local focus="$3"

  slog "🚀 パイプライン実行: ${pipeline} (${content_type})"
  slog "  テーマ: ${focus}"

  # 直近3日間の投稿タイトルを取得（全パイプライン共通・ネタ被り防止）
  local RECENT_POSTED
  RECENT_POSTED=$(python3 - <<'PYEOF'
import json, urllib.request, urllib.parse, base64, os
from datetime import datetime, timedelta, timezone
cutoff = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%S")
url = "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts?per_page=30&after=" + urllib.parse.quote(cutoff) + "&status=publish"
auth = base64.b64encode((os.environ.get("WP_USER","kpop-bot") + ":" + os.environ.get("WP_PASS","")).encode()).decode()
try:
    req = urllib.request.Request(url, headers={"Authorization": "Basic " + auth})
    with urllib.request.urlopen(req, timeout=10) as resp:
        posts = json.loads(resp.read())
    if not posts:
        print("（直近3日間の投稿なし）")
    else:
        for p in posts:
            print("- " + p["title"]["rendered"])
except Exception as e:
    print("（取得失敗: " + str(e)[:80] + "）")
PYEOF
  )
  slog "  直近3日間の投稿: $(echo "$RECENT_POSTED" | grep -c '^\-' || echo 0)件"

  case "$pipeline" in
    kpop_pipeline)
      # コンテンツタイプに応じたエージェント選択
      local agent="deoxys_kpop"
      case "$content_type" in
        beauty)   agent="beautywriter" ;;
        lifestyle)
          # ライフスタイル系でイベント・ポップアップ要素があればmewtwo_popup
          agent="deoxys_kpop"
          ;;
      esac

      TRENDS_JSON=$(python3 ~/google_metrics/fetch_trends.py 2>/dev/null || echo '{"combined":[]}')
      TREND_KEYWORDS=$(echo "$TRENDS_JSON" | python3 -c "
import json, sys
d = json.load(sys.stdin)
kw = d.get('combined', [])
print(', '.join(kw[:8]) if kw else 'なし')
" 2>/dev/null || echo "なし")

      # イベント・ポップアップ関連トレンドがあればmewtwo_popupを使用
      HAS_EVENT_TREND=$(echo "$TREND_KEYWORDS" | python3 -c "
import sys
kw = sys.stdin.read().lower()
events = ['ポップアップ','popup','イベント','展示','来日','コンサート','ライブ','ファンミ','チケット']
print('YES' if any(e in kw for e in events) else 'NO')
" 2>/dev/null || echo "NO")
      if [ "$HAS_EVENT_TREND" = "YES" ] && [ "$content_type" != "beauty" ]; then
        agent="mewtwo_popup"
        slog "  → イベントトレンド検出: mewtwo_popup使用"
      fi

      slog "  エージェント: ${agent}"

      cd ~ && claude --dangerously-skip-permissions --allowedTools WebSearch --agent "$agent" -p "
今日は${TODAY}です。現在${HOUR}時です。

【コンテンツ方針】
${focus}

【★最重要★ ネタ被り絶対禁止】
同じネタを繰り返すな。直近3日間の投稿と被らないテーマを選べ。
以下は直近3日間に既に投稿済みの記事タイトル一覧である。
これらと同じテーマ・同じ切り口・同じまとめ形式の記事を書くことは絶対に禁止。
特に「カムバックスケジュールまとめ」「カムバック一覧」「○月のカムバック予定」のような
まとめ・ラウンドアップ形式の記事が既にある場合、類似のまとめ記事は絶対に書くな。

【直近3日間の投稿済み記事（これらと被るテーマは禁止）】
${RECENT_POSTED}

【今日のトレンドキーワード（参考）】
${TREND_KEYWORDS}

【昨日のアクセスデータに基づく示唆】
${CTR_INSIGHTS}

上記の方針・トレンド・アクセスデータを踏まえて、直近投稿と完全に異なるテーマで記事を1本書いてください。
既に本日${POST_COUNT}本投稿済みです。
昨日のデータで需要が確認されたテーマがあれば積極的に活用してください。

【出力形式・絶対厳守】
1行目：タイトル文字列のみ
2行目：空行
3行目以降：<h2>から始まるHTML本文のみ
末尾に情報元と「※本記事は${TODAY}時点の情報です」を明記
" > reports/0_breaking.md 2>&1

      bash ~/kpop_pipeline.sh >> "$LOG_FILE" 2>&1
      ;;

    kpop_strategy)
      bash ~/kpop_strategy_pipeline.sh >> "$LOG_FILE" 2>&1
      ;;

    agent_council)
      bash ~/ai_company/agent_council.sh >> "$LOG_FILE" 2>&1
      ;;
  esac
}

# ============================================================
# ゴールデンタイム追加投稿判定
# ============================================================
should_double_post() {
  local hour=$1
  local count=$2

  # ゴールデンタイム（7-9, 12-13, 17-20）かつ投稿数が目標ペースを下回っている場合
  local is_golden=0
  case $hour in
    7|8|9|12|13|17|18|19|20) is_golden=1 ;;
  esac

  if [ "$is_golden" -eq 1 ]; then
    # 目標ペース: 残り時間で8本に到達するか
    local remaining_hours=$((20 - hour + 1))
    local needed=$((8 - count))
    if [ "$needed" -gt "$remaining_hours" ] && [ "$count" -lt 15 ]; then
      echo "YES"
      return
    fi
  fi
  echo "NO"
}

# ============================================================
# メイン実行
# ============================================================
slog ""
slog "════════════════════════════════════════"
slog "  マスタースケジューラ起動 ${HOUR}:${MINUTE}"
slog "  モード: ${MODE} / 本日投稿数: ${POST_COUNT}/20"
slog "════════════════════════════════════════"

# --- 速報モード ---
if [ "$MODE" = "--breaking" ]; then
  slog "⚡ 速報モード: 緊急投稿実行"
  run_pipeline "breaking" "kpop_pipeline" "K-POP緊急速報・トレンド急上昇ニュース"
  NEW_COUNT=$(get_today_post_count)
  slog "📊 投稿後の本日投稿数: ${NEW_COUNT}/20"
  discord "⚡ 速報投稿完了（本日${NEW_COUNT}/20）"
  exit 0
fi

# --- 合議モード ---
if [ "$MODE" = "--council" ]; then
  slog "🏛️ 合議モード: 高品質記事生成"
  run_pipeline "council" "agent_council" "K-POP合議制高品質記事"
  NEW_COUNT=$(get_today_post_count)
  slog "📊 投稿後の本日投稿数: ${NEW_COUNT}/20"
  discord "🏛️ 合議記事投稿完了（本日${NEW_COUNT}/20）"
  exit 0
fi

# --- 通常スケジュール ---
CONTENT_INFO=$(determine_content "$HOUR" "$POST_COUNT")
CONTENT_TYPE=$(echo "$CONTENT_INFO" | cut -d'|' -f1)
PIPELINE=$(echo "$CONTENT_INFO" | cut -d'|' -f2)
FOCUS=$(echo "$CONTENT_INFO" | cut -d'|' -f3)

slog "📋 コンテンツ: ${CONTENT_TYPE} → ${PIPELINE}"
slog "  テーマ: ${FOCUS}"

# 1本目実行
run_pipeline "$CONTENT_TYPE" "$PIPELINE" "$FOCUS" || {
  slog "❌ パイプライン失敗"
  discord "❌ スケジューラ: ${HOUR}時の${CONTENT_TYPE}投稿失敗"
}

# ゴールデンタイム追加投稿チェック
NEW_COUNT=$(get_today_post_count)
DOUBLE=$(should_double_post "$HOUR" "$NEW_COUNT")

if [ "$DOUBLE" = "YES" ] && [ "$NEW_COUNT" -lt 20 ]; then
  slog "⏰ ゴールデンタイム追加投稿（目標ペース不足）"

  # 追加投稿は別のコンテンツタイプで
  case $CONTENT_TYPE in
    breaking)  ADD_TYPE="strategy"; ADD_PIPE="kpop_strategy"; ADD_FOCUS="K-POP深掘り・考察記事" ;;
    strategy)  ADD_TYPE="breaking"; ADD_PIPE="kpop_pipeline"; ADD_FOCUS="K-POP最新速報" ;;
    council)   ADD_TYPE="breaking"; ADD_PIPE="kpop_pipeline"; ADD_FOCUS="K-POP速報ニュース" ;;
    beauty)    ADD_TYPE="breaking"; ADD_PIPE="kpop_pipeline"; ADD_FOCUS="K-POP最新ニュース" ;;
    *)         ADD_TYPE="breaking"; ADD_PIPE="kpop_pipeline"; ADD_FOCUS="K-POP最新ニュース" ;;
  esac

  slog "  追加: ${ADD_TYPE} → ${ADD_PIPE}"
  sleep 120  # 2分待機（連投防止）
  run_pipeline "$ADD_TYPE" "$ADD_PIPE" "$ADD_FOCUS" || slog "  ⚠ 追加投稿失敗"
fi

# 最終集計
FINAL_COUNT=$(get_today_post_count)
slog "📊 現在の本日投稿数: ${FINAL_COUNT}/20"
slog "════════════════════════════════════════"
slog ""
