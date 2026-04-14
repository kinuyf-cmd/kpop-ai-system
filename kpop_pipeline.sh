
#!/bin/bash
source "$(cd "$(dirname "$0")" && pwd)/env_loader.sh"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1日最大投稿数チェック（上限3本）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_DAILY_MAX="${DAILY_POST_LIMIT:-3}"
_TODAY=$(date +%Y-%m-%d)
_KPI_LOG="$(cd "$(dirname "$0")" && pwd)/logs/kpi_posts.jsonl"
_TODAY_COUNT=0
if [[ -f "$_KPI_LOG" ]]; then
  _TODAY_COUNT=$(grep -c "\"date\": \"${_TODAY}\"" "$_KPI_LOG" 2>/dev/null) || _TODAY_COUNT=0
fi
if [[ "$_TODAY_COUNT" -ge "$_DAILY_MAX" ]]; then
  echo "⛔ 本日の投稿上限（${_DAILY_MAX}本）に達しています（本日投稿済み: ${_TODAY_COUNT}本）" >&2
  echo "   投稿戦略ルール: logs/posting_strategy.md を参照してください" >&2
  exit 0
fi

# トークントラッキング（ENABLE_TOKEN_TRACKING=1 で有効化）
if [ "${ENABLE_TOKEN_TRACKING:-0}" = "1" ]; then
  source "$(cd "$(dirname "$0")" && pwd)/lib/claude_wrapper.sh"
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# トピック予約: 並列パイプラインの重複防止
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TOPIC_LOCK_FILE="/tmp/kpop_pipeline_topics.lock"
TOPIC_LOCK_DIR="/tmp/kpop_pipeline_topics.lockdir"

# 古い予約エントリ（1時間超）を削除し、ファイルアトミック操作のためflockを使用
cleanup_old_reservations() {
  local now
  now=$(date +%s)
  local tmp_clean
  tmp_clean=$(mktemp)
  if [[ -f "$TOPIC_LOCK_FILE" ]]; then
    while IFS='|' read -r ts pid topic; do
      # 1時間=3600秒 以内のエントリのみ残す
      if [[ -n "$ts" ]] && [[ $((now - ts)) -lt 3600 ]]; then
        # PIDがまだ生きているか確認（死んだプロセスの予約は除去）
        if kill -0 "$pid" 2>/dev/null; then
          echo "${ts}|${pid}|${topic}" >> "$tmp_clean"
        fi
      fi
    done < "$TOPIC_LOCK_FILE"
  fi
  mv "$tmp_clean" "$TOPIC_LOCK_FILE" 2>/dev/null || true
}

# トピックを予約ファイルに登録（排他ロック付き）
reserve_topic() {
  local topic="$1"
  (
    flock -w 10 200 || { echo "⚠️ トピック予約: ロック取得失敗"; return 1; }
    cleanup_old_reservations
    echo "$(date +%s)|$$|${topic}" >> "$TOPIC_LOCK_FILE"
  ) 200>"${TOPIC_LOCK_FILE}.flock"
}

# 予約済みトピックとの類似チェック（排他ロック付き）
# 戻り値: 0=重複なし, 1=類似トピックあり
check_topic_reservation() {
  local new_topic="$1"
  local result
  result=$(
    flock -w 10 200 || { echo "SKIP"; exit 0; }
    cleanup_old_reservations
    if [[ ! -s "$TOPIC_LOCK_FILE" ]]; then
      echo "OK"
      exit 0
    fi
    # 予約済みトピック一覧を取得（自分のPID以外）
    local reserved_topics=""
    while IFS='|' read -r ts pid topic; do
      if [[ "$pid" != "$$" ]] && [[ -n "$topic" ]]; then
        reserved_topics="${reserved_topics}${topic}"$'\n'
      fi
    done < "$TOPIC_LOCK_FILE"
    if [[ -z "$reserved_topics" ]]; then
      echo "OK"
      exit 0
    fi
    # Claudeで類似度を判定
    local sim
    sim=$(claude --no-session-persistence -p "
【タスク】トピック類似チェック（並列パイプライン重複防止）
新しいトピックが、現在他のパイプラインが執筆中のトピックと重複しているか判定せよ。

【新トピック】${new_topic}

【現在執筆中のトピック一覧】
${reserved_topics}

【判定基準】
- 同じアーティスト＋同じイベント/テーマ → 重複（YES）
- 同じテーマのまとめ記事同士 → 重複（YES）
- 同じアーティストでも別テーマ → 重複なし（NO）
- 完全に別のアーティスト/テーマ → 重複なし（NO）

【出力】YESまたはNOの1単語のみ。
" 2>/dev/null | tr -d '[:space:]')
    echo "$sim"
  ) 200>"${TOPIC_LOCK_FILE}.flock"

  if [[ "$result" == "YES" ]]; then
    return 1
  fi
  return 0
}

# パイプライン終了時にトピック予約を解除
release_topic_reservation() {
  if [[ -f "$TOPIC_LOCK_FILE" ]]; then
    (
      flock -w 10 200 || return
      local tmp_rel
      tmp_rel=$(mktemp)
      grep -v "^[0-9]*|$$|" "$TOPIC_LOCK_FILE" > "$tmp_rel" 2>/dev/null || true
      mv "$tmp_rel" "$TOPIC_LOCK_FILE" 2>/dev/null || true
    ) 200>"${TOPIC_LOCK_FILE}.flock"
  fi
}
trap release_topic_reservation EXIT

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# パイプラインログ: logs/pipeline.jsonl
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PIPELINE_JSONL="$SCRIPT_DIR/logs/pipeline.jsonl"
mkdir -p "$SCRIPT_DIR/logs"

log_step() {
  local step="$1" status="$2" file="${3:-}" msg="${4:-}"
  local ts sz
  ts=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
  if [[ -n "$file" && -f "$file" ]]; then
    sz=$(wc -c < "$file")
  else
    sz=0
  fi
  # JSON安全化: ダブルクォートとバックスラッシュをエスケープ
  msg="${msg//\\/\\\\}"
  msg="${msg//\"/\\\"}"
  printf '{"timestamp":"%s","run_id":"%s","step":"%s","status":"%s","file":"%s","size_bytes":%d,"message":"%s"}\n' \
    "$ts" "${RUN_ID:-unknown}" "$step" "$status" "$file" "$sz" "$msg" >> "$PIPELINE_JSONL"
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ユーティリティ: 出力検証関数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
check_output() {
  local file="$1"
  local step="$2"
  if [[ ! -s "$file" ]]; then
    echo "❌ [$step] 出力が空 → パイプライン停止"
    log_step "$step" "error" "$file" "出力が空（check_output）"
    archive_and_exit 1
  fi
  # 極小ファイル（500バイト未満）は記事として不十分 → エラー応答の疑い（定型文1行通過防止）
  local _sz
  _sz=$(wc -c < "$file" 2>/dev/null || echo 0)
  if [[ "$_sz" -lt 500 ]]; then
    echo "❌ [$step] 出力が極小 (${_sz}bytes < 500) → エラー応答の疑い → パイプライン停止"
    echo "  内容: $(cat "$file")"
    log_step "$step" "error" "$file" "出力極小: ${_sz}bytes（エラー応答の疑い）"
    archive_and_exit 1
  fi
  # 先頭行がHTMLコメントのみ → デオキシスがメタデータコメントを先頭に出力したケース（本文なし扱い）
  # ただし article-type / TITLE_LOG などの既知メタデータコメントは正常出力のため除外
  local _first_line
  _first_line=$(head -1 "$file")
  if [[ "$_first_line" =~ ^\s*\<!--.*--\>\s*$ ]] && \
     ! [[ "$_first_line" =~ article-type|TITLE_LOG|pipeline-meta ]]; then
    echo "❌ [$step] 先頭行がHTMLコメントのみ → 本文なし扱い → パイプライン停止"
    echo "  先頭行: $_first_line"
    log_step "$step" "error" "$file" "先頭行HTMLコメントのみ（本文なし）"
    archive_and_exit 1
  fi
  if grep -qE '申し訳ありません[がで。、 ]|申し訳ありません$|お手伝いできますか|許可してください|許可が必要です|確認させてください|WebSearchを使用|ウェブ検索の許可|許可を?いただ|入力記事が見当たりません|記事の入力が見当たりません|チェック対象の記事本文を貼り付けてください|記事を提供してください|記事の元となるコンテンツ|リライトしたい記事の本文|元となる記事の原文|ウェブフェッチはできません|ウェブフェッチ(は|が|でき)|ユーザーから記事のソース|元の記事が提供されていません|記事本文・題材・元記事URL|対象アーティスト・トピック・元記事内容を貼り付け|元ネタが見当たりません|リライト対象の記事本文を貼り付け|記事の元となる情報.*を提供してください|元記事.*を提供してください|元記事.*を貼り付けてください|読んでいただきありがとうございます.*提供してください|このチャットに貼り付けてください|元情報.*を.*貼り付け|ドラフト文章.*貼り付け|アーティスト名.*イベント詳細.*日付.*貼り付け|記事の元情報が貼り付けられていません|貼り付けられていません|このチャットに貼り付け|タイトルを入力してください|評価対象がありません' "$file"; then
    echo "❌ [$step] エラー応答を検出 → パイプライン停止"
    echo "  先頭行: $(head -1 "$file")"
    log_step "$step" "error" "$file" "エラー応答検出（boilerplate）: $(head -1 "$file")"
    archive_and_exit 1
  fi
  echo "  ✓ [$step] OK"
}

cleanup_reports_dir() {
  # run専用reportsディレクトリを削除し、シンボリックリンクも解除
  if [[ -n "${REPORTS_DIR:-}" ]] && [[ -d "$REPORTS_DIR" ]]; then
    rm -rf "$REPORTS_DIR"
  fi
  if [[ -L "$SCRIPT_DIR/reports" ]]; then
    rm -f "$SCRIPT_DIR/reports"
  elif [[ -d "$SCRIPT_DIR/reports" ]]; then
    rm -rf "$SCRIPT_DIR/reports"
  fi
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# pre_publish_gate: 投稿前品質ゲート
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
pre_publish_gate() {
  local title="${1:-}"
  local content_file="${2:-/tmp/kpop_content.txt}"
  local aioseo_desc="${3:-}"
  local slug="${4:-}"

  local block_reasons=()
  local warn_reasons=()
  local gate_pass=true

  # [1] タイトル崩壊チェック
  if [[ -z "$title" ]]; then
    block_reasons+=("タイトル空")
  elif [[ "${#title}" -lt 10 ]]; then
    block_reasons+=("タイトル短すぎ(${#title}文字)")
  else
    # AIボイラープレート検出
    if echo "$title" | grep -qE "以下に完成記事|以下がリライト|記事を生成します|入力記事が見当たりません|提供してください|確認させてください"; then
      block_reasons+=("タイトルにAIボイラープレート検出")
    fi
  fi

  # [2] コンテンツ最低品質チェック
  if [[ -f "$content_file" ]]; then
    local content_size
    content_size=$(wc -c < "$content_file" 2>/dev/null || echo 0)
    if [[ "$content_size" -lt 3000 ]]; then
      block_reasons+=("コンテンツサイズ不足(${content_size}bytes < 3000)")
    fi
    # エラーボイラープレート検出
    if grep -qE "以下に完成記事|記事を生成します|入力記事が見当たりません|ウェブフェッチできません" "$content_file" 2>/dev/null; then
      block_reasons+=("コンテンツにエラーボイラープレート検出")
    fi
  fi

  # [3] メタディスクリプション（110〜130文字）
  if [[ -z "$aioseo_desc" ]]; then
    block_reasons+=("AIOSEO_DESC未設定")
  elif [[ "${#aioseo_desc}" -lt 110 ]]; then
    block_reasons+=("AIOSEO_DESC短すぎ(${#aioseo_desc}文字 < 110)")
  elif [[ "${#aioseo_desc}" -gt 130 ]]; then
    block_reasons+=("AIOSEO_DESC長すぎ(${#aioseo_desc}文字 > 130)")
  fi

  # [4] スラッグ品質チェック
  if [[ -n "$slug" ]]; then
    # 先頭が数字 → 禁止（数字のみ・年+数字・数字始まり全般）
    if [[ "$slug" =~ ^[0-9] ]]; then
      block_reasons+=("スラッグが数字始まり（禁止）: '$slug'")
    fi
    if [[ "$slug" =~ ^[0-9]+$ ]]; then
      block_reasons+=("スラッグが純粋な数字: '$slug'")
    fi
    # T.O.P表記が残存している場合（slug_generatorで変換済みのはずだが念のため）
    if echo "$slug" | grep -qi "t\.o\.p\|t-o-p"; then
      block_reasons+=("スラッグにT.O.P表記残存（topに変換必須）: '$slug'")
    fi
    # アーティスト/キーワードトークン数チェック（ハイフン区切りで最低2語）
    local slug_token_count
    slug_token_count=$(echo "$slug" | tr '-' '\n' | grep -cE "[a-z]{2,}" || echo 0)
    if [[ "$slug_token_count" -lt 2 ]]; then
      block_reasons+=("スラッグのキーワードトークン不足(${slug_token_count}語)")
    fi
  fi

  # [5] 重複チェック（WP APIで直近10件のタイトルを取得）
  local dup_title
  dup_title=$(python3 - << 'DUPPY' "$title" 2>/dev/null || echo "")
import sys, json, urllib.request, re

title = sys.argv[1]
def token_overlap(a, b):
    ta = set(re.findall(r'[\w]+', a.lower()))
    tb = set(re.findall(r'[\w]+', b.lower()))
    if not ta or not tb: return 0.0
    return len(ta & tb) / len(ta | tb)

try:
    url = "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts?per_page=10&orderby=date&order=desc&_fields=id,title"
    req = urllib.request.Request(url, headers={"User-Agent": "kpop-gate/1.0"})
    with urllib.request.urlopen(req, timeout=6) as resp:
        posts = json.loads(resp.read())
    for p in posts:
        t2 = p.get("title", {})
        t2 = t2.get("rendered", "") if isinstance(t2, dict) else str(t2)
        sim = token_overlap(title, t2)
        if sim >= 0.70:
            print(f"ID={p.get('id')} sim={sim:.0%}: {t2[:60]}")
            sys.exit()
except Exception:
    pass
DUPPY
  if [[ -n "$dup_title" ]]; then
    block_reasons+=("類似タイトルの記事が既存: $dup_title")
  fi

  # [6] サムネイルコピー品質チェック（全違反BLOCK）
  local thumb_copy="${THUMB_TITLE:-}"
  if [[ -n "$thumb_copy" ]]; then
    # 禁止パターン
    if [[ "$thumb_copy" == *".."* ]] || [[ "$thumb_copy" == *"…"* ]]; then
      block_reasons+=("サムネイルコピーに'..'/'…'検出（禁止）: '$thumb_copy'")
    fi
    if [[ "$thumb_copy" == *"「」"* ]]; then
      block_reasons+=("サムネイルコピーに「」空パターン検出（禁止）: '$thumb_copy'")
    fi
    # 2行構成チェック（改行区切り）
    local thumb_line_count
    thumb_line_count=$(echo "$thumb_copy" | wc -l)
    if [[ "$thumb_line_count" -lt 2 ]]; then
      block_reasons+=("サムネイルコピーが1行のみ（2行構成必須）: '$thumb_copy'")
    else
      # 各行15文字以内チェック
      local thumb_line_ok=true
      while IFS= read -r line; do
        [[ -z "$line" ]] && continue
        if [[ "${#line}" -gt 15 ]]; then
          block_reasons+=("サムネイルコピー行が15文字超(${#line}文字): '$line'")
          thumb_line_ok=false
        fi
      done <<< "$thumb_copy"
    fi
    # 固有名詞・数字・感情要素のいずれか必須
    local has_artist has_number has_emotion
    has_artist=$(echo "$thumb_copy" | grep -ciE "BTS|TWICE|BLACKPINK|IVE|ILLIT|aespa|NewJeans|ENHYPEN|TXT|Stray|SEVENTEEN|NCT|ATEEZ|TOP|RIIZE|LE SSERAFIM|aespa|EXO|GOT7|MAMAMOO|ATEEZ" || true)
    has_number=$(echo "$thumb_copy" | grep -cE "[0-9]" || true)
    has_emotion=$(echo "$thumb_copy" | grep -ciE "制覇|記録|復帰|衝撃|独占|最高|伝説|解禁|初|号泣|歴史|快挙|圧倒|無双|覚醒|爆発|崩壊|激震|話題|炎上" || true)
    if [[ "$has_artist" -eq 0 ]] && [[ "$has_number" -eq 0 ]] && [[ "$has_emotion" -eq 0 ]]; then
      block_reasons+=("サムネイルコピーに固有名詞・数字・感情要素のいずれもなし（CTR必須条件未達）: '$thumb_copy'")
    fi
  fi

  # [7] CTRスコアチェック（タイトルベース・60未満BLOCK）
  local ctr_score=0
  if [[ -n "$title" ]]; then
    ctr_score=$(python3 - << 'CTRPY' "$title"
import sys, re
t = sys.argv[1]
score = 0
# 数字あり +20
if re.search(r'[0-9０-９]', t): score += 20
# 対比構造 +20（vs/→/から/より/でも/なのに/ただし）
if re.search(r'(vs|→|から|より|でも|なのに|ただし|なぜ|なのか|？|？)', t): score += 20
# 固有名詞 +20
if re.search(r'BTS|TWICE|BLACKPINK|IVE|ILLIT|aespa|NewJeans|ENHYPEN|TXT|SEVENTEEN|NCT|ATEEZ|TOP|RIIZE|LE SSERAFIM|EXO|GOT7|MAMAMOO', t, re.IGNORECASE): score += 20
# 感情ワード +20
if re.search(r'制覇|記録|復帰|衝撃|独占|最高|伝説|解禁|初|号泣|歴史|快挙|圧倒|無双|覚醒|爆発|崩壊|激震|1位|首位|全米|全英|Billboard', t): score += 20
# 32文字以内 +20
if len(t) <= 32: score += 20
print(score)
CTRPY
)
    if [[ "$ctr_score" -lt 60 ]]; then
      block_reasons+=("CTRスコア不足(${ctr_score}/100 < 60): タイトル='$title'")
    fi
  fi

  # ── 結果ログ・判定 ─────────────────────────────────────────────────────
  local all_issues=""
  for r in "${block_reasons[@]}"; do all_issues="$all_issues|BLOCK:$r"; done
  for w in "${warn_reasons[@]}"; do all_issues="$all_issues|WARN:$w"; done

  log_step "pre_publish_gate" "$([ ${#block_reasons[@]} -eq 0 ] && echo ok || echo BLOCKED)" "" "${all_issues:1}"

  if [[ ${#warn_reasons[@]} -gt 0 ]]; then
    echo "  ⚠️ [pre_publish_gate] 警告:"
    for w in "${warn_reasons[@]}"; do
      echo "      - $w"
    done
  fi

  if [[ ${#block_reasons[@]} -gt 0 ]]; then
    echo "❌ [pre_publish_gate] 投稿ブロック理由:"
    for r in "${block_reasons[@]}"; do
      echo "    - $r"
    done
    return 1
  fi

  echo "  ✅ [pre_publish_gate] 全チェック通過"
  return 0
}

archive_and_exit() {
  local code="${1:-1}"
  if [[ "$code" -ne 0 ]]; then
    log_step "pipeline" "error" "" "archive_and_exit code=$code"
  fi
  if [[ -n "$ARCHIVE_DIR" ]]; then
    mkdir -p "$ARCHIVE_DIR"
    cp reports/* "$ARCHIVE_DIR/" 2>/dev/null
    cat > "$ARCHIVE_DIR/summary.txt" << SUMMARY
実行ID      : $RUN_ID
パイプライン: speed
日時        : $TODAY
判定        : 停止
SUMMARY
    echo "  アーカイブ保存: $ARCHIVE_DIR"
  fi
  cleanup_reports_dir
  bash $SCRIPT_DIR/kpop_notify.sh error "ニュース" "パイプライン停止 (RUN: $RUN_ID)" 2>/dev/null
  # 異常検知: エラーログ記録 + 連続失敗チェック
  python3 "$SCRIPT_DIR/lib/kpi_logger.py" log_error "{\"error_type\":\"pipeline_stop\",\"message\":\"RUN $RUN_ID stopped\",\"recoverable\":true}" 2>/dev/null || true
  python3 "$SCRIPT_DIR/lib/human_gate.py" check 2>/dev/null || true
  exit "$code"
}

wp_health_check() {
  echo "=== WordPress 接続確認 ==="
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
    "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts?per_page=1" \
    -K ~/.wp_auth \
    --connect-timeout 10 --max-time 15)
  if [[ "$HTTP_CODE" != "200" ]]; then
    echo "❌ WordPress API 接続失敗 (HTTP ${HTTP_CODE}) → パイプライン停止"
    bash $SCRIPT_DIR/kpop_notify.sh error "速報" "WordPress API 接続失敗 (HTTP ${HTTP_CODE})" 2>/dev/null
    exit 1
  fi
  echo "  ✓ WordPress API 正常 (HTTP ${HTTP_CODE})"
}

check_duplicate() {
  local title="$1"
  local days="${2:-2}"
  echo "=== 重複投稿チェック（過去${days}日）==="

  RECENT_TITLES=$(python3 - "$days" <<'PYEOF'
import sys, json, urllib.request, base64, urllib.parse, os
from datetime import datetime, timedelta, timezone
days = int(sys.argv[1])
cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
url = "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts?per_page=30&after=" + urllib.parse.quote(cutoff)
auth = base64.b64encode(os.environ.get("WP_USER","kpop-bot").encode() + b":" + os.environ.get("WP_PASS","").encode()).decode()
req = urllib.request.Request(url, headers={"Authorization": "Basic " + auth})
try:
    with urllib.request.urlopen(req, timeout=10) as res:
        posts = json.loads(res.read())
    print("\n".join(p.get("title", {}).get("rendered", "") for p in posts))
except Exception:
    print("")
PYEOF
  )

  if [[ -z "$RECENT_TITLES" ]]; then
    echo "  ⚠️  投稿履歴取得失敗 → チェックスキップ"
    return 0
  fi

  echo "  直近${days}日の投稿: $(echo "$RECENT_TITLES" | grep -c .)件"

  SIMILARITY=$(claude --no-session-persistence -p "
【タスク】類似記事重複チェック
新しく投稿しようとしている記事タイトルが、過去${days}日間の投稿済みタイトルと内容が重複しているか判定せよ。
【新タイトル】${title}
【過去${days}日間の投稿済みタイトル】
${RECENT_TITLES}
【判定基準（厳格に適用）】
- 同じアーティスト＋同じイベント＋同じ時期 → 重複（YES��
- 同じテーマのまとめ・ラウンドアップ記事（例：カムバックスケジュールまとめが既にあるのに再度カムバック一覧を書く）→ 重複（YES）
- 同じカテゴリの総まとめ・一覧系記事が既にある場合（例：4月のカムバック予定 vs 2025年春のカムバックまとめ）→ 重複（YES）
- 美容・スキンケア・ガラス肌・韓国コスメ・Kビューティ系記事が過去${days}日に既に1本以上ある → 重複（YES）
- 同じアー��ィストでも別イベント・別テーマ → 重複なし（NO）
- チャートランキングは毎週異なるため常に重複なし（NO）
【出力ルール】YESまたはNOの1単語のみ。他は出力禁止。
")

  if [[ "$SIMILARITY" == "YES" ]]; then
    echo "  ⚠️  重複あり: 類似記事が過去${days}日以内に投稿済み → スキップ"
    echo "    新タイトル: $title"
    archive_and_exit 0
  fi

  echo "  ✓ 重複なし"
}

source "$SCRIPT_DIR/lib/sanitize_output.sh"

# テーマ記事・速報共通: 許可要求禁止の共通プロンプト
NO_CONV_RULE='【★絶対禁止★】許可要求・質問・会話文・説明文を一切出力するな。「許可が必要」「WebSearchの許可」「確認させてください」等を含む出力は自動BLOCKされる。完成記事のみ出力せよ。'

THEME_INPUT="${1:-}"
# マスタースケジューラが事前に記事を生成した場合はスキップフラグを立てる
# 呼び出し例: DEOXYS_PREBUILT=1 bash kpop_pipeline.sh
DEOXYS_PREBUILT="${DEOXYS_PREBUILT:-0}"
# ゴシップ記事フラグ（kpop_master_scheduler.sh の gossip content_type から渡される）
# 呼び出し例: GOSSIP_MODE=1 DEOXYS_PREBUILT=1 bash kpop_pipeline.sh
GOSSIP_MODE="${GOSSIP_MODE:-0}"

TODAY=$(date '+%Y年%m月%d日')
RUN_ID=$(date '+%Y%m%d_%H%M%S')
PIPELINE_START=$(date +%s)
ARCHIVE_DIR=~/kpop_archives/$RUN_ID

# run_idごとに reports を分離（並列実行時のファイル競合を防止）
REPORTS_DIR="$SCRIPT_DIR/reports_${RUN_ID}"
mkdir -p "$REPORTS_DIR"
# DEOXYS_PREBUILT=1 時: マスタースケジューラが書いた 0_breaking.md を新ディレクトリに引き継ぐ
# (reports リセット前にバックアップ)
_PREBUILT_CONTENT=""
if [[ "${DEOXYS_PREBUILT:-0}" == "1" ]]; then
  _PREBUILT_SRC=""
  if [[ -L "$SCRIPT_DIR/reports" ]] && [[ -s "$SCRIPT_DIR/reports/0_breaking.md" ]]; then
    _PREBUILT_SRC="$SCRIPT_DIR/reports/0_breaking.md"
  elif [[ -f "$SCRIPT_DIR/reports/0_breaking.md" ]] && [[ -s "$SCRIPT_DIR/reports/0_breaking.md" ]]; then
    _PREBUILT_SRC="$SCRIPT_DIR/reports/0_breaking.md"
  fi
  if [[ -n "$_PREBUILT_SRC" ]]; then
    _PREBUILT_CONTENT=$(cat "$_PREBUILT_SRC")
  fi
fi
# シンボリックリンクと実ディレクトリの両方に対応
if [[ -L "$SCRIPT_DIR/reports" ]]; then
  rm -f "$SCRIPT_DIR/reports"
elif [[ -d "$SCRIPT_DIR/reports" ]]; then
  rm -rf "$SCRIPT_DIR/reports"
fi
ln -sfn "$REPORTS_DIR" "$SCRIPT_DIR/reports"
# DEOXYS_PREBUILT=1 時: 引き継いだ記事を新ディレクトリに復元
if [[ "${DEOXYS_PREBUILT:-0}" == "1" ]] && [[ -n "$_PREBUILT_CONTENT" ]]; then
  echo "$_PREBUILT_CONTENT" > "$SCRIPT_DIR/reports/0_breaking.md"
fi
export TOKEN_LOG="$ARCHIVE_DIR/token_usage.jsonl"

echo "========================================"
echo " K-POPニュースパイプライン 開始: $TODAY"
echo " 実行ID: $RUN_ID"
echo " THEME_INPUT=$THEME_INPUT"
echo "========================================"
wp_health_check

echo "=== [0] ミュウツー: 戦略判断 ==="
# 直近の投稿タイトルを取得（ネタ被り防止・戦略判断用）
# ※認証付きで取得（認証なしだとサイト設定によっては全件失敗する）
RECENT_POSTED=$(python3 - <<'PYEOF'
import json, urllib.request, urllib.parse, base64, os
from datetime import datetime, timedelta, timezone
cutoff = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%S")
auth = base64.b64encode((os.environ.get("WP_USER","kpop-bot") + ":" + os.environ.get("WP_PASS","")).encode()).decode()
posts = []
# 公開済み記事（過去3日間）
url_publish = "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts?per_page=30&after=" + urllib.parse.quote(cutoff) + "&status=publish"
try:
    req = urllib.request.Request(url_publish, headers={"Authorization": "Basic " + auth})
    with urllib.request.urlopen(req, timeout=10) as resp:
        posts += json.loads(resp.read())
except Exception:
    pass
# 下書き・予約・レビュー中の記事も取得（キャッシュ遅延で公開済みに反映されない当日記事をカバー）
for st in ["draft", "pending", "future"]:
    url_extra = "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts?per_page=15&after=" + urllib.parse.quote(cutoff) + "&status=" + st
    try:
        req = urllib.request.Request(url_extra, headers={"Authorization": "Basic " + auth})
        with urllib.request.urlopen(req, timeout=10) as resp:
            posts += json.loads(resp.read())
    except Exception:
        pass
# 並列パイプラインの予約トピックも追加
lock_file = "/tmp/kpop_pipeline_topics.lock"
try:
    with open(lock_file, encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split("|", 2)
            if len(parts) == 3 and parts[1] != str(os.getpid()):
                posts.append({"title": {"rendered": parts[2] + " [執筆中]"}})
except Exception:
    pass
# 重複除去（タイトルベース）
seen = set()
unique_posts = []
for p in posts:
    t = p.get("title", {}).get("rendered", "")
    if t and t not in seen:
        seen.add(t)
        unique_posts.append(p)
posts = unique_posts
try:
    if not posts:
        print("（直近3日間の投稿なし）")
    else:
        for p in posts:
            print("- " + p["title"]["rendered"])
except Exception as e:
    print("（取得失敗: " + str(e)[:80] + "）")
PYEOF
)
echo "  直近3日間の投稿タイトル取得: $(echo "$RECENT_POSTED" | grep -c '^\-' || echo 0)件"

if [[ -z "$THEME_INPUT" ]]; then
  # テーマ未指定時: ミュウツーが戦略判断
  STRATEGY_BRIEF=$(claude --no-session-persistence --allowedTools WebSearch -p "
今日は${TODAY}です。あなたはK-POPメディアの編集長です。

【★最重要★ ネタ被り絶対禁止】
同じネタを繰り返すな。直近3日間の投稿と被らないテーマを選べ。
以下は直近3日間に既に投稿済みの記事タイトル一覧である。
これらと同じテーマ・同じ切り口・同じまとめ形式の記事を選ぶことは絶対に禁止。
特に「カムバックスケジュールまとめ」「カムバック一覧」「○月のカムバック予定」のような
まとめ・ラウンドアップ形式の記事が既にある場合、類似のまとめ記事は絶対に選ぶな。

【直近3日間の投稿済み記事（これらと被るテーマは禁止）】
${RECENT_POSTED}

上記と完全に異なるテーマ・切り口で、今日書くべきK-POP記事を1本決定せよ。

【判断基準（この順番で評価）】
1. 重複回避：上記の投稿済み記事と同じテーマ・切り口でないこと（最優先）
2. 時事性：24時間以内の新情報はあるか？（速報候補）
3. 検索需要：今ファンが検索しているキーワードは何か？
4. 差別化：他メディアがまだ書いていない切り口はあるか？
5. カテゴリバランス：直近の記事が速報ばかりなら、美容・旅行・イベント・解説に振る

【速報(YES)の厳格な基準 - v1.3】
速報=YESにしてよいのは以下のみ：
- 24時間以内のスキャンダル・緊急発表・突発事件
速報=NOにすべきもの（絶対にYESにしない）：
- カムバックスケジュールまとめ・一覧記事
- ランキング・チャート記事
- イベントリスト・カレンダー記事
- 分析・考察・振り返り記事
- 既知情報のまとめ・解説記事

【出力形式（厳守）】
1行目：記事テーマ（1行、簡潔に）
2行目：速報かどうか（YES or NO）
3行目：推奨カテゴリ（速報/カムバック/美容/旅行/イベント/ファッション/解説/ゴシップ のどれか）
※3行のみ出力。説明禁止。
" 2>/dev/null | head -3)

  THEME_FROM_MEWTWO=$(echo "$STRATEGY_BRIEF" | head -1)
  IS_BREAKING=$(echo "$STRATEGY_BRIEF" | sed -n '2p')
  CATEGORY_HINT=$(echo "$STRATEGY_BRIEF" | sed -n '3p')
  echo "  ミュウツー判断: $THEME_FROM_MEWTWO"
  echo "  速報: $IS_BREAKING / カテゴリ: $CATEGORY_HINT"
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# トピック予約チェック: 並列パイプライン重複防止
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CHOSEN_TOPIC="${THEME_INPUT:-$THEME_FROM_MEWTWO}"
if [[ -n "$CHOSEN_TOPIC" ]]; then
  echo "=== [0.5] トピック予約チェック ==="
  if ! check_topic_reservation "$CHOSEN_TOPIC"; then
    echo "  ⚠️ 類似トピックが他のパイプラインで執筆中 → パイプライン停止"
    echo "  トピック: $CHOSEN_TOPIC"
    bash $SCRIPT_DIR/kpop_notify.sh error "ニュース" "トピック重複検出で停止: $CHOSEN_TOPIC (RUN: $RUN_ID)" 2>/dev/null
    archive_and_exit 0
  fi
  echo "  ✓ トピック重複なし → 予約登録"
  reserve_topic "$CHOSEN_TOPIC"
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 自律改善ディレクティブ読み込み（週次レビューで自動更新）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DEOXYS_DIRECTIVE=$(python3 "$SCRIPT_DIR/lib/auto_improve.py" directive --agent deoxys 2>/dev/null || echo "")
METAMON_DIRECTIVE=$(python3 "$SCRIPT_DIR/lib/auto_improve.py" directive --agent metamon 2>/dev/null || echo "")
EEVEE_DIRECTIVE=$(python3 "$SCRIPT_DIR/lib/auto_improve.py" directive --agent eevee 2>/dev/null || echo "")
GARDEVOIR_DIRECTIVE=$(python3 "$SCRIPT_DIR/lib/auto_improve.py" directive --agent gardevoir_hook_critic 2>/dev/null || echo "")

echo "=== [1] デオキシス: 記事化 ==="
if [[ "$DEOXYS_PREBUILT" == "1" ]] && [[ -s reports/0_breaking.md ]]; then
  echo "  → DEOXYS_PREBUILT: マスタースケジューラ生成の記事を使用（再生成スキップ）"
  # SOURCE_FAILチェックは引き続き実施
  if grep -q '^DEOXYS_SOURCE_FAIL' reports/0_breaking.md; then
    echo "❌ 事前生成記事にDEOXYS_SOURCE_FAILが含まれています（パイプライン停止）"
    log_step "deoxys" "rejected" "reports/0_breaking.md" "DEOXYS_SOURCE_FAIL（prebuilt）"
    archive_and_exit 1
  fi
  # ゴシップ専用: GOSSIP_SOURCE_FAILチェック
  if grep -q '^GOSSIP_SOURCE_FAIL' reports/0_breaking.md; then
    echo "❌ ゴシップ記事の一次ソース不足（GOSSIP_SOURCE_FAIL） → pipeline停止"
    log_step "deoxys" "rejected" "reports/0_breaking.md" "GOSSIP_SOURCE_FAIL（prebuilt）"
    archive_and_exit 1
  fi
  # ゴシップ専用: 本文内の憶測語チェック（prebuilt記事がGOSSIP_MODEで来た場合）
  if [[ "$GOSSIP_MODE" == "1" ]]; then
    echo "  → GOSSIP_MODE: ゴシップ記事の憶測語チェックを実施"
    _GOSSIP_SPECULATION=$(python3 - << 'GSPY'
import sys, re
try:
    text = open("reports/0_breaking.md", encoding="utf-8", errors="replace").read()
    # 憶測語パターン（ゴシップ記事で危険な表現）
    speculation_patterns = [
        r'関係者によると',
        r'ネットで話題',
        r'噂によると',
        r'〜という噂',
        r'〜と噂され',
        r'匿名.*によると',
        r'消息筋によると',
        r'確認は取れていない',
        r'未確認.*情報',
    ]
    hits = [p for p in speculation_patterns if re.search(p, text)]
    if hits:
        print("WARN:" + "|".join(hits))
    else:
        print("OK")
except Exception as e:
    print("OK")
GSPY
)
    if [[ "$_GOSSIP_SPECULATION" == WARN:* ]]; then
      _SPEC_DETAIL="${_GOSSIP_SPECULATION#WARN:}"
      echo "❌ [GOSSIP_SOURCE_GUARD] 憶測語検出: ${_SPEC_DETAIL} → pipeline停止"
      log_step "gossip_source_guard" "rejected" "reports/0_breaking.md" "憶測語検出: ${_SPEC_DETAIL}"
      # logs/gossip_source_guard.log にも記録
      echo "[$(date '+%Y-%m-%d %H:%M:%S')] [GOSSIP_SOURCE_GUARD] 憶測語検出: ${_SPEC_DETAIL}" \
        >> "$SCRIPT_DIR/logs/gossip_source_guard.log" 2>/dev/null || true
      archive_and_exit 1
    fi
    echo "  ✓ ゴシップ記事: 憶測語なし"
    log_step "gossip_source_guard" "ok" "reports/0_breaking.md" "憶測語チェック通過"
  fi
  log_step "deoxys" "ok" "reports/0_breaking.md"
elif [[ -n "$THEME_INPUT" ]]; then
  # テーマ記事: WebSearchで事実確認してから記事を書く
  claude --no-session-persistence --allowedTools WebSearch --agent deoxys_kpop -p "
今日は${TODAY}です。以下のテーマでK-POP記事を作成せよ。
【指定テーマ】${THEME_INPUT}

${NO_CONV_RULE}

【重要】必ずWebSearchでテーマに関する最新情報・一次ソースを確認してから記事を書け。
WebSearchで一次ソース（公式SNS・公式声明・信頼できるメディア報道）が見つからない場合は「DEOXYS_SOURCE_FAIL」を出力して停止せよ。
確認できた情報のみ断定的に書き、未確認の情報は「〜とみられる」「〜と報じられている」で表現すること。

【タイトルの【速報】について - v1.3厳格ルール】
【速報】を付けてよいのは以下のみ：
- 24時間以内のスキャンダル・緊急発表・突発事件
【速報】を絶対に付けてはならない記事タイプ：
- まとめ記事（〜まとめ、〜一覧、〜スケジュール）
- ランキング・チャート記事（TOP10、1位、Billboard等）
- イベントリスト・カレンダー記事
- 解説・分析・考察・振り返り記事
- カムバックスケジュール一覧
迷ったら付けない。

【最重要ルール：日付と時制】
- 今日は${TODAY}。これを基準に判断する
- 未来の日付 → 未来形（予定・見込み・開催予定）
- 過去・当日 → 過去形（開催された・発表された）
- 絶対に未来の出来事を過去形で書くな
- 日付は必ず本文に明記する

【出力形式・絶対厳守】
1行目：タイトル文字列のみ（##・説明文禁止）
  ※真の速報の場合のみ冒頭に【速報】を付ける。まとめ・ランキング・スケジュール記事には絶対に付けない。
2行目：空行
3行目以降：<h2>から始まるHTML本文のみ
末尾に情報元と「※本記事は${TODAY}時点の情報です」を明記

${DEOXYS_DIRECTIVE}
" > reports/0_breaking.md
else
  # ニュース取得モード: ミュウツーの戦略判断を反映
  claude --no-session-persistence --allowedTools WebSearch --agent deoxys_kpop -p "
今日は${TODAY}です。以下のテーマでK-POP記事を書け。

【編集長（ミュウツー）の指示】
テーマ: ${THEME_FROM_MEWTWO:-K-POPの最新ニュース}
速報扱い: ${IS_BREAKING:-判断して}
推奨カテゴリ: ${CATEGORY_HINT:-自動判断}

【★ネタ被り絶対禁止★】以下は直近3日間に既に投稿済みの記事です。
同じテーマ・同じ切り口・同じまとめ形式で書くことは絶対に禁止。
特に「カムバックスケジュールまとめ」等のラウンドアップ記事が既にある場合、類似まとめ記事��絶対に書くな。
編集長が指��したテーマで��っても、既出テーマと被る場合は切り口を大きく��えること。
${RECENT_POSTED}

【速報の判断基準 - v1.3厳格ルール】
速報扱いが「YES」の場合 → タイトル冒頭に【速報】を付ける
速報扱いが「NO」の場合 → タイトルに【速報】を付けない
「判断して」の場合 → 24時間以内の新情報・ゴシップ・緊急発表なら【速報】、それ以外は付けない
【速報】を絶対に付けてはならない記事タイプ（速報扱いがYESでも上書き禁止）：
- まとめ記事（〜まとめ、〜一覧、〜スケジュール）
- ランキング・チャート記事（TOP10、1位、Billboard等）
- イベントリスト・カレンダー記事
- 解説・分析・考察・振り返り記事
迷ったら付けない。

${NO_CONV_RULE}

【最重要ルール：日付と時制】
- 今日は${TODAY}。これを基準に判断する
- 未来の日付 → 未来形（予定・見込み・開催予定）
- 過去・当日 → 過去形（開催された・発表された）
- 絶対に未来の出来事を過去形で書くな
- 日付は必ず本文に明記する

【出力形式・絶対厳守】
1行目：タイトル文字列のみ（##・説明文禁止）
  ※真の速報の場合のみ冒頭に【速報】を付ける。まとめ・ランキング・スケジュール記事には絶対に付けない。
2行目：空行
3行目以降：<h2>から始まるHTML本文のみ
末尾に情報元と「※本記事は${TODAY}時点の情報です」を明記

${DEOXYS_DIRECTIVE}
" > reports/0_breaking.md
fi
sanitize_output reports/0_breaking.md

# 空出力なら1回リトライ（レートリミット・一時失敗対策）
if [[ ! -s reports/0_breaking.md ]]; then
  echo "  ⚠️ デオキシス空出力 → 30秒待機後リトライ..."
  sleep 30
  # テーマ入力があればテーマモードでリトライ
  if [[ -n "$THEME_INPUT" ]]; then
    claude --no-session-persistence --allowedTools WebSearch --agent deoxys_kpop -p "
今日は${TODAY}です。以下のテーマでK-POP記事を作成せよ。
【指定テーマ】${THEME_INPUT}
${NO_CONV_RULE}
【重要】必ずWebSearchでテーマに関する最新情報を確認してから記事を書け。
一次ソースが見つからない場合は「DEOXYS_SOURCE_FAIL」を出力して停止せよ。
【出力形式】1行目：タイトルのみ 2行目：空行 3行目以降：<h2>から始まるHTML
" > reports/0_breaking.md
  else
    claude --no-session-persistence --allowedTools WebSearch --agent deoxys_kpop -p "
今日は${TODAY}です。K-POPの最新ニュース1本を記事化せよ。
【ネタ被り禁止】${RECENT_POSTED}
${NO_CONV_RULE}
【出力形式】1行目：タイトルのみ 2行目：空行 3行目以降：<h2>から始まるHTML
末尾に情報元と「※本記事は${TODAY}時点の情報です」を明記
${DEOXYS_DIRECTIVE}
" > reports/0_breaking.md
  fi
  sanitize_output reports/0_breaking.md
  if [[ ! -s reports/0_breaking.md ]]; then
    echo "❌ デオキシス: リトライ後も空出力 → パイプライン停止"
    log_step "deoxys" "error" "reports/0_breaking.md" "空出力（リトライ失敗）"
    archive_and_exit 1
  fi
  echo "  ✅ デオキシス リトライ成功"
fi

check_output reports/0_breaking.md "デオキシス"
# [ガード] デオキシスがSOURCE_FAILを出力した場合は即停止
if grep -q '^DEOXYS_SOURCE_FAIL' reports/0_breaking.md; then
  echo "❌ デオキシスが一次ソース未確認で停止しました"
  head -5 reports/0_breaking.md
  log_step "deoxys" "rejected" "reports/0_breaking.md" "DEOXYS_SOURCE_FAIL"
  archive_and_exit 1
fi
log_step "deoxys" "ok" "reports/0_breaking.md"

echo "=== [2] メタモン: CTRリライト ==="
# [ガード] 0_breaking.mdが空またはreportsリンク切れの場合は即停止
_BREAKING_CONTENT=$(cat reports/0_breaking.md 2>/dev/null || echo "")
if [[ -z "$_BREAKING_CONTENT" ]] || [[ ${#_BREAKING_CONTENT} -lt 100 ]]; then
  echo "❌ [メタモン前ガード] reports/0_breaking.md が空または取得不可 (${#_BREAKING_CONTENT}文字) → パイプライン停止"
  log_step "pre_metamon_guard" "error" "reports/0_breaking.md" "0_breaking.md空: reportsリンク切れの疑い"
  archive_and_exit 1
fi
# [前処理] デオキシスのメタ説明行（「記事を生成します」等）を除去して本文のみを渡す
_BREAKING_CONTENT=$(echo "$_BREAKING_CONTENT" | grep -vE '(一次ソース情報が確認できました|記事を生成します|情報が確認できました。記事を|以下に記事を生成|記事を作成します|記事を出力します)' || echo "$_BREAKING_CONTENT")
# [ガード] デオキシスがチャットUI向け定型文を返した場合は即停止
if echo "$_BREAKING_CONTENT" | grep -qE '(記事の元情報.*貼り付け|このチャットに貼り付け|ドラフト文章.*このチャット|チャットに貼り付けてください|記事の元原稿が提供されていません|リライト対象の記事本文を貼り付け|元原稿.*提供されていません)'; then
  echo "❌ [メタモン前ガード] デオキシスがチャットUI向け定型文を出力しました → パイプライン停止"
  echo "  内容冒頭: $(head -c 200 reports/0_breaking.md)"
  log_step "pre_metamon_guard" "error" "reports/0_breaking.md" "デオキシスがチャット定型文を出力（入力コンテキスト誤認識）"
  archive_and_exit 1
fi
# [重要] _BREAKING_CONTENTをシェル引数展開のトラブルを避けるためファイル経由で渡す
_METAMON_PROMPT_FILE=$(mktemp "/tmp/metamon_prompt_${RUN_ID}_XXXXXX.txt")
cat > "$_METAMON_PROMPT_FILE" << METAMON_PROMPT_EOF
あなたはK-POPニュース専門ライター兼CTR改善担当です。

以下の記事を、SEOとCTRの両方が強い完成記事にしてください。

${NO_CONV_RULE}

【絶対ルール】
・修正内容や理由は一切書かない
・『修正箇所』『修正サマリー』『理由』『チェック項目』などの文言を一切出力しない
・説明文・前置き・後書き・表・箇条書き禁止
・質問禁止
・完成記事本文だけを書くこと

【最重要ルール：日付と時制】
- 今日は${TODAY}。未来は未来形・過去は過去形
- 日付は必ず本文に明記すること

【CTRタイトル生成ルール】
以下の3パターンで内部タイトル案を作り、最もCTRが高い1案を採用して出力すること。
A【SEO型】: 「アーティスト名＋具体イベント名＋日付 or 数字」でロングテール検索を狙う
B【感情フック型】: 「ついに／衝撃／まさか／神／完全復帰」などの感情語＋固有情報で読者の感情を動かす
C【異常性・ギャップ型】: 予想外・矛盾・驚きの数字・裏事情など「え、なんで？」を誘う表現を使う

採用ルール:
・固有情報（アーティスト名・数字・日付・イベント名）は必ず保持
・24〜38文字を目安にする
・弱い一般表現禁止（まとめ／情報／解説／について／とは）
・事実にない情報は追加しない
・冒頭3行は必ず「結論 → 注目理由 → 読む価値」で構成する

【TITLE_LOG出力ルール（必須）】
記事本文の最終行の後に、必ず以下の形式で1行だけ出力すること:
TITLE_LOG: A=「...」 B=「...」 C=「...」 → 採用=X（理由1行）

【精度ルール】
- 実在しない情報を増やさない
- 不確実な内容は断定しない
- 記事末尾に情報元を明記する
- 記事末尾に「※本記事は${TODAY}時点の情報です」を入れる

【記事タイプ付与（必須）】
HTML本文の最初の<p>または<h2>の直前に、以下を判定して1行挿入すること：
・タイトルに「速報」「決定」「判明」「解禁」「確定」「発表」が含まれる → <p class="article-type speed">【速報】</p>
・タイトルに「視聴方法」「チケット」「アクセス」「持ち物」「どこで」が含まれる → <p class="article-type guide">【ガイド】</p>
・それ以外 → <p class="article-type explanation">【解説】</p>
・タイトルにすでに【速報】等が明示されている場合は重複付与しない

【回遊導線（末尾に必ず追加）】
記事末尾に以下を追加すること。記事対象アーティストがBTS/BIGBANG/BLACKPINK/StrayKids/NCT/TWICE/NewJeans/XG/IVE/aespaの場合、該当ハブページへのリンクを含めること：
<div class="related-articles"><h3>関連記事もチェック</h3><ul>
<li>▶ <a href="https://www.kpopjournal.tokyo/【該当アーティスト名】-hub/">【アーティスト名】最新情報まとめ</a></li>
</ul></div>
（ハブURLの対応: bts-hub / bigbang-hub / blackpink-hub / straykids-hub / nct-hub / twice-hub / newjeans-hub / xg-hub / ive-hub / aespa-hub）

【出力形式】
1行目：タイトルのみ
2行目以降：HTML本文のみ

【重要】
最終完成記事だけを出力せよ

${METAMON_DIRECTIVE}

---
【リライト対象記事・全文（以下をそのままリライトせよ）】
METAMON_PROMPT_EOF
# 記事本文をファイルに追記（変数展開の問題を回避）
printf '%s\n' "${_BREAKING_CONTENT}" >> "$_METAMON_PROMPT_FILE"
_METAMON_PROMPT_SZ=$(wc -c < "$_METAMON_PROMPT_FILE" 2>/dev/null || echo 0)
echo "  [metamon] プロンプトファイル: $_METAMON_PROMPT_SZ bytes (記事: ${#_BREAKING_CONTENT} chars)"
claude --no-session-persistence --agent metamon_kpop -p < "$_METAMON_PROMPT_FILE" > reports/1_rewrite.md
rm -f "$_METAMON_PROMPT_FILE"
sanitize_output reports/1_rewrite.md
# [sanitize後ガード] sanitize_outputが定型文を除去した結果ファイルが空/極小になった場合
_METAMON_SZ_AFTER=$(wc -c < reports/1_rewrite.md 2>/dev/null || echo 0)
if [[ "$_METAMON_SZ_AFTER" -lt 500 ]]; then
  echo "❌ [メタモン後ガード] sanitize後ファイルが極小(${_METAMON_SZ_AFTER}bytes) → 定型文除去後に実記事なし → パイプライン停止"
  log_step "metamon" "error" "reports/1_rewrite.md" "sanitize後極小: ${_METAMON_SZ_AFTER}bytes（定型文のみだった疑い）"
  archive_and_exit 1
fi
# TITLE_LOG 抽出（メタモンが出力した内部ログ行を記録してから本文から除去）
_TITLE_LOG=$(grep '^TITLE_LOG:' reports/1_rewrite.md | head -1)
if [[ -n "$_TITLE_LOG" ]]; then
  echo "  [metamon] $_TITLE_LOG"
  grep -v '^TITLE_LOG:' reports/1_rewrite.md > /tmp/1_rewrite_clean_${RUN_ID}.md && mv /tmp/1_rewrite_clean_${RUN_ID}.md reports/1_rewrite.md
fi
check_output reports/1_rewrite.md "メタモン"
# [追加ガード] メタモン出力がチャット定型文のみの場合（check_output通過後も念のため確認）
# ※ sanitize_outputが除去しきれなかったHTMLタグ内定型文等に対するフォールバック
if grep -qE '(記事の元情報.*貼り付け|このチャットに貼り付け|ドラフト文章.*貼り付け|アーティスト名.*イベント詳細.*日付.*貼り付け|記事の元情報が貼り付けられていません|チェック対象の記事本文を貼り付け|貼り付けられていません|タイトルを入力してください|評価対象がありません|入力記事が見当たりません|記事の入力が見当たりません)' reports/1_rewrite.md; then
  echo "❌ [メタモン後ガード] メタモンがチャットUI向け定型文を出力しました → パイプライン停止"
  echo "  内容冒頭: $(head -c 200 reports/1_rewrite.md)"
  log_step "metamon" "error" "reports/1_rewrite.md" "メタモンがチャット定型文を出力（入力コンテキスト誤認識）"
  archive_and_exit 1
fi
log_step "metamon" "ok" "reports/1_rewrite.md"

echo "=== [2.5] イーブイ: タイトル評価・確定 ==="
# 1行目タイトル抽出: 空行スキップ・<h1>タグがある場合はタグを除去して中身のみ取得
TITLE_A=$(python3 -c "
import re, sys
lines = open('reports/1_rewrite.md', encoding='utf-8', errors='replace').read().splitlines()
for l in lines:
    l = l.strip()
    if not l:
        continue
    # <h1>...</h1> 形式のタイトルを除去してテキストのみ取得（閉じタグなし・行末なしも対応）
    m = re.match(r'^<h1[^>]*>(.*?)(?:</h1>)?$', l, re.IGNORECASE)
    if m:
        title = m.group(1).strip()
        if title:
            print(title)
            break
    # h2以下・div・p等のコンテンツタグはスキップ（h1以外のブロック要素）
    if re.match(r'^<(h[2-6]|p|div|ul|ol|li|table|section|article|header|footer|nav|aside|figure|blockquote|pre|code)[^>]*>', l, re.IGNORECASE):
        continue
    # HTMLコメントはスキップ
    if l.startswith('<!--'):
        continue
    # テキスト行（または未知のタグ行）はタイトル候補として採用
    # 未知タグの場合はタグを除去してテキストを取得
    clean = re.sub(r'<[^>]+>', '', l).strip()
    if clean:
        print(clean)
        break
" 2>/dev/null || head -n 1 reports/1_rewrite.md)
# フォールバック: TITLE_LOGの採用タイトルから取得（本文先頭から取れなかった場合）
if [[ -z "$TITLE_A" ]] && [[ -n "$_TITLE_LOG" ]]; then
  _ADOPTED=$(echo "$_TITLE_LOG" | sed 's/.*採用=\([ABC]\).*/\1/')
  case "$_ADOPTED" in
    A) TITLE_A=$(echo "$_TITLE_LOG" | grep -oP 'A=「\K[^」]+') ;;
    B) TITLE_A=$(echo "$_TITLE_LOG" | grep -oP 'B=「\K[^」]+') ;;
    C) TITLE_A=$(echo "$_TITLE_LOG" | grep -oP 'C=「\K[^」]+') ;;
  esac
fi
echo "  メタモン採用タイトル: $TITLE_A"

# 勝ちパターン参照（学習データがあれば）
WIN_PROMPT=$(python3 "$SCRIPT_DIR/lib/title_learner.py" prompt 2>/dev/null || echo "")

# イーブイ: 採用タイトルを評価し、必要なら改善して1案に確定
TITLE_B=$(claude --no-session-persistence -p "
あなたはK-POPメディアのCTR改善専門エディターです。

メタモンが選んだ以下のタイトルを評価し、最終タイトルを1つだけ出力してください。

【メタモン採用タイトル】
$TITLE_A

【評価基準（5項目）】
1. 固有情報（アーティスト名・数字・日付・イベント名）が含まれているか
2. 感情語または異常性・ギャップ表現が入っているか
3. 24〜38文字の範囲内か
4. 弱い表現（まとめ／解説／情報／について／とは）が使われていないか
5. 事実逸脱・釣り過剰になっていないか

【判断ルール】
・5項目すべて合格 → そのままタイトルを出力
・1〜2項目に問題 → 修正して改善版を出力
・3項目以上問題 → 最初からより良いタイトルを生成して出力

【絶対禁止】
・タイトル文字列以外の出力（説明・前置き・評価コメント）
・タイトルAにない事実を追加（事実逸脱禁止）
・釣り表現（「閲覧注意」「ガチでやばい」等の過剰煽り）

${WIN_PROMPT}

${EEVEE_DIRECTIVE}
" 2>/dev/null | grep -v '^$' | head -1)

# [ガード] TITLE_Aが空の場合はパイプライン停止（メタモンタイトル未取得）
if [[ -z "$TITLE_A" ]]; then
  echo "❌ [イーブイ前ガード] メタモン採用タイトルが空 → パイプライン停止"
  log_step "eevee" "error" "reports/1_rewrite.md" "TITLE_A空: メタモンタイトル取得失敗"
  archive_and_exit 1
fi
# [ガード] TITLE_Aが定型文の場合はパイプライン停止（メタモンがコンテキストを誤認識）
if echo "$TITLE_A" | grep -qE '(記事の元情報.*貼り付け|このチャットに貼り付け|ドラフト文章.*貼り付け|アーティスト名.*イベント詳細.*日付.*貼り付け|記事の元情報が貼り付けられていません|タイトルを入力してください|評価対象がありません)'; then
  echo "❌ [イーブイ前ガード] TITLE_Aが定型文 → メタモンがコンテキストを誤認識 → パイプライン停止"
  echo "  TITLE_A冒頭: $(echo "$TITLE_A" | head -c 100)"
  log_step "eevee" "error" "reports/1_rewrite.md" "TITLE_Aが定型文: メタモン誤認識"
  archive_and_exit 1
fi
# フォールバック: タイトルBが空ならタイトルAをそのまま使用
if [[ -z "$TITLE_B" ]]; then
  TITLE_B="$TITLE_A"
  echo "  ⚠️ イーブイ評価失敗 → メタモンタイトルで確定"
fi
# [ガード] タイトルBに定型文が含まれている場合はフォールバック
if echo "$TITLE_B" | grep -qE 'タイトルを入力してください|評価対象がありません|このチャットに貼り付け|記事の元情報|メタモン採用タイトルが空白|空白のため|入力してください'; then
  echo "  ⚠️ [イーブイ後ガード] イーブイが定型文を出力 → TITLE_Aで確定"
  TITLE_B="$TITLE_A"
fi
echo "  イーブイ確定タイトル: $TITLE_B"

# タイトルをJSONで保存（後続ステップで使用）
python3 -c "
import json, sys
data = {'title_a': sys.argv[1], 'title_b': sys.argv[2]}
with open('reports/title_ab.json', 'w') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
" "$TITLE_A" "$TITLE_B"
echo "  ✓ reports/title_ab.json 保存完了"
log_step "eevee" "ok" "reports/title_ab.json" "title confirmed"

echo "=== [3] ジラーチ: ファクトチェック ==="

# [事前ガード] ジラーチへの入力(1_rewrite.md)が定型文・極小でないか最終確認
_JIRACHI_INPUT_SZ=$(wc -c < reports/1_rewrite.md 2>/dev/null || echo 0)
if [[ "$_JIRACHI_INPUT_SZ" -lt 500 ]]; then
  echo "❌ [ジラーチ前ガード] 1_rewrite.mdが極小(${_JIRACHI_INPUT_SZ}bytes) → パイプライン停止"
  log_step "jirachi" "error" "reports/1_rewrite.md" "入力極小: ${_JIRACHI_INPUT_SZ}bytes"
  archive_and_exit 1
fi
if grep -qE '記事の元情報.*貼り付け|このチャットに貼り付け|ドラフト文章.*貼り付け|記事の元情報が貼り付けられていません|タイトルを入力してください' reports/1_rewrite.md; then
  echo "❌ [ジラーチ前ガード] 1_rewrite.mdに定型文を検出 → パイプライン停止"
  echo "  内容冒頭: $(head -c 150 reports/1_rewrite.md)"
  log_step "jirachi" "error" "reports/1_rewrite.md" "入力に定型文検出"
  archive_and_exit 1
fi

# カテゴリ111（視聴方法・配信ガイド）判定
_JIRACHI_TITLE=$(head -1 reports/1_rewrite.md | sed 's/^[#[:space:]]*//')
_IS_STREAMING_GUIDE_J=$(python3 -c "
import sys
title = sys.argv[1].lower()
keywords = ['視聴方法','どこで見れる','無料視聴','配信サービス','配信比較','サブスク','abema','netflix','hulu','prime video','ライブ配信','見る方法','見る全方法','視聴ガイド']
print('yes' if any(k in title for k in keywords) else 'no')
" "$_JIRACHI_TITLE" 2>/dev/null)

if [[ "$_IS_STREAMING_GUIDE_J" == "yes" ]]; then
  echo "  ⚠️  視聴導線記事（カテゴリ111相当）検出 → 強化ファクトチェックモード"
  _STREAMING_EXTRA_J="

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【視聴導線記事 専用ファクトチェックルール（最優先・必須）】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
■ 料金チェック
- ABEMAプレミアム正しい料金: 月1,180円（2026年4月改定済み）。960円があれば即修正
- Leminoプレミアム正しい料金: Web登録月1,540円（2026年2月改定済み）。990円があれば即修正
- 料金記載箇所には「最新料金は公式サイトをご確認ください」を必ず同段落内に追加
■ 配信状況チェック
- 配信状況は「確認済み」「未確認」「過去実績あり」の3分類で表現
- 「過去実績あり」と「2026年も配信決定」を混同している箇所を全て修正
- 未確認情報に「配信予定です」「視聴できます」が付いていたら「要確認」に修正
■ プラットフォーム正確性
- IVEはKakao系（Weverse非対応）。IVE記事のWeverse導線は公式SNSに置き換えよ
- YouTubeは「無料公開動画あり」と表現（「全て無料視聴可能」は禁止）
■ 出力末尾への監査ログ追加（必須）
本文の最後の行の後に以下を1行追加せよ：
FACTCHECK_LOG: price=OK/NG stream=OK/NG schedule=OK/NG status=OK/NG source_count=N
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
else
  _STREAMING_EXTRA_J=""
fi

# ジラーチプロンプトをファイル経由で渡す（インライン $(cat) によるプロンプト破損を防ぐ）
_JIRACHI_PROMPT_FILE=$(mktemp "/tmp/jirachi_prompt_${RUN_ID}_XXXXXX.txt")
cat > "$_JIRACHI_PROMPT_FILE" <<EOF
今日は${TODAY}です。

【前提条件】
あなたにはWebSearch・Read・Edit等の外部ツールは一切与えられていない。
外部ツールが使えないことは正常な状態であり、言及する必要はない。
手元の記事の内部整合性のみをチェックせよ。

以下の記事の時制と内部整合性をチェックし、修正済みの完成記事を出力せよ。

【チェック項目（内部整合性のみ）】
- 日付と時制の整合性（${TODAY}基準・最重要）
- 未来の出来事が過去形になっていないか
- 同じ記事内で矛盾する記述がないか
- 不自然な誇張（世界初・史上初など）
- 情報元表記があるか
${_STREAMING_EXTRA_J}
【ルール】
- 修正が必要な箇所のみ修正。構造は変えない
- 検証できない情報はそのまま残す（削除・拒否しない）
- 必ず完成記事を出力する。出力しないことは許されない

【絶対禁止】
- 修正箇所・修正理由・チェック結果の説明
- 「確認できない」「検証できない」「範囲外」等の辞退
- 質問・会話文・前置き・後書き
- 空の出力

【出力形式】
1行目：タイトルのみ
2行目：空行
3行目以降：HTML本文のみ
視聴導線記事の場合のみ、本文の最後の行の後にFACTCHECK_LOGを追加せよ（本文内には含めない）

---
【ファクトチェック対象記事・全文（以下を確認せよ）】
EOF
cat reports/1_rewrite.md >> "$_JIRACHI_PROMPT_FILE"
claude --no-session-persistence --agent jirachi_kpop -p < "$_JIRACHI_PROMPT_FILE" > reports/2_checked.md
rm -f "$_JIRACHI_PROMPT_FILE"
sanitize_output reports/2_checked.md
# FACTCHECK_LOG行をログに保存して本文から除去
_FACTCHECK_LOG_J=$(grep '^FACTCHECK_LOG:' reports/2_checked.md | head -1)
if [[ -n "$_FACTCHECK_LOG_J" ]]; then
  echo "  [jirachi] $_FACTCHECK_LOG_J"
  echo "$_FACTCHECK_LOG_J" >> "$SCRIPT_DIR/logs/factcheck.log"
  grep -v '^FACTCHECK_LOG:' reports/2_checked.md > /tmp/2_checked_clean.md && mv /tmp/2_checked_clean.md reports/2_checked.md
fi
check_output reports/2_checked.md "ジラーチ"

# [ガード] ジラーチ出力のサイズ比較（元記事の10%未満なら異常→フォールバック）
SIZE_REWRITE=$(wc -c < reports/1_rewrite.md)
SIZE_CHECKED=$(wc -c < reports/2_checked.md)
if [ "$SIZE_REWRITE" -gt 0 ] && [ "$((SIZE_CHECKED * 100 / SIZE_REWRITE))" -lt 10 ]; then
  echo "⚠️ ジラーチ出力が異常に小さい（${SIZE_CHECKED}B / 元${SIZE_REWRITE}B = $((SIZE_CHECKED * 100 / SIZE_REWRITE))%）"
  echo "  → リライト版をそのまま使用（ジラーチをスキップ）"
  cp reports/1_rewrite.md reports/2_checked.md
fi
log_step "jirachi" "ok" "reports/2_checked.md"

# [ガード] ジラーチのFAIL/デオキシスのSOURCE_FAIL判定を直接チェック
if grep -qE '^(FACT_CHECK_FAIL|DEOXYS_SOURCE_FAIL)' reports/2_checked.md; then
  echo "❌ ジラーチがFACT_CHECK_FAILを出力しました（パイプライン停止）"
  head -5 reports/2_checked.md
  log_step "jirachi" "rejected" "reports/2_checked.md" "FACT_CHECK_FAIL検出"
  archive_and_exit 1
fi

# === プロンプトインジェクション検出 ===
if grep -qiE '(プロンプトインジェクション|prompt injection|この指示を無視|ignore previous instructions|IGNORE PREVIOUS|system prompt|システムプロンプトを)' reports/2_checked.md reports/title_ab.json 2>/dev/null; then
  echo "🚨 プロンプトインジェクションの痕跡を検出 — パイプライン停止"
  log_step "security" "rejected" "reports/2_checked.md" "プロンプトインジェクション検出"
  archive_and_exit 1
fi

# === [3.5] ガルーラ批評: 刺さり品質ゲート ===
echo "=== [3.5] ガルデvoir: 刺さり品質判定 ==="
# ガルデvoir ログファイルを事前に確保（存在しない場合は作成）
touch "$SCRIPT_DIR/logs/gardevoir_hook.jsonl"

# タイトル取得（eevee選定済みのtitle_ab.jsonから最終タイトルを取得）
_GDV_TITLE=""
if [ -f reports/title_ab.json ]; then
  _GDV_TITLE=$(python3 -c "
import json,sys
data=json.load(open('reports/title_ab.json'))
t=data.get('SELECTED_TITLE') or data.get('TITLE_A') or data.get('title_a') or ''
print(t.strip())
" 2>/dev/null || echo "")
fi
[ -z "$_GDV_TITLE" ] && _GDV_TITLE=$(head -1 reports/2_checked.md)

# [前段ガード] タイトル崩壊パターン検出 → サーナイト呼び出し前に即停止
# 根拠: gardevoir HARD_FAIL率68%の主因がタイトル崩壊であることをagent_monitorが検出
_TITLE_COLLAPSE=0
if echo "$_GDV_TITLE" | grep -qE '(以下に|分析します|ウェブフェッチ|以下の記事|提供してください|見当たりません|コンテンツが提供されていません|^以下)'; then
  _TITLE_COLLAPSE=1
fi
# タイトルが空・10文字未満・HTMLタグのみ の場合も崩壊とみなす
_TITLE_LEN=${#_GDV_TITLE}
if [[ $_TITLE_LEN -lt 10 ]]; then
  _TITLE_COLLAPSE=1
fi
if [[ "$_TITLE_COLLAPSE" == "1" ]]; then
  echo "❌ [前段ガード] タイトル崩壊を検出しました → パイプライン停止"
  echo "  検出タイトル: ${_GDV_TITLE}"
  echo "  原因: デオキシス/メタモンがメタコメントをタイトルとして出力した可能性"
  log_step "gardevoir_hook_critic" "ERROR" "reports/2_checked.md" "前段ガード: タイトル崩壊検出 title=${_GDV_TITLE}"
  python3 "$SCRIPT_DIR/lib/kpi_logger.py" log_error "{\"error_type\":\"title_collapse\",\"step\":\"pre_gardevoir_guard\",\"title\":\"${_GDV_TITLE}\",\"message\":\"タイトル崩壊パターン検出: deoxys/metamonのメタコメント混入疑い\",\"recoverable\":false}" 2>/dev/null || true
  bash "$SCRIPT_DIR/kpop_notify.sh" error "速報" "タイトル崩壊検出で停止 (RUN: $RUN_ID) title=${_GDV_TITLE}" 2>/dev/null || true
  archive_and_exit 1
fi

# 冒頭500文字・H2一覧・メタディスクリプション抽出
_GDV_HOOK=$(python3 -c "
import re
text=open('reports/2_checked.md').read()
body=re.sub(r'^.*\n','',text,count=1)  # タイトル行除去
body=re.sub(r'<[^>]+>','',body)         # タグ除去
print(body[:500])
" 2>/dev/null || head -20 reports/2_checked.md)

_GDV_H2=$(grep -oP '(?<=<h2>)[^<]+' reports/2_checked.md 2>/dev/null | head -10 | sed 's/^/- /' || grep -E '^## ' reports/2_checked.md | head -10)
[ -z "$_GDV_H2" ] && _GDV_H2="（H2なし）"

_GDV_META=$(python3 -c "
import re
text=open('reports/2_checked.md').read()
m=re.search(r'description[\":\s]+([^\n\"]{20,140})',text,re.I)
if m: print(m.group(1).strip())
" 2>/dev/null || echo "")

# カテゴリ情報（CATEGORY_HINTがあれば使用、なければ不明）
_GDV_CATEGORY="${CATEGORY_HINT:-不明}"

_GDV_RETRY=0
_GDV_VERDICT=""

while true; do
  echo "  ガルデvoir採点中... (試行$((${_GDV_RETRY}+1)))"
  claude --no-session-persistence --agent gardevoir_hook_critic -p "
以下の記事を採点せよ。出力は SCORE: から始まる固定フォーマットのみとする。会話・説明・質問を出力してはならない。
【必須】出力の最後に必ず「VERDICT: PASS」「VERDICT: SOFT_RETRY」「VERDICT: HARD_FAIL」のいずれか1行を含めること。VERDICT行を省略することは絶対に禁止。

${GARDEVOIR_DIRECTIVE}

記事カテゴリ: ${_GDV_CATEGORY}
想定ターゲット: KPOPファン・韓国カルチャー好き・旅行/美容/ファッション興味層
タイトル: ${_GDV_TITLE}
メタディスクリプション: ${_GDV_META:-（なし）}

【冒頭300〜500文字】
${_GDV_HOOK}

【H2一覧】
${_GDV_H2}

【CTA】
（記事末尾のCTAを参照してください）

【記事全文】
$(cat reports/2_checked.md)
" > reports/3_gardevoir.md 2>/dev/null
  sanitize_output reports/3_gardevoir.md

  _GDV_VERDICT=$(grep -oP '^\s*VERDICT:\s*\K(PASS|SOFT_RETRY|HARD_FAIL)' reports/3_gardevoir.md | head -1)
  # SCORE パース: 複数フォーマットに対応
  #   パターン1: "SCORE: 81"           (同一行にスコアあり)
  #   パターン2: "SCORE: 81/100"       (同一行に /100 付き)
  #   パターン3: "TOTAL: 81/100"       (TOTAL行)
  #   パターン4: "SCORE:\n総合: 81/100"  (直後行)
  #   パターン5: "SCORE:\n- 総合: 81/100" (直後行・箇条書き)
  #   パターン6: "- 総合スコア: 87/100"  (任意行・総合スコア)
  #   パターン7: "総合: 87/100"         (任意行・総合のみ)
  _GDV_SCORE=$(python3 -c "
import re, sys
text = open('reports/3_gardevoir.md', errors='replace').read()
# パターン1/2: SCORE: 81 または SCORE: 81/100 (同一行)
m = re.search(r'^SCORE:\s*(\d+)', text, re.MULTILINE)
if m:
    print(m.group(1)); sys.exit(0)
# パターン3: TOTAL: 81/100 (同一行)
m = re.search(r'^TOTAL[：:]\s*(\d+)', text, re.MULTILINE)
if m:
    print(m.group(1)); sys.exit(0)
# パターン4/5: SCORE:行の後（距離制限なし）に 総合: or - 総合: or 合計: が来るケース
m = re.search(r'^SCORE:\s*\n(?:.*\n)*?[-\s]*(?:総合|合計)[：:]\s*(\d+)', text, re.MULTILINE)
if m:
    print(m.group(1)); sys.exit(0)
# パターン6: 任意行の「総合スコア: 87/100」
m = re.search(r'総合スコア[：:]\s*(\d+)', text)
if m:
    print(m.group(1)); sys.exit(0)
# パターン7: 任意行の「総合: 87/100」(総合スコアとは別語)
m = re.search(r'総合[：:]\s*(\d+)', text)
if m:
    print(m.group(1)); sys.exit(0)
# パターン8: 任意行の「合計: 87/100」(合計キーワード)
m = re.search(r'合計[：:]\s*(\d+)', text)
if m:
    print(m.group(1)); sys.exit(0)
# パターン9: 任意行の「総合点: 81/100」(総合点キーワード)
m = re.search(r'総合点[：:]\s*(\d+)', text)
if m:
    print(m.group(1)); sys.exit(0)
# パターン10a: テーブルセル形式 | 合計 | 81 | or | 合計 | 81/100 |
m = re.search(r'\|\s*(?:合計|総合|SCORE|スコア)\s*\|\s*(\d+)', text)
if m:
    print(m.group(1)); sys.exit(0)
# パターン10b: フォールバック — テキスト中の NN/100 形式を拾う（最後の手段）
m = re.search(r'(?<!\d)([6-9]\d|100)/100\b', text)
if m:
    print(m.group(1)); sys.exit(0)
# パターン11: NN/90 形式（総合スコアが/90の場合、100点換算に変換）
m = re.search(r'(?<!\d)(\d+)/90\b', text)
if m:
    raw = int(m.group(1))
    print(min(100, int(round(raw * 100 / 90)))); sys.exit(0)
# パターン12: SCORE:行後の箇条書き個別スコアから平均を計算（最終フォールバック）
scores = re.findall(r'[-\s]*[^：:\n]+[：:]\s*(\d+)/\d+', text)
if len(scores) >= 3:
    nums = [int(s) for s in scores[:8]]
    avg = int(round(sum(nums) / len(nums)))
    print(avg); sys.exit(0)
print('')
" 2>/dev/null || echo "")
  _GDV_MUST_FIX=$(awk '/^MUST_FIX:/,/^[A-Z_]+:/' reports/3_gardevoir.md | grep -v '^[A-Z_]*:' | head -3 | tr '\n' ' ')

  # VERDICT フォールバック: VERDICT行が省略されているがスコアが取れた場合はスコアから推定
  if [[ -z "${_GDV_VERDICT}" ]] && [[ -n "${_GDV_SCORE}" ]]; then
    if [[ "${_GDV_SCORE}" -ge 80 ]]; then
      _GDV_VERDICT="PASS"
      echo "  ℹ️ [gardevoir] VERDICT行なし → score=${_GDV_SCORE} からPASSに推定"
    elif [[ "${_GDV_SCORE}" -ge 65 ]]; then
      _GDV_VERDICT="SOFT_RETRY"
      echo "  ℹ️ [gardevoir] VERDICT行なし → score=${_GDV_SCORE} からSOFT_RETRYに推定"
    else
      _GDV_VERDICT="HARD_FAIL"
      echo "  ℹ️ [gardevoir] VERDICT行なし → score=${_GDV_SCORE} からHARD_FAILに推定"
    fi
  fi

  log_step "gardevoir_hook_critic" "${_GDV_VERDICT:-ERROR}" "reports/3_gardevoir.md" "score=${_GDV_SCORE:-?} retry=${_GDV_RETRY} must_fix=${_GDV_MUST_FIX}"
  python3 -c "
import json, sys
print(json.dumps({
  'ts':       '$(date -u +%Y-%m-%dT%H:%M:%SZ)',
  'run_id':   '${RUN_ID:-unknown}',
  'pipeline': 'breaking',
  'agent':    'gardevoir_hook_critic',
  'score':    int('${_GDV_SCORE:-0}' or 0),
  'verdict':  '${_GDV_VERDICT:-ERROR}',
  'retry':    int('${_GDV_RETRY:-0}' or 0),
  'must_fix': '${_GDV_MUST_FIX}',
  'title':    sys.argv[1],
  'category': sys.argv[2],
}, ensure_ascii=False))" "${_GDV_TITLE:-}" "${_GDV_CATEGORY:-}" >> "$SCRIPT_DIR/logs/gardevoir_hook.jsonl"

  if [ "${_GDV_VERDICT}" = "PASS" ]; then
    echo "✅ ガルデvoir PASS (score=${_GDV_SCORE})"
    break
  elif [ "${_GDV_VERDICT}" = "SOFT_RETRY" ] && [ "${_GDV_RETRY}" -lt 2 ]; then
    _GDV_RETRY=$((_GDV_RETRY+1))
    echo "⚠️ ガルデvoir SOFT_RETRY (score=${_GDV_SCORE}, 試行${_GDV_RETRY}/2) — メタモン・デオキシス差し戻し"
    # タイトル再生成（メタモン）— ファイル経由でプロンプト渡し（シェル展開でのHTMLエスケープ破損を防ぐ）
    _GDV_META_RETRY_PROMPT=$(mktemp "/tmp/gdv_meta_retry_${RUN_ID}_XXXXXX.txt")
    cat > "$_GDV_META_RETRY_PROMPT" <<EOF
以下の記事のタイトルを再生成せよ。
【改善要求】
${_GDV_MUST_FIX}
【現タイトル】${_GDV_TITLE}
【記事本文（以下をそのまま参照せよ）】
EOF
    cat reports/2_checked.md >> "$_GDV_META_RETRY_PROMPT"
    claude --no-session-persistence --agent metamon_kpop -p < "$_GDV_META_RETRY_PROMPT" > /tmp/gardevoir_metamon_retry.md 2>/dev/null
    rm -f "$_GDV_META_RETRY_PROMPT"
    _NEW_TITLE=$(head -1 /tmp/gardevoir_metamon_retry.md | sed 's/^[#[:space:]]*//')
    [ -n "$_NEW_TITLE" ] && _GDV_TITLE="$_NEW_TITLE"
    # 冒頭再生成（デオキシス的リライト — 2_checked.mdの冒頭を差し替え）— ファイル経由
    _GDV_DEO_RETRY_PROMPT=$(mktemp "/tmp/gdv_deo_retry_${RUN_ID}_XXXXXX.txt")
    cat > "$_GDV_DEO_RETRY_PROMPT" <<EOF
以下の記事の冒頭（最初の300〜500文字）を書き直せ。タイトル行・H2・CTAは変えない。
【改善要求】
${_GDV_MUST_FIX}
【記事全文（以下をそのまま参照せよ）】
EOF
    cat reports/2_checked.md >> "$_GDV_DEO_RETRY_PROMPT"
    claude --no-session-persistence --agent deoxys_kpop -p < "$_GDV_DEO_RETRY_PROMPT" > /tmp/gardevoir_deoxys_retry.md 2>/dev/null
    rm -f "$_GDV_DEO_RETRY_PROMPT"
    [ -s /tmp/gardevoir_deoxys_retry.md ] && cp /tmp/gardevoir_deoxys_retry.md reports/2_checked.md
    _GDV_HOOK=$(python3 -c "
import re
text=open('reports/2_checked.md').read()
body=re.sub(r'^.*\n','',text,count=1)
body=re.sub(r'<[^>]+>','',body)
print(body[:500])
" 2>/dev/null || head -20 reports/2_checked.md)
  else
    # HARD_FAIL（または SOFT_RETRY 2回超過）
    echo "❌ ガルデvoir HARD_FAIL (score=${_GDV_SCORE}, retry=${_GDV_RETRY}) — 刺さらないため公開停止"
    log_step "gardevoir_hook_critic" "hard_fail" "reports/3_gardevoir.md" "公開停止 score=${_GDV_SCORE}"
    if [[ -z "${_GDV_SCORE}" ]] || [[ "${_GDV_SCORE}" == "0" ]]; then
      echo "🚨 GARDEVOIR_HARD_FAIL"
      echo "run_id=${RUN_ID:-unknown}"
      echo "title=${_GDV_TITLE}"
      echo "category=${_GDV_CATEGORY}"
      echo "reason=score=${_GDV_SCORE:-未取得} フォーマット不正の疑い"
      echo "action=exit(1)"
      python3 -c "
import json, sys
print(json.dumps({
  'ts':       '$(date -u +%Y-%m-%dT%H:%M:%SZ)',
  'agent':    'gardevoir_hook_critic',
  'score':    int('${_GDV_SCORE:-0}' or 0),
  'verdict':  'HARD_FAIL',
  'retry':    int('${_GDV_RETRY:-0}' or 0),
  'must_fix': '',
  'run_id':   '${RUN_ID:-unknown}',
  'pipeline': 'breaking',
  'title':    sys.argv[1],
  'category': sys.argv[2],
  'reason':   'score=${_GDV_SCORE:-未取得} format_error',
  'action':   'exit(1)',
}, ensure_ascii=False))" "${_GDV_TITLE}" "${_GDV_CATEGORY}" >> "$SCRIPT_DIR/logs/gardevoir_hook.jsonl"
    fi

    # Discord urgent通知
    _GDV_DISCORD_MSG="🛑 *刺さり品質HARD_FAIL* — 公開停止\nScore: ${_GDV_SCORE:-?} / RETRY: ${_GDV_RETRY}回\nTitle: ${_GDV_TITLE}\nMUST_FIX: ${_GDV_MUST_FIX}"
    if command -v python3 &>/dev/null && [ -f lib/discord_channels.sh ]; then
      source lib/discord_channels.sh
      _GDV_WH=$(get_discord_webhook urgent_errors 2>/dev/null || echo "")
      if [ -n "$_GDV_WH" ]; then
        curl -s -X POST "$_GDV_WH" \
          -H 'Content-Type: application/json' \
          -d "{\"content\":\"${_GDV_DISCORD_MSG}\"}" > /dev/null 2>&1 || true
      fi
    fi
    archive_and_exit 1
  fi
done

# ─── [3.9] arceus前シェルハードガード（LLM不使用・即判定） ───────────────────
echo "=== [3.9] arceus前ハードガード ==="
python3 - <<'PRE_ARCEUS_GUARD'
import re, sys
from pathlib import Path

src = Path("reports/2_checked.md")
if not src.exists():
    print("🚨 GUARD: reports/2_checked.md が存在しない")
    sys.exit(1)

text = src.read_text(encoding="utf-8", errors="replace")
lines = text.splitlines()
title = lines[0].strip() if lines else ""

# タイトル文字数チェック（20文字未満は即停止）
if len(title) < 20:
    print(f"🚨 GUARD: タイトルが短すぎる ({len(title)}文字 < 20) → arceus停止")
    sys.exit(1)

# 本文プレーンテキスト文字数チェック（800文字未満は即停止）
plain = re.sub(r'<[^>]+>', '', text)
plain = re.sub(r'\s+', '', plain)
if len(plain) < 800:
    print(f"🚨 GUARD: 本文テキストが短すぎる ({len(plain)}文字 < 800) → arceus停止")
    sys.exit(1)

# K-POP文脈キーワードチェック（タイトルに1つもなければ警告ログ出力・停止はしない）
kpop_words = ['K-POP','K-pop','KPOP','韓国','アイドル','カムバック',
              'ガールズグループ','ボーイズグループ','K-POPアイドル',
              'BTS','BLACKPINK','NewJeans','IVE','aespa','ILLIT','TWICE',
              'SHINee','BIGBANG','Stray Kids','ATEEZ','SEVENTEEN','NCT',
              'EXO','GOT7','MONSTA X','MAMAMOO','Red Velvet','Girls Generation',
              'MAMA','Coachella','コーチェラ']
has_kpop = any(w in title for w in kpop_words)
if not has_kpop:
    print(f"⚠️ GUARD_WARN: タイトルにK-POP文脈語なし: '{title}' → post_audit [2b] でフォールバック対応")

print(f"✅ GUARD: タイトル={len(title)}文字 本文={len(plain)}文字 K-POP文脈={'あり' if has_kpop else '警告'}")
sys.exit(0)
PRE_ARCEUS_GUARD
if [[ $? -ne 0 ]]; then
  echo "❌ arceus前ハードガード失敗 → パイプライン停止"
  log_step "pre_arceus_guard" "rejected" "reports/2_checked.md" "ハードガード: 文字数不足"
  archive_and_exit 1
fi

echo "=== [4] アルセウス: 品質監督・最終承認 ==="
claude --no-session-persistence --agent arceus -p "
今日は${TODAY}です。
以下の記事を監督・審査し、投稿可否を判定せよ。

${NO_CONV_RULE}

【記事（ジラーチ出力）】
$(cat reports/2_checked.md)

【パイプライン担当エージェント】
- デオキシス（速報取得）: 事実・数字・日付の充実度
- メタモン（CTRリライト）: タイトル強度・フックの質
- ジラーチ（ファクトチェック）: 時制・事実整合・出力形式

【最終記事の合格基準】
- 1行目がタイトル文字列のみ（##なし）
- 本文800文字以上
- 時制が${TODAY}と整合している
- 情報元の記載がある

エージェント別採点表・最終記事品質評価・投稿承認/却下を出力せよ。

【最終判定の絶対ルール（厳守）】
出力の末尾に必ず以下のどちらか一方のみを記載せよ：
- 投稿する場合 → 「✅ 投稿承認」
- 投稿しない場合 → 「❌ 投稿却下：〇〇のため」
「条件付き承認」「保留」「投稿不可」「REJECT」「CONDITIONAL」等の表現は絶対禁止。
パイプラインは「✅ 投稿承認」か「❌ 投稿却下」の2文字列のみを検出して動作する。
" > reports/3_arceus.md
sanitize_output reports/3_arceus.md
check_output reports/3_arceus.md "アルセウス"

# 却下キーワードの検出（Arceusの表記揺れを全網羅）
if grep -qE '(❌ 投稿却下|投稿判定.*却下|条件付き却下|却下（REJECT）|却下\(REJECT\)|^.*投稿不可|REJECT)' reports/3_arceus.md; then
  echo "❌ アルセウスが投稿を却下しました"
  grep -E '(投稿却下|却下|REJECT|投稿不可)' reports/3_arceus.md | head -3
  log_step "arceus" "rejected" "reports/3_arceus.md" "投稿却下"
  archive_and_exit 1
fi
# 「条件付き承認」単独（英語なし）は禁止表現 → 却下扱いとして安全停止
# ※Arceusがプロンプト違反で「条件付き承認」を出力してもarchive_and_exit 1になる（これは正常動作）
if grep -qE '条件付き承認' reports/3_arceus.md; then
  echo "❌ アルセウスが禁止表現「条件付き承認」を使用（フォーマット違反・却下扱い）"
  echo "  ヒント: Arceusプロンプトの最終判定ルールを確認してください"
  log_step "arceus" "rejected" "reports/3_arceus.md" "禁止表現:条件付き承認"
  archive_and_exit 1
fi
# 承認キーワードが存在しない場合も安全のため停止
# 注意: 「条件付き承認」「CONDITIONAL APPROVE」は除外（誤通過防止）
if ! grep -qE '(✅ 投稿承認|✅ 承認|投稿判定.*承認|投稿OK|即時投稿可)' reports/3_arceus.md; then
  echo "❌ アルセウスの承認が確認できません（安全停止）"
  log_step "arceus" "rejected" "reports/3_arceus.md" "承認確認不可"
  archive_and_exit 1
fi
log_step "arceus" "approved" "reports/3_arceus.md"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# final_post.md 生成（審査レポート分離）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo "=== final_post.md 生成 ==="

# [ガード0] ソースファイルの存在・空チェック
if [[ ! -f reports/2_checked.md ]]; then
  echo "🚨 BLOCK: reports/2_checked.md が存在しません"
  archive_and_exit 1
fi
if [[ ! -s reports/2_checked.md ]]; then
  echo "🚨 BLOCK: reports/2_checked.md が空です"
  archive_and_exit 1
fi

# [ガード1] 審査レポート文言の混入チェック
REVIEW_CHECK=$(grep -cE '(エージェント別採点|最終記事品質評価|投稿承認|投稿却下|採点表|/50点|/10点|デオキシス:|メタモン:|ジラーチ:|アルセウス:|修正箇所：|修正サマリー|チェック項目：|【修正内容】)' reports/2_checked.md || true)
if [ "$REVIEW_CHECK" -gt 0 ]; then
  echo "🚨 BLOCK: 審査レポートの文言が記事本文に混入しています（${REVIEW_CHECK}箇所）"
  echo "  検出内容:"
  grep -E '(エージェント別採点|最終記事品質評価|投稿承認|投稿却下|採点表|/50点|/10点|デオキシス:|メタモン:|ジラーチ:|アルセウス:|修正箇所：|修正サマリー|チェック項目：|【修正内容】)' reports/2_checked.md | head -5
  archive_and_exit 1
fi
python3 - <<'PY'
from pathlib import Path
import re

src = Path("reports/2_checked.md")
dst = Path("reports/final_post.md")

text = src.read_text(encoding="utf-8", errors="replace")
lines = text.splitlines()

# 最初のHTMLブロックタグ行を探す
html_idx = None
for i, line in enumerate(lines):
    if re.match(r'\s*<(h[1-6]|p[ >]|ul|ol|div|hr|blockquote)', line, re.IGNORECASE):
        html_idx = i
        break

if html_idx is not None:
    # HTML行より前の非空・非HTMLの行をタイトルとして採用
    title_idx = None
    for j in range(html_idx - 1, -1, -1):
        s = lines[j].strip()
        if not s:
            continue
        if not s.startswith("<"):
            title_idx = j
            break
    start = title_idx if title_idx is not None else html_idx
    cleaned = "\n".join(lines[start:]).strip() + "\n"
else:
    # HTMLタグなし → フォールバック（従来動作）
    cleaned = text.strip() + "\n"

dst.write_text(cleaned, encoding="utf-8")
PY

# [ガード2] 質問文・AI定型文・許可要求文の混入チェック
# [ガード2] sanitize_output で既に除去済みだが念のためチェック
# ※ 「できません$」は通常記事で誤検知するため除外
# ※ 「WebSearch」「ウェブ検索」は単体だと誤検知するため「許可」とセットで検出
QUESTION_CHECK=$(grep -ciE '(質問があります|確認させてください|お手伝いできますか|申し訳ありません[がで。、 ]|申し訳ありません$|承知しました|以下に示します|AIとして[、。]|言語モデルとして|お答えできません|許可してください|許可を?いただ|許可が必要です|WebSearch.*許可|ウェブ検索.*許可|どちらで進めますか|Web tools are currently blocked|WebSearch requires a permission|I don.t have access to web search|Tool use is not available|Search is not available|I.m unable to use tools)' reports/2_checked.md || true)
if [ "$QUESTION_CHECK" -gt 0 ]; then
  echo "🚨 BLOCK: 質問文またはAI定型文が記事本文に混入しています（${QUESTION_CHECK}箇所）"
  echo "  検出内容:"
  grep -iE '(質問があります|確認させてください|お手伝いできますか|申し訳ありません[がで。、 ]|申し訳ありません$|承知しました|以下に示します|AIとして[、。]|言語モデルとして|お答えできません|許可してください|許可をいただ|許可が必要です|WebSearch.*許可|ウェブ検索.*許可|どちらで進めますか|Web tools are currently blocked|WebSearch requires a permission|I don.t have access to web search|Tool use is not available|Search is not available|I.m unable to use tools)' reports/2_checked.md | head -5
  archive_and_exit 1
fi

echo "  ✓ reports/final_post.md 生成完了"

echo "=== 投稿 ==="

# 投稿対象: final_post.md のみ（2_checked.mdや3_arceus.mdからは絶対に投稿しない）
TITLE=$(head -n 1 reports/final_post.md)
check_duplicate "$TITLE" 7
# 速報判定: デオキシスが【速報】を付けた場合のみ速報扱い（無条件付加しない）
# 既に【速報】が含まれていればそのまま、なければ付けない
CONTENT=$(tail -n +2 reports/final_post.md)

# v1.3: まとめ/ランキング/スケジュール系記事から【速報】を強制除去
if echo "$TITLE" | grep -q '【速報】'; then
  if echo "$TITLE" | grep -qE '(まとめ|スケジュール|ランキング|一覧|TOP[0-9]|チャート|振り返り|解説|徹底|比較|分析|予定|カレンダー|イベント情報|月間|週間)'; then
    echo "  ⚠️ v1.3: まとめ/ランキング系記事から【速報】を除去"
    TITLE=$(echo "$TITLE" | sed 's/【速報】//')
    # final_post.md の1行目も更新
    sed -i "1s/【速報】//" reports/final_post.md
  fi
fi

echo "=== 品質チェック ==="

# -----------------------------------------------
# [A] タイトル基本チェック
# -----------------------------------------------
if [[ -z "$TITLE" ]]; then
  echo "❌ 品質NG: タイトルが空 → 投稿停止"
  archive_and_exit 1
fi

# タイトルNGワード（AI定型文・マークダウン記法）
TITLE_NG_RESULT=$(python3 - << 'PY' "$TITLE"
import sys
t = sys.argv[1]
ng_words = [
    "お手伝いできますか", "申し訳ありません", "承知しました", "以下に",
    "まとめました", "解説します", "ご質問", "サポート",
    "AIとして", "言語モデル", "できません", "お答えできません",
    "修正箇所", "修正サマリー", "##",
    "入力記事が見当たりません", "記事が見当たりません", "記事を提供してください",
    "以下の記事を提供", "記事の入力が見当たりません", "元となる記事の原文",
    "元の記事が提供されていません", "入力記事が提供されていない",
]
# 英語Claudeエラーメッセージ（タイトル混入防止）
ng_words_en = [
    "Web tools are currently blocked", "WebSearch requires a permission",
    "I don't have access to web search", "Tool use is not available",
    "I'm not able to access", "I cannot access the web",
    "Search is not available", "I can't perform web search",
    "I'm unable to use tools", "I do not have access to",
]
hit = [w for w in ng_words if w in t]
hit += [w for w in ng_words_en if w.lower() in t.lower()]
# 英語混入検出（K-POP固有名詞以外の英文がタイトルの大部分を占める場合）
import re as _re
# 日本語文字（ひらがな・カタカナ・漢字）が含まれるタイトルはK-POP記事として正常
# 例: "NewJeans「How Sweet」問題提起" → 日本語含むので除外
has_japanese = bool(_re.search(r'[\u3040-\u30ff\u4e00-\u9fff]', t))
if not has_japanese:
    alpha_chars = len(_re.findall(r'[a-zA-Z]', t))
    total_chars = len(t.strip())
    if total_chars > 0 and alpha_chars / total_chars > 0.5:
        hit.append("英語比率過大")
# マークダウンコードブロック検出
if t.startswith("#") or "```" in t:
    hit.append("markdown記法")
print("|".join(hit) if hit else "OK")
PY
)
if [[ "$TITLE_NG_RESULT" != "OK" ]]; then
  echo "❌ 品質NG: タイトルにNGワード（$TITLE_NG_RESULT）→ 投稿停止"
  archive_and_exit 1
fi

# タイトル文字数（24〜45文字）
TITLE_LEN=${#TITLE}
if [ "$TITLE_LEN" -lt 20 ]; then
  echo "❌ 品質NG: タイトルが短すぎる（${TITLE_LEN}文字）→ 投稿停止"
  archive_and_exit 1
fi
if [ "$TITLE_LEN" -gt 60 ]; then
  echo "⚠️  警告: タイトルが長すぎる（${TITLE_LEN}文字）→ 続行"
fi
echo "  ✓ タイトル文字数OK（${TITLE_LEN}文字）"

# CTR弱ワード警告（停止しない・ログのみ）
_CTR_WARN=$(python3 -c "
import sys, re
t = sys.argv[1]
weak = ['について解説', 'まとめ', 'とは?', 'とは？', 'とは ', 'とは$', '分析', 'の魅力', '徹底解説', '完全解説', 'ガイド', '一覧']
hit = [w for w in weak if re.search(re.escape(w), t)]
print(','.join(hit) if hit else '')
" "$TITLE" 2>/dev/null || true)
if [[ -n "$_CTR_WARN" ]]; then
  echo "  ⚠️ [CTR警告] タイトルに弱ワードあり: $_CTR_WARN → 続行（停止しない）"
fi

# -----------------------------------------------
# [B] 本文基本チェック
# -----------------------------------------------
if [[ -z "$CONTENT" ]]; then
  echo "❌ 品質NG: 本文が空 → 投稿停止"
  archive_and_exit 1
fi

# 本文NGワード（AI定型文・エラー応答）
CONTENT_NG_RESULT=$(python3 - << 'PY' "$CONTENT"
import sys
c = sys.argv[1]
import re as _re
# 部分一致NGワード（完全な文字列でのみヒット、通常語彙の誤検知を防ぐ）
# 「申し訳ありません」は「申し訳なくて」等の通常語彙と区別するため後読みで限定
ng_patterns = [
    r'申し訳ありません[がで。、\n]|申し訳ありません$',  # AI謝罪定型文のみ（「申し訳なくて」等は除外）
    r'お手伝いできますか', r'確認させてください', r'許可してください',
    r'許可をいただ', r'許可が必要です', r'質問があります',
    r'以下に示します', r'AIとして[、。]', r'言語モデル', r'お答えできません',
    r'修正箇所：', r'修正サマリー', r'チェック項目：', r'【修正内容】',
    r'ウェブ検索の許可', r'どちらで進めますか',
    r'Web tools are currently blocked', r'WebSearch requires a permission',
    r"I don't have access to web search", r'Tool use is not available',
    r'Search is not available', r"I'm unable to use tools",
]
hit = [p for p in ng_patterns if _re.search(p, c, _re.IGNORECASE)]
# コードブロック混入チェック
if "```" in c:
    hit.append("codeblock混入")
print("|".join(hit) if hit else "OK")
PY
)
if [[ "$CONTENT_NG_RESULT" != "OK" ]]; then
  echo "⚠️  本文NGワード検出（$CONTENT_NG_RESULT）→ 自動修正を試みる"
  # NGワードを含む段落のみClaudeで書き換え（1回のみリトライ）
  CONTENT_FIXED=$(claude --no-session-persistence -p "
以下のHTML記事本文にAI定型文（${CONTENT_NG_RESULT}）が含まれています。
その表現を自然な日本語に書き換えてください。
記事の内容・構造・HTMLタグはそのまま維持し、NGワード部分だけを修正してください。
修正後のHTML本文のみ出力してください（説明文は不要）。

--- 本文 ---
${CONTENT}
" 2>/dev/null || echo "")
  if [[ -n "$CONTENT_FIXED" ]]; then
    # 再チェック
    CONTENT_NG_RETRY=$(python3 - << 'PY' "$CONTENT_FIXED"
import sys, re as _re
c = sys.argv[1]
ng_patterns = [
    r'申し訳ありません[がで。、\n]|申し訳ありません$',
    r'お手伝いできますか', r'確認させてください', r'許可してください',
    r'許可をいただ', r'許可が必要です', r'質問があります',
    r'以下に示します', r'AIとして[、。]', r'言語モデル', r'お答えできません',
    r'修正箇所：', r'修正サマリー', r'チェック項目：', r'【修正内容】',
    r'ウェブ検索の許可', r'どちらで進めますか',
    r'Web tools are currently blocked', r'WebSearch requires a permission',
    r"I don't have access to web search", r'Tool use is not available',
    r'Search is not available', r"I'm unable to use tools",
]
hit = [p for p in ng_patterns if _re.search(p, c, _re.IGNORECASE)]
if "```" in c:
    hit.append("codeblock混入")
print("|".join(hit) if hit else "OK")
PY
)
    if [[ "$CONTENT_NG_RETRY" == "OK" ]]; then
      echo "  ✓ 自動修正成功 → 修正後の本文を使用"
      CONTENT="$CONTENT_FIXED"
      # final_post.md を更新
      { head -n 1 reports/final_post.md; echo "$CONTENT_FIXED"; } > reports/final_post.md.tmp && mv reports/final_post.md.tmp reports/final_post.md
    else
      echo "❌ 品質NG: 自動修正後もNGワード残存（$CONTENT_NG_RETRY）→ 投稿停止"
      archive_and_exit 1
    fi
  else
    echo "❌ 品質NG: 本文にNGワード（$CONTENT_NG_RESULT）、自動修正失敗 → 投稿停止"
    archive_and_exit 1
  fi
fi

# -----------------------------------------------
# [C] 実文字数チェック（HTMLタグ除外）
# -----------------------------------------------
CONTENT_STATS=$(python3 - << 'PY' "$CONTENT"
import sys, re
content = sys.argv[1]
plain = re.sub(r'<[^>]+>', '', content).strip()
plain = re.sub(r'\s+', ' ', plain)
char_count = len(plain)
h2_count = len(re.findall(r'<h2', content, re.IGNORECASE))
h3_count = len(re.findall(r'<h3', content, re.IGNORECASE))
p_count  = len(re.findall(r'<p',  content, re.IGNORECASE))
has_source = any(w in content for w in ['情報元', '出典', '参照', '引用', '参考'])
print(f"{char_count}|{h2_count}|{h3_count}|{p_count}|{'YES' if has_source else 'NO'}")
PY
)

PLAIN_CHARS=$(echo "$CONTENT_STATS" | cut -d'|' -f1)
H2_COUNT=$(echo "$CONTENT_STATS"    | cut -d'|' -f2)
H3_COUNT=$(echo "$CONTENT_STATS"    | cut -d'|' -f3)
P_COUNT=$(echo "$CONTENT_STATS"     | cut -d'|' -f4)
HAS_SOURCE=$(echo "$CONTENT_STATS"  | cut -d'|' -f5)

echo "  純テキスト: ${PLAIN_CHARS}文字 / h2:${H2_COUNT} / h3:${H3_COUNT} / p:${P_COUNT} / 情報元:${HAS_SOURCE}"

if [ "$PLAIN_CHARS" -lt 1500 ]; then
  echo "❌ 品質NG: 純テキストが1500文字未満（${PLAIN_CHARS}文字）→ 投稿停止"
  archive_and_exit 1
fi

if [ "$H2_COUNT" -lt 2 ]; then
  echo "❌ 品質NG: h2見出しが少なすぎる（${H2_COUNT}個）→ 投稿停止"
  archive_and_exit 1
fi

if [[ "$HAS_SOURCE" == "NO" ]]; then
  echo "⚠️  警告: 情報元の記載なし → 続行（要改善）"
fi

CONTENT_LENGTH="$PLAIN_CHARS"
echo "✅ 品質OK（純テキスト${PLAIN_CHARS}文字 / h2:${H2_COUNT} / p:${P_COUNT}）"

# ─── [C-QUALITY] 同ジャンル連投チェック（明示的BLOCK） ───────────────────────
echo "=== [品質C] 同ジャンル連投チェック ==="
_SAME_GENRE_BLOCK=$(python3 - << 'GENRE_BLOCK_PY' "$CATEGORY_ID" "${CATEGORY_HINT:-}"
import sys, json, urllib.request, os
from datetime import datetime, timezone, timedelta

cat_id = sys.argv[1] if len(sys.argv) > 1 else ""
cat_hint = sys.argv[2] if len(sys.argv) > 2 else ""

# ジャンルグループ定義（同グループ内は連投禁止）
GENRE_GROUPS = {
    "chart":    ["71", "chart", "チャート", "ランキング"],
    "comeback": ["3", "comeback", "カムバック"],
    "beauty":   ["12", "beauty", "美容", "コスメ"],
    "travel":   ["11", "travel", "旅行"],
    "live":     ["5", "live", "ライブ", "コンサート"],
    "fashion":  ["30", "fashion", "ファッション"],
    "breaking": ["7", "breaking", "速報"],
}

def detect_genre(cat_id_str, hint):
    for g, keywords in GENRE_GROUPS.items():
        if any(k in cat_id_str or k in hint for k in keywords):
            return g
    return None

my_genre = detect_genre(cat_id, cat_hint)
if not my_genre:
    print("SKIP:ジャンル不明")
    sys.exit(0)

# 直近24時間の投稿を取得
cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
try:
    auth_file = os.path.expanduser("~/.wp_auth")
    auth = ""
    if os.path.exists(auth_file):
        import re as _re
        with open(auth_file) as f:
            m = _re.search(r'Basic\s+(\S+)', f.read())
            if m: auth = m.group(1)
    headers = {"Authorization": f"Basic {auth}"} if auth else {}
    url = f"https://www.kpopjournal.tokyo/wp-json/wp/v2/posts?per_page=10&after={urllib.request.quote(cutoff)}&status=publish&_fields=id,title,categories"
    req = urllib.request.Request(url, headers={**headers, "User-Agent": "kpop-gate/1.0"})
    with urllib.request.urlopen(req, timeout=6) as resp:
        posts = json.loads(resp.read())
except Exception as e:
    print(f"SKIP:取得失敗({e})")
    sys.exit(0)

for p in posts:
    cats = p.get("categories", [])
    title2 = p.get("title", {}).get("rendered", "")
    # カテゴリIDで同ジャンル判定
    for g, keywords in GENRE_GROUPS.items():
        if g == my_genre:
            for k in keywords:
                if k.isdigit() and int(k) in cats:
                    print(f"BLOCK:{my_genre}ジャンルが直近24h以内に投稿済み → ID={p.get('id')} {title2[:40]}")
                    sys.exit(0)

print("OK")
GENRE_BLOCK_PY
)

echo "  同ジャンル連投チェック: $_SAME_GENRE_BLOCK"
if [[ "$_SAME_GENRE_BLOCK" == BLOCK:* ]]; then
  echo "❌ 同ジャンル連投BLOCK: $_SAME_GENRE_BLOCK → 投稿停止"
  log_step "genre_block" "BLOCKED" "" "$_SAME_GENRE_BLOCK"
  archive_and_exit 1
fi

STATUS="publish"

echo "=== CTRタイトル採点 ==="
TITLE_SCORE_JSON=$(python3 $SCRIPT_DIR/google_metrics/score_title_ctr.py "$TITLE")
echo "$TITLE_SCORE_JSON"

TITLE_PASS=$(python3 - << 'PY2' "$TITLE_SCORE_JSON"
import json, sys
data = json.loads(sys.argv[1])
print("YES" if data.get("pass") else "NO")
PY2
)

TITLE_SCORE=$(python3 - << 'PY3' "$TITLE_SCORE_JSON"
import json, sys
data = json.loads(sys.argv[1])
print(data.get("score", 0))
PY3
)

echo "TITLE_SCORE=$TITLE_SCORE"

if [ "$TITLE_PASS" != "YES" ]; then
  echo "⚠️ CTR WARNING: タイトルスコア低 → 警告のみで続行"
  # exit 1  # テスト期間中は停止しない
fi

echo "=== サムネ文言生成（v4: テンプレート選択） ==="

# ── THUMB_GENRE: THEME_INPUT・CATEGORY_HINT・タイトルからジャンルを決定 ──
THUMB_GENRE=$(python3 - << 'GENRE_PY' "$TITLE" "${CATEGORY_HINT:-}" "${THEME_INPUT:-}"
import sys, re

title       = sys.argv[1].lower()
cat_hint    = sys.argv[2].lower()
theme_input = sys.argv[3].lower()
combined    = title + " " + cat_hint + " " + theme_input

# カテゴリヒント（ミュウツー判断）優先
cat_map = {
    "旅行": "travel", "ライフスタイル": "travel",
    "美容": "beauty", "コスメ": "beauty",
    "ファッション": "fashion",
    "カムバック": "comeback", "速報": "breaking",
    "イベント": "live", "ゴシップ": "expose",
    "解説": "analysis", "ランキング": "ranking",
}
for k, v in cat_map.items():
    if k in cat_hint:
        print(v); sys.exit()

# THEME_INPUT（cron引数）からジャンル判定
theme_map = [
    (["旅行", "ソウル", "カフェ", "聖地巡礼", "ポップアップ"], "travel"),
    (["美容", "コスメ", "スキンケア", "ガラス肌"], "beauty"),
    (["ファッション", "着用", "コーデ", "ブランド"], "fashion"),
    (["チャート", "ランキング", "billboard"], "ranking"),
    (["ライブ", "コンサート", "ツアー", "来日"], "live"),
]
for keywords, genre in theme_map:
    if any(k in theme_input for k in keywords):
        print(genre); sys.exit()

# タイトルから判定
title_map = [
    (["旅行", "ソウル", "カフェ", "聖地", "観光", "グルメ"], "travel"),
    (["美容", "コスメ", "スキンケア", "メイク", "ガラス肌"], "beauty"),
    (["ファッション", "着用", "コーデ", "ブランド", "即完売"], "fashion"),
    (["チャート", "ランキング", "1位", "billboard"], "ranking"),
    (["ライブ", "コンサート", "ツアー", "公演", "来日"], "live"),
    (["カムバック", "新曲", "アルバム", "復帰", "復活"], "comeback"),
    (["暴露", "炎上", "騒動", "脱退", "事件", "スキャンダル"], "expose"),
    (["美容", "コスメ", "スキンケア"], "beauty"),
    (["速報", "緊急", "判明", "電撃", "衝撃"], "breaking"),
]
for keywords, genre in title_map:
    if any(k in title for k in keywords):
        print(genre); sys.exit()
print("breaking")
GENRE_PY
)
echo "THUMB_GENRE=$THUMB_GENRE"

THUMB_TITLE=$(python3 "$SCRIPT_DIR/lib/thumbnail_templates.py" "$TITLE" --genre "$THUMB_GENRE")

echo "THUMB_TITLE=$THUMB_TITLE"

echo "=== サムネ文言採点（v3） ==="
THUMB_SCORE_JSON=$(python3 $SCRIPT_DIR/google_metrics/score_thumbnail_text.py "$THUMB_TITLE")
echo "$THUMB_SCORE_JSON"

THUMB_PASS=$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); print('YES' if d.get('pass') else 'NO')" "$THUMB_SCORE_JSON")
THUMB_SCORE=$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); print(d.get('score',0))" "$THUMB_SCORE_JSON")
echo "THUMB_SCORE=$THUMB_SCORE"

# ジャンル別の強ワードマップ
_GENRE_STRONG_WORDS=$(python3 -c "
import sys
genre = sys.argv[1]
words = {
    'travel':   '穴場解禁／完全版／現地レポ／神カフェ／速攻いける',
    'beauty':   '神コスメ／完全公開／真似できる／激変／秘密',
    'fashion':  '着用判明／即完売／神コーデ／完全版／激安',
    'comeback': '解禁／ついに／新曲全公開／待望／電撃',
    'live':     '当日レポ／速攻まとめ／現地の声／完全版／涙',
    'ranking':  '1位確定／神記録／独占／衝撃結果／完全版',
    'expose':   '暴露／真相判明／衝撃告白／炎上の真実／独占',
    'analysis': '完全解説／深掘り／全容判明／なぜ／真相',
    'breaking': '速報／判明／緊急／電撃／衝撃',
}.get(genre, '速報／判明／解禁／ついに／衝撃')
print(words)
" "$THUMB_GENRE")

if [ "$THUMB_PASS" != "YES" ]; then
  echo "⚠️ サムネ文言NG(score=$THUMB_SCORE) → Claude fallback 1回 (genre=$THUMB_GENRE)"
  THUMB_TITLE=$(claude --no-session-persistence -p "
サムネイル用の文言を出力してください。ターゲットは10〜30代の女性K-POPファンです。
記事ジャンル：${THUMB_GENRE}

【絶対ルール】
・最大2行（改行で区切る）
・1行あたり最大10文字（厳守）
・強ワード必須（ジャンルに合うもの）：${_GENRE_STRONG_WORDS}
・速報・判明などのニュース系ワードは速報(breaking)以外のジャンルでは使わない
・数字があれば優先的に入れる
・アーティスト名があれば入れる
・弱ワード禁止：まとめ／解説／情報
・コロン禁止。文言のみ出力。

タイトル：
$TITLE
" | grep -v '^$' | head -2)
  echo "RETRY THUMB_TITLE=$THUMB_TITLE"
  THUMB_SCORE_JSON=$(python3 $SCRIPT_DIR/google_metrics/score_thumbnail_text.py "$THUMB_TITLE")
  THUMB_PASS=$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); print('YES' if d.get('pass') else 'NO')" "$THUMB_SCORE_JSON")
  if [ "$THUMB_PASS" != "YES" ]; then
    echo "❌ 再生成もNG → select_thumbnail_text()でテンプレート生成"
    THUMB_TITLE=$(python3 -c "
import sys
sys.path.insert(0, '$(dirname "$0")')
from lib.thumbnail_templates import select_thumbnail_text
print(select_thumbnail_text(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None))
" "$TITLE" "$THUMB_GENRE")
    echo "TEMPLATE THUMB_TITLE=$THUMB_TITLE"
  fi
fi

echo "=== アイキャッチ生成（v3: 固定テンプレ背景） ==="
THUMB_META_FILE=$(mktemp)
python3 $SCRIPT_DIR/make_thumbnail.py "$THUMB_TITLE" --title "$TITLE" --genre "$THUMB_GENRE" 2>"$THUMB_META_FILE"
THUMB_META_LINE=$(grep "^THUMB_META: " "$THUMB_META_FILE" | head -1 | sed 's/^THUMB_META: //')
rm -f "$THUMB_META_FILE"
[ -n "$THUMB_META_LINE" ] && echo "  thumb_meta: $THUMB_META_LINE"

echo "=== アイキャッチアップロード ==="
MEDIA_RESPONSE=$(curl -s -X POST https://www.kpopjournal.tokyo/wp-json/wp/v2/media \
-K ~/.wp_auth \
-H "Content-Disposition: attachment; filename=thumbnail.webp" \
-H "Content-Type: image/webp" \
--data-binary @thumbnail.webp)

MEDIA_ID=$(echo "$MEDIA_RESPONSE" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('id',''))" 2>/dev/null)

# === アイキャッチ ALTテキスト自動設定（再発防止: ALT空防止） ===
if [ -n "$MEDIA_ID" ]; then
  ALT_TEXT=$(python3 -c "
import sys, re
title = '''$TITLE'''
# タイトルから簡潔なALTテキストを生成（120文字以内）
alt = re.sub(r'[【】「」『』\|｜]', ' ', title).strip()
alt = re.sub(r'\s+', ' ', alt)[:100]
print(alt)
" 2>/dev/null)
  curl -s -X POST "https://www.kpopjournal.tokyo/wp-json/wp/v2/media/${MEDIA_ID}" \
    -K ~/.wp_auth \
    -H "Content-Type: application/json" \
    -d "{\"alt_text\": \"$(echo "$ALT_TEXT" | sed 's/"/\\"/g')\"}" > /dev/null 2>&1
  echo "  ✅ ALTテキスト設定: ${ALT_TEXT:0:50}..."
fi

# === サムネイルコピー品質警告（pre-publish thumbnail check） ===
if [[ -n "${THUMB_TITLE:-}" ]]; then
  echo "=== サムネイルコピー品質チェック ==="
  python3 - << 'THUMB_CHECK_PY' "${THUMB_TITLE:-}" "${TITLE:-}"
import sys, re
copy = sys.argv[1] if len(sys.argv) > 1 else ""
title = sys.argv[2] if len(sys.argv) > 2 else ""

ARTIST_PAT = re.compile(
    r"BTS|TWICE|BLACKPINK|IVE|ILLIT|aespa|NewJeans|ENHYPEN|TXT|"
    r"Stray\s*Kids|SEVENTEEN|NCT|ATEEZ|TOP|RIIZE|BIGBANG|SHINee|MAMAMOO",
    re.IGNORECASE
)

issues = []
blocks = []

if not copy:
    issues.append("コピーテキストなし")
else:
    if ".." in copy:
        blocks.append(f"'..'パターン検出（フォントバグ）: '{copy}'")
    if "「」" in copy:
        blocks.append(f"「」空パターン検出: '{copy}'")
    if len(copy) > 28:
        issues.append(f"コピー長={len(copy)}文字（28文字超、オーバーフロー懸念）")
    if not ARTIST_PAT.search(copy):
        issues.append(f"アーティスト名未検出: '{copy}'")
    # タイトルキーワード一致チェック
    if title:
        tw = set(re.findall(r"[\w]+", title.lower()))
        cw = set(re.findall(r"[\w]+", copy.lower()))
        if tw and cw:
            overlap = len(tw & cw) / len(tw)
            if overlap < 0.1:
                issues.append(f"タイトルとコピーの一致率低（{overlap:.0%}）")

if blocks:
    for b in blocks:
        print(f"  ❌ [サムネ/BLOCK] {b}")
    sys.exit(1)
elif issues:
    for i in issues:
        print(f"  ⚠️ [サムネ/WARN] {i}")
else:
    print(f"  ✅ サムネイルコピーOK: '{copy}'")
THUMB_CHECK_PY
fi

# === カテゴリ自動判定（15分類） ===
CATEGORY_ID=$(python3 - << 'PY' "$TITLE"
import sys
title = sys.argv[1].lower()

rules = [
    (71, ['チャート','ランキング','1位','top10','top 10','top50','top 50','billboard','gaon','circle chart','spotify']),
    (3,  ['カムバック','カムバ','復帰','ソロ復帰','新アルバム','ミニアルバム','ep','カムバック決定']),
    (6,  ['新曲','新曲リリース','mv公開','ミュージックビデオ','先行公開','配信開始','音源公開']),
    (5,  ['ライブ','コンサート','ツアー','来日','ファンミ','ファンミーティング','チケット']),
    (7,  ['出演','出演決定','出演情報','テレビ','番組','放送','ラジオ','ゲスト出演']),
    (28, ['音楽番組','人気歌謡','music bank','m countdown','show champion','music core']),
    (8,  ['ドラマ','主演','出演ドラマ','配信ドラマ','俳優','女優']),
    (27, ['映画','映画出演','映画化','スクリーンデビュー']),
    (30, ['ファッション','着用','コーデ','私服','ストリートスナップ','outfit','ブランドコレクション']),
    (13, ['新商品','発売','限定発売','新作','グッズ','公式グッズ']),
    (12, ['美容','コスメ','スキンケア','ヘアケア','ダイエット','サロン','クリニック','ガラス肌','グラスキン','ルーティン','保湿','洗顔','美白','韓国スキンケア','韓国コスメ']),
    (11, ['旅行','釜山','観光','レストラン','渡韓','タクシー','聖地巡礼','ポップアップ','カフェ','ソウル','ホテル']),
    (111,['視聴方法','どこで見れる','無料視聴','配信サービス','配信比較','サブスク','abema','netflix','hulu','prime video']),
    (112,['プロフィール','メンバー紹介','経歴','生年月日','身長','出身','デビュー日']),
    (113,['入門','初心者','始め方','完全ガイド','わかりやすく','ゼロから']),
    (14, ['熱愛','炎上','騒動','脱退','訴訟','事件','問題','謝罪','ゴシップ']),
    (9,  ['話題','注目','反応','バズ','拡散','snsで話題','海外の反応']),
    (4,  ['考察','分析','なぜ','理由','比較','解説','深掘り','特集','まとめ','徹底解説','戦略','グローバル','ボーカル','トレーニング','練習生','レッスン']),
]

for cid, keywords in rules:
    if any(word in title for word in keywords):
        print(cid)
        sys.exit()

print(2)
PY
)

echo "CATEGORY_ID=$CATEGORY_ID"

# === アーティスト別カテゴリ自動判定 ===
ARTIST_CATEGORY_IDS=$(python3 - << 'PY' "$TITLE"
import sys, re
title = sys.argv[1].lower()

def match_keyword(title, keyword):
    """短語・単語バウンダリーを考慮したマッチング。誤検知防止。"""
    if len(keyword) <= 2:
        # 1〜2文字は完全単語マッチのみ（スペース/記号/文字列境界）
        return bool(re.search(r'(?<![a-z0-9])' + re.escape(keyword) + r'(?![a-z0-9])', title))
    return keyword in title

artist_rules = [
    (19, ['bigbang', 'g-dragon', 'gd', 'taeyang', 'daesung', 't.o.p']),
    (23, ['blackpink', 'black pink', 'jennie', 'jisoo', 'rosé', 'lisa']),
    (18, ['bts', '방탄', 'j-hope', 'jhope', 'jimin', 'jungkook', 'jung kook',
           'rm（', 'rm・', 'rm/', ' rm ', '「rm」', 'jin（', 'jin・', '「jin」',
           'suga（', 'suga・', '「suga」', 'v（', 'v・', '「v」', 'テヒョン']),
    (25, ['aespa', 'karina', 'ningning', 'giselle']),
    (38, ['babymonster', 'baby monster', 'ahyeon', 'pharita', 'rami', 'rora', 'chiquita']),
    (44, ['illit', 'iroha', 'wonhee', 'moka', 'yunah']),
    (68, ['ive', 'wonyoung', 'yujin', 'gaeul', 'leeseo']),
    (41, ['le sserafim', 'lesserafim', 'chaewon', 'yunjin', 'kazuha', 'eunchae']),
    (98, ['enhypen', 'enha', 'jungwon', 'heeseung', 'jay', 'jake', 'sunghoon', 'sunoo', 'ni-ki', 'niki']),
    (40, ['nct', 'nct wish', 'mark', 'haechan', 'taeyong', 'jaehyun', 'doyoung']),
    (32, ['newjeans', 'new jeans', 'minji', 'hani', 'danielle', 'haerin', 'hyein']),
    (39, ['riize', 'shotaro', 'sungchan', 'wonbin', 'sohee', 'anton', 'eunseok']),
    (24, ['seventeen', 'svt', 'scoups', 's.coups', 'jeonghan', 'joshua', 'jun', 'hoshi', 'wonwoo', 'woozi', 'mingyu', 'dk', 'seungkwan', 'vernon', 'dino']),
    (43, ['stray kids', 'skz', 'bang chan', 'lee know', 'changbin', 'hyunjin', 'han', 'felix', 'seungmin', 'i.n', 'in']),
    (22, ['twice', 'nayeon', 'jeongyeon', 'momo', 'sana', 'jihyo', 'mina', 'dahyun', 'chaeyoung', 'tzuyu']),
    (42, ['zerobaseone', 'zb1', 'sung hanbin', 'han yujin', 'zhang hao', 'ricky']),
    (60, ['exo', 'baekhyun', 'kai', 'suho', 'chanyeol', 'd.o.', 'kyungsoo', 'xiumin', 'chen']),
    (37, ['itzy', 'yeji', 'lia', 'ryujin', 'chaeryeong', 'yuna']),
    (45, ['boa']),
    (33, ['xg', 'jurin', 'chisa', 'hinata', 'harvey', 'juria', 'maya', 'cocona']),
]

matched = []
for cid, keywords in artist_rules:
    if any(match_keyword(title, word) for word in keywords):
        matched.append(str(cid))

print(",".join(matched))
PY
)

echo "ARTIST_CATEGORY_IDS=$ARTIST_CATEGORY_IDS"

# === アーティストカテゴリが未登録なら自動作成 ===
if [ -z "$ARTIST_CATEGORY_IDS" ]; then
  # タイトルからアーティスト名を推定（英字大文字グループ or 「」内）
  DETECTED_ARTIST=$(python3 - << 'PY' "$TITLE"
import sys, re
title = sys.argv[1]
# 「アーティスト」パターン
m = re.search(r'[「『]([^」』]{2,20})[」』]', title)
if m:
    candidate = m.group(1).strip()
    # アルバム名ではなくアーティスト名らしいもの（英字含むか短い）
    if re.search(r'[A-Za-z]', candidate) or len(candidate) <= 6:
        print(candidate)
        sys.exit()
# 英字アーティスト名（全大文字3文字以上）
matches = re.findall(r'\b[A-Z][A-Z0-9]{2,}(?:\s+[A-Z][A-Z0-9]{2,})*\b', title)
# フィルタ: 一般的な英単語を除外
stop = {'THE', 'FOR', 'AND', 'NEW', 'TOP', 'HIT', 'ALL', 'MAY', 'YG', 'SM', 'JYP', 'HYBE'}
matches = [m for m in matches if m not in stop]
if matches:
    print(matches[0])
    sys.exit()
print("")
PY
  )
  if [ -n "$DETECTED_ARTIST" ]; then
    echo "=== 新規アーティストカテゴリ自動作成: $DETECTED_ARTIST ==="
    NEW_CAT_RESPONSE=$(curl -s -X POST "https://www.kpopjournal.tokyo/wp-json/wp/v2/categories" \
      -K ~/.wp_auth \
      -H "Content-Type: application/json" \
      -d "{\"name\": \"$DETECTED_ARTIST\", \"description\": \"$DETECTED_ARTIST 関連記事\"}")
    NEW_CAT_ID=$(echo "$NEW_CAT_RESPONSE" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('id',''))" 2>/dev/null)
    if [ -n "$NEW_CAT_ID" ] && [ "$NEW_CAT_ID" != "null" ]; then
      ARTIST_CATEGORY_IDS="$NEW_CAT_ID"
      echo "  → 新規カテゴリ作成成功: ID=$NEW_CAT_ID ($DETECTED_ARTIST)"
    else
      ERR=$(echo "$NEW_CAT_RESPONSE" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('message','unknown error'))" 2>/dev/null)
      # term_exists エラーなら既存IDを取得
      if echo "$NEW_CAT_RESPONSE" | grep -q '"term_exists"'; then
        EXISTING_ID=$(echo "$NEW_CAT_RESPONSE" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('data',{}).get('term_id',''))" 2>/dev/null)
        [ -n "$EXISTING_ID" ] && ARTIST_CATEGORY_IDS="$EXISTING_ID" && echo "  → 既存カテゴリ使用: ID=$EXISTING_ID"
      else
        echo "  ⚠️ カテゴリ作成失敗: $ERR"
      fi
    fi
  fi
fi

# === タグ名候補を自動生成 ===
TAG_NAMES=$(python3 - << 'PY' "$TITLE"
import sys

title = sys.argv[1]

rules = [
    ('BTS', ['bts', '방탄', 'j-hope', 'jhope', 'jimin', 'jungkook', 'jung kook',
              'rm（', 'rm・', 'rm/', ' rm ', '「rm」', 'jin（', 'jin・', '「jin」',
              'suga（', 'suga・', '「suga」', 'v（', 'v・', '「v」', 'テヒョン']),
    ('BIGBANG', ['bigbang', 'g-dragon', 'gd', 'taeyang', 'daesung', 'top', 't.o.p']),
    ('BLACKPINK', ['blackpink', 'black pink', 'jennie', 'jisoo', 'rose', 'rosé', 'lisa']),
    ('aespa', ['aespa', 'karina', 'winter', 'ningning', 'giselle']),
    ('BABYMONSTER', ['babymonster', 'baby monster']),
    ('ILLIT', ['illit']),
    ('IVE', ['ive', 'wonyoung', 'yujin']),
    ('LE SSERAFIM', ['le sserafim', 'lesserafim']),
    ('SEVENTEEN', ['seventeen', 'svt']),
    ('TWICE', ['twice']),
    ('Stray Kids', ['stray kids', 'skz']),
    ('NewJeans', ['newjeans', 'new jeans']),
    ('XG', ['xg']),
    ('Coachella', ['coachella']),
    ('カムバック', ['カムバック', 'カムバ', '復帰']),
    ('ワールドツアー', ['ワールドツアー', 'ツアー', 'ライブ', 'コンサート']),
    ('K-POP速報', ['速報', '最新情報', 'breaking']),
]

title_l = title.lower()
matched = []

for tag_name, keywords in rules:
    if any(word in title_l for word in keywords):
        matched.append(tag_name)

matched = list(dict.fromkeys(matched))
print('|'.join(matched))
PY
)

echo "TAG_NAMES=$TAG_NAMES"

# === タグを検索 / なければ作成してIDを取得 ===
TAG_IDS=$(python3 - << 'PY' "$TAG_NAMES"
import sys, json, urllib.request, urllib.parse, base64, os

raw = sys.argv[1].strip()
if not raw:
    print("")
    sys.exit()

tag_names = [t for t in raw.split("|") if t.strip()]
auth = base64.b64encode(os.environ.get("WP_USER","kpop-bot").encode() + b":" + os.environ.get("WP_PASS","").encode()).decode()
headers = {"Authorization": "Basic " + auth, "Content-Type": "application/json"}
base_url = "https://www.kpopjournal.tokyo/wp-json/wp/v2/tags"
tag_ids = []

for name in tag_names:
    search_url = base_url + "?search=" + urllib.parse.quote(name) + "&per_page=5"
    req = urllib.request.Request(search_url, headers=headers)
    try:
        with urllib.request.urlopen(req) as res:
            data = json.loads(res.read())
        match = next((t for t in data if t["name"] == name), None)
        if match:
            tag_ids.append(str(match["id"]))
            continue
    except:
        pass
    req = urllib.request.Request(base_url,
        data=json.dumps({"name": name}).encode(),
        headers=headers)
    try:
        with urllib.request.urlopen(req) as res:
            tag = json.loads(res.read())
            tag_ids.append(str(tag["id"]))
    except:
        pass

print(",".join(tag_ids))
PY
)

echo "TAG_IDS=$TAG_IDS"

SLUG=$(python3 "$SCRIPT_DIR/lib/slug_generator.py" "$TITLE")
# スラッグ品質チェック: 数字始まり or 語が少なすぎる場合は警告・kpop-プレフィックス付与
if [[ "$SLUG" =~ ^[0-9] ]] || [[ "$(echo "$SLUG" | tr -cd '-' | wc -c)" -lt 2 ]]; then
  echo "  ⚠️ [slug_validator] 不良スラッグ検出: '$SLUG' → kpop-プレフィックス付与"
  SLUG="kpop-${SLUG}"
fi
echo "  slug: $SLUG"

DESC=$(echo "$CONTENT" | sed -e 's/<[^>]*>//g' | python3 -c "import sys; t=sys.stdin.read().strip(); print(t[:120])")

echo "$TITLE"   > /tmp/kpop_title.txt
echo "$CONTENT" > /tmp/kpop_content.txt
echo "$DESC"    > /tmp/kpop_desc.txt

JSON=$(python3 - << 'PY' "$SLUG" "$CATEGORY_ID" "$MEDIA_ID" "$ARTIST_CATEGORY_IDS" "$TAG_IDS" "$STATUS"
import json, sys

slug           = sys.argv[1]
main_category  = int(sys.argv[2])
media_id_raw   = sys.argv[3].strip()
media_id       = int(media_id_raw) if media_id_raw else 0
artist_ids_raw = sys.argv[4].strip()
tag_ids_raw    = sys.argv[5].strip()
status         = sys.argv[6].strip()

with open("/tmp/kpop_title.txt",   encoding='utf-8', errors='replace') as f: title   = f.read().strip()
with open("/tmp/kpop_content.txt", encoding='utf-8', errors='replace') as f: content = f.read().strip()
with open("/tmp/kpop_desc.txt",    encoding='utf-8', errors='replace') as f: desc    = f.read().strip()

categories = [main_category]
if artist_ids_raw:
    for x in artist_ids_raw.split(","):
        x = x.strip()
        if x:
            categories.append(int(x))
categories = list(dict.fromkeys(categories))

tags = []
if tag_ids_raw:
    for x in tag_ids_raw.split(","):
        x = x.strip()
        if x:
            tags.append(int(x))
tags = list(dict.fromkeys(tags))

print(json.dumps({
    'title': title,
    'content': content,
    'status': status,
    'slug': slug,
    'excerpt': desc,
    'categories': categories,
    'tags': tags,
    'featured_media': media_id
}, ensure_ascii=False))
PY
)

# トークン合計をエクスポート（post_to_wp.py のKPIログ用）
if [ "${ENABLE_TOKEN_TRACKING:-0}" = "1" ] && [ -f "$TOKEN_LOG" ]; then
  export PIPELINE_TOKEN_COUNT=$(token_total "$TOKEN_LOG")
  echo "  トークン合計: $PIPELINE_TOKEN_COUNT"
fi

# === Pre-Publish品質ゲート ===
echo "=== Pre-Publish品質ゲート ==="
if ! pre_publish_gate "$TITLE" "/tmp/kpop_content.txt" "${AIOSEO_DESC:-}" "$SLUG"; then
  echo "❌ Pre-Publishゲート失敗 → 投稿中止"
  archive_and_exit 1
fi

# === 投稿前バリデーション（再発防止の本丸） ===
echo "=== 投稿前バリデーション ==="
if ! echo "$JSON" | python3 "$SCRIPT_DIR/lib/validate_post.py"; then
  echo "❌ バリデーション失敗 → 投稿中止"
  archive_and_exit 1
fi

echo "=== ダークライ権利監査 ==="
if ! echo "$JSON" | python3 "$SCRIPT_DIR/lib/darkrai_audit.py"; then
  echo "❌ 権利監査失敗 → 投稿中止"
  archive_and_exit 1
fi

RESPONSE=$(curl -s -X POST https://www.kpopjournal.tokyo/wp-json/wp/v2/posts \
-K ~/.wp_auth \
-H "Content-Type: application/json" \
-d "$JSON")

echo "$RESPONSE"

POST_URL=$(echo "$RESPONSE" | python3 -c "import json,sys,os; d=json.load(sys.stdin); print(d.get('link','（URL取得失敗）'))" 2>/dev/null)
POST_ID=$(echo "$RESPONSE"  | python3 -c "import json,sys,os; d=json.load(sys.stdin); print(d.get('id',''))"  2>/dev/null)

if [[ -n "$POST_ID" && "$POST_ID" =~ ^[0-9]+$ ]]; then
  log_step "wordpress_post" "ok" "reports/final_post.md" "post_id=$POST_ID"
else
  log_step "wordpress_post" "error" "reports/final_post.md" "POST_ID empty or invalid"
fi

# === 視聴導線記事: 再監査台帳に追記 ===
if [[ -n "$POST_ID" && "$POST_ID" =~ ^[0-9]+$ && "$CATEGORY_ID" == "111" ]]; then
  echo "=== 視聴導線記事 再監査台帳追記 ==="
  python3 - << 'LEDGER_PY' "$POST_ID" "$TITLE" "$CATEGORY_ID"
import sys, json
from datetime import date, timedelta
from pathlib import Path

post_id = int(sys.argv[1])
title = sys.argv[2]
category_id = int(sys.argv[3])

BASE = Path("/home/aiuser/kpop-ai-system")
LEDGER = BASE / "logs" / "streaming_guide_review.jsonl"
today = date.today()

t = title.lower()
if any(k in t for k in ['kcon','mama','award','授賞式','イベント','開催']):
    article_type = "event_guide"
    interval = 14
elif any(k in t for k in ['music bank','inkigayo','m countdown','show champion','music core','人気歌謡']):
    article_type = "single_show_guide"
    interval = 60
elif any(k in t for k in ['まとめ','比較','一覧','総まとめ','全サービス']):
    article_type = "comprehensive_guide"
    interval = 30
else:
    article_type = "artist_streaming_guide"
    interval = 14

new_record = {
    "post_id": post_id,
    "title": title,
    "category_id": category_id,
    "article_type": article_type,
    "risk_level": "high" if interval <= 14 else ("medium" if interval <= 60 else "low"),
    "reason": f"パイプライン自動登録 ({today})",
    "review_rule": f"{article_type}: {interval}日後",
    "audit_focus": ["料金変動", "配信可否確認", "活動状況確認"],
    "last_factchecked_at": today.isoformat(),
    "next_review_due": (today + timedelta(days=interval)).isoformat(),
    "status": "published_verified",
}

records = []
if LEDGER.exists():
    with open(LEDGER) as f:
        for line in f:
            line = line.strip()
            if line:
                r = json.loads(line)
                if r["post_id"] != post_id:
                    records.append(r)
records.append(new_record)
with open(LEDGER, "w") as f:
    for r in records:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
print(f"  ✅ 再監査台帳追記: post_id={post_id} article_type={article_type} next_review={new_record['next_review_due']}")
LEDGER_PY
fi

# === [4.1] AIOSEO meta設定（再発防止: title/desc空防止） ===
if [[ -n "$POST_ID" && "$POST_ID" =~ ^[0-9]+$ ]]; then
  echo "=== [4.1] AIOSEO metaタイトル・説明設定 ==="
  # AIOSEOの内部メタキーはREST API非公開のため、
  # post_meta直書き用エンドポイント or wp-cli 経由で設定
  # → post_audit.shのAIOSEO設定ロジックを呼ぶ（再発防止の本丸）
  # meta_desc_copied 再発防止: 本文冒頭コピーではなくSEO独立文を生成
  AIOSEO_DESC=$(echo "$CONTENT" | sed -e 's/<[^>]*>//g' | python3 -c "
import sys, re
text = sys.stdin.read().strip()
text = re.sub(r'\s+', ' ', text)
sentences = re.split(r'[。！？]', text)
sentences = [s.strip() for s in sentences if len(s.strip()) >= 20]
# 2文目以降からキーワードを取得（冒頭コピー禁止）
mid = sentences[1] if len(sentences) > 1 else (sentences[0] if sentences else text[:60])
mid = mid[:60].rstrip('。！？')
title_short = re.sub(r'[【】「」『』\[\]]', '', sys.argv[1] if len(sys.argv) > 1 else '')[:20]
desc = f'{title_short}について解説。{mid}。K-POPファン必見の最新情報をお届けします。'
if len(desc) > 130:
    desc = desc[:127] + '...'
print(desc)
" \"$TITLE\" 2>/dev/null)
  curl -s -X POST "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/${POST_ID}" \
    -K ~/.wp_auth \
    -H "Content-Type: application/json" \
    -d "{\"meta\":{\"_aioseo_description\": \"$(echo "$AIOSEO_DESC" | sed 's/"/\\"/g')\"}}" > /dev/null 2>&1 \
    && echo "  ✅ AIOSEO description設定完了" || echo "  ⚠️ AIOSEO description設定スキップ"
fi

echo "=== [4.5] 収益導線自動挿入 ==="
bash $SCRIPT_DIR/google_metrics/inject_revenue_links.sh "$POST_ID" 2>&1 || echo "⚠️ 収益導線スキップ"
echo "=== [4.5.1] ABEMA CTA自動挿入 ==="
bash /home/aiuser/kpop-ai-system/google_metrics/inject_abema_cta.sh "$POST_ID" 2>&1 || echo "⚠️ ABEMA CTAスキップ"

echo "=== [4.5.2] CTA存在確認（必須） ==="
# カテゴリベースでCTAタイプを判定
CTA_TYPE=$(python3 -c "
import sys
cat_id = int('${CATEGORY_ID}' or '0')
title = '''${TITLE}'''
streaming_kw = ['配信', 'ストリーミング', 'MV', 'ABEMA', '番組', '放送', '生放送', 'ライブ配信', '独占', 'サバイバル', 'オーディション']
if any(kw in title for kw in streaming_kw):
    print('ABEMA')
elif cat_id == 12:
    print('COSMETICS')
elif cat_id in (11, 70):
    print('TRAVEL')
else:
    print('INTERNAL')
")
echo "CTA_TYPE=$CTA_TYPE (CATEGORY_ID=$CATEGORY_ID)"

# 投稿済み記事のコンテンツからCTA有無を確認
HAS_CTA_CHECK=$(curl -s "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/$POST_ID" \
  -K ~/.wp_auth | python3 -c "
import sys, json
data = json.load(sys.stdin)
content = data.get('content', {}).get('rendered', '')
has = 'revenue-cta' in content or 'cta-box' in content or 'abema-cta' in content or 'affiliate-link' in content
print('YES' if has else 'NO')
" 2>/dev/null)

if [ "$HAS_CTA_CHECK" != "YES" ]; then
  echo "CTA未挿入 → フォールバックCTA挿入 (type=$CTA_TYPE)"
  python3 - << 'FALLBACK_CTA_PY' "$POST_ID" "$CATEGORY_ID" "$CTA_TYPE"
import requests, json, sys, os, re as _re

post_id = sys.argv[1]
category_id = sys.argv[2] or "1"
cta_type = sys.argv[3]

_auth_header = ""
_wp_auth_path = os.path.expanduser("~/.wp_auth")
if os.path.exists(_wp_auth_path):
    with open(_wp_auth_path) as _f:
        for _line in _f:
            _m = _re.match(r'header\s*=\s*"(Authorization:\s*Basic\s+[^"\n]+)"?', _line.strip())
            if _m:
                _auth_header = _m.group(1)
                break
if not _auth_header:
    import base64
    _u = os.environ.get("WP_USER","kpop-bot")
    _p = os.environ.get("WP_PASS","")
    _auth_header = "Authorization: Basic " + base64.b64encode(f"{_u}:{_p}".encode()).decode()
_wp_headers = {"Authorization": _auth_header.split(": ", 1)[1]}
base_url = "https://www.kpopjournal.tokyo/wp-json/wp/v2"

# 現在の投稿コンテンツを取得
resp = requests.get(f"{base_url}/posts/{post_id}", headers=_wp_headers)
resp.raise_for_status()
post_data = resp.json()
current_content = post_data.get("content", {}).get("raw", post_data.get("content", {}).get("rendered", ""))

cta_html = ""

if cta_type == "ABEMA":
    cta_html = """
<div class="cta-box abema-cta" style="background:#1a1a2e;color:#fff;padding:20px;border-radius:8px;margin:24px 0;text-align:center;">
<p style="font-size:18px;font-weight:bold;margin-bottom:12px;">ABEMAで今すぐチェック！</p>
<p>K-POP番組・ライブ配信が充実のABEMAプレミアム</p>
<a href="https://abema.tv/" target="_blank" rel="noopener sponsored" style="display:inline-block;background:#ff0060;color:#fff;padding:12px 32px;border-radius:24px;text-decoration:none;font-weight:bold;margin-top:8px;">ABEMAプレミアムを見る</a>
</div>
"""
elif cta_type == "COSMETICS":
    cta_html = """
<div class="cta-box cosmetics-cta" style="background:#fff0f5;padding:20px;border-radius:8px;margin:24px 0;border:1px solid #ffb6c1;">
<p style="font-size:18px;font-weight:bold;margin-bottom:12px;">K-POPアイドル愛用コスメをチェック</p>
<p>韓国コスメの人気アイテムをお得にゲット！</p>
<a href="https://www.qoo10.jp/" target="_blank" rel="noopener sponsored" style="display:inline-block;background:#ff69b4;color:#fff;padding:12px 32px;border-radius:24px;text-decoration:none;font-weight:bold;margin-top:8px;">人気韓国コスメを見る</a>
</div>
"""
elif cta_type == "TRAVEL":
    cta_html = """
<div class="cta-box travel-cta" style="background:#f0f8ff;padding:20px;border-radius:8px;margin:24px 0;border:1px solid #87ceeb;">
<p style="font-size:18px;font-weight:bold;margin-bottom:12px;">韓国旅行をお得に予約</p>
<p>聖地巡礼・コンサート遠征に！ホテル・航空券を比較検索</p>
<a href="https://www.expedia.co.jp/" target="_blank" rel="noopener sponsored" style="display:inline-block;background:#1e90ff;color:#fff;padding:12px 32px;border-radius:24px;text-decoration:none;font-weight:bold;margin-top:8px;">韓国行きプランを探す</a>
</div>
"""
else:
    # デフォルト: あわせて読みたい（内部リンクCTA）
    try:
        recent = requests.get(
            f"{base_url}/posts",
            params={"categories": category_id, "per_page": 4, "exclude": post_id, "status": "publish"},
            headers=_wp_headers, timeout=10
        )
        recent.raise_for_status()
        articles = recent.json()[:3]
    except Exception:
        articles = []

    if articles:
        links_html = ""
        for art in articles:
            art_title = art.get("title", {}).get("rendered", "関連記事")
            art_url = art.get("link", "#")
            links_html += f'<li><a href="{art_url}">{art_title}</a></li>\n'
        cta_html = f"""
<div class="cta-box internal-link-cta" style="background:#f9f9f9;padding:20px;border-radius:8px;margin:24px 0;border-left:4px solid #7c3aed;">
<p style="font-size:18px;font-weight:bold;margin-bottom:12px;">あわせて読みたい</p>
<ul style="list-style:none;padding:0;">
{links_html}</ul>
</div>
"""
    else:
        cta_html = """
<div class="cta-box internal-link-cta" style="background:#f9f9f9;padding:20px;border-radius:8px;margin:24px 0;border-left:4px solid #7c3aed;">
<p style="font-size:18px;font-weight:bold;margin-bottom:12px;">あわせて読みたい</p>
<p>最新のK-POP情報は<a href="https://www.kpopjournal.tokyo/">トップページ</a>をチェック！</p>
</div>
"""

if cta_html:
    updated_content = current_content + cta_html
    update_resp = requests.post(
        f"{base_url}/posts/{post_id}",
        headers={**_wp_headers, "Content-Type": "application/json"},
        json={"content": updated_content},
        timeout=15
    )
    update_resp.raise_for_status()
    print(f"フォールバックCTA挿入完了 (type={cta_type})")
else:
    print("CTA HTMLの生成に失敗")
    sys.exit(1)
FALLBACK_CTA_PY
  if [ $? -ne 0 ]; then
    echo "フォールバックCTA挿入失敗"
  fi
else
  echo "CTA確認OK（既存CTA検出）"
fi

echo "=== [4.6] 内部リンク自動挿入 ==="
bash $SCRIPT_DIR/google_metrics/add_internal_links.sh "/$SLUG/" 2>&1 || echo "⚠️ 内部リンクスキップ"

echo "=== [4.7] Google Indexing API ==="
bash $SCRIPT_DIR/google_metrics/request_index.sh "$POST_URL" 2>&1 || echo "⚠️ Google インデックススキップ"

echo "=== [4.8] Bing URL Submission ==="
bash $SCRIPT_DIR/google_metrics/request_bing_index.sh "$POST_URL" 2>&1 || echo "⚠️ Bing インデックススキップ"

echo "=== [5] SNS投稿 (v12.0 シングル投稿モード) ==="

# ── [DRAFT GUARD 2重防衛] X投稿直前にWP側のstatus を再確認 ─────────────
# WP投稿後に何らかの理由でdraftになっていた場合のX拡散事故を防ぐ
_WP_STATUS_NOW=$(curl -s "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/${POST_ID}" \
  -K ~/.wp_auth 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('status','unknown'))" 2>/dev/null || echo "unknown")
if [[ "$_WP_STATUS_NOW" != "publish" ]]; then
  echo "⛔ [DRAFT GUARD] X投稿スキップ: WP status=${_WP_STATUS_NOW} (publish以外はX投稿禁止)"
  echo "  → POST_ID=$POST_ID が publish 状態でないためX投稿を中止"
  log_step "sns_draft_guard" "blocked" "" "X投稿スキップ: status=${_WP_STATUS_NOW}"
  X_STATUS="スキップ(DRAFT_GUARD: status=${_WP_STATUS_NOW})"
else

# v12.0: シングル投稿モード — 引数をファイル渡しで安全に処理（タイトル内のクォート破論防止）
_SNS_ARGS_FILE=$(mktemp /tmp/kpop_sns_args.XXXXXX.json)
python3 -c "import json,sys; json.dump({'title':sys.argv[1],'url':sys.argv[2],'category_id':sys.argv[3],'lib':sys.argv[4]}, open(sys.argv[5],'w'))" \
  "$TITLE" "$POST_URL" "$CATEGORY_ID" "$SCRIPT_DIR/lib" "$_SNS_ARGS_FILE" 2>/dev/null

SNS_TEXT=$(python3 - "$_SNS_ARGS_FILE" << 'PYEOF'
import json, sys
args = json.load(open(sys.argv[1]))
sys.path.insert(0, args['lib'])
from x_post_templates import generate_single, determine_target, CATEGORY_TO_GENRE
genre = CATEGORY_TO_GENRE.get(args['category_id'], 'default')
target = determine_target(args['title'], genre)
print(f"TARGET={target}", file=sys.stderr)
print(generate_single(args['title'], args['url'], genre))
PYEOF
) 2>/tmp/kpop_sns_target.tmp
_SNS_EXIT=$?
rm -f "$_SNS_ARGS_FILE"

if [ $_SNS_EXIT -ne 0 ] || [ -z "$SNS_TEXT" ] || [ ${#SNS_TEXT} -lt 20 ]; then
  SNS_TEXT="${TITLE}
${POST_URL}

#KPOP #韓国"
fi

echo "$SNS_TEXT" > reports/4_sns.md
# 互換性維持
cp reports/4_sns.md reports/4_sns_a.md

SNS_TARGET=$(grep "TARGET=" /tmp/kpop_sns_target.tmp 2>/dev/null | tail -1 | sed 's/TARGET=//' || echo "不明")
rm -f /tmp/kpop_sns_target.tmp
echo "  ターゲット: $SNS_TARGET"
echo "  投稿文(1行目): $(head -1 reports/4_sns.md)"

# pre_score を記録（SNS_TEXT をファイル経由で渡す）
_SNS_SCORE_FILE=$(mktemp)
echo "$SNS_TEXT" > "$_SNS_SCORE_FILE"
SNS_SCORE_JSON=$(python3 "$SCRIPT_DIR/lib/x_pre_score.py" "$(cat "$_SNS_SCORE_FILE")" 2>/dev/null || echo '{"total":0,"pass":false}')
rm -f "$_SNS_SCORE_FILE"
SNS_SCORE=$(python3 -c "import json,sys; print(json.loads(sys.argv[1]).get('total',0))" "$SNS_SCORE_JSON" 2>/dev/null || echo "0")
echo "  pre_score: $SNS_SCORE/100"

echo "=== [5.1] X/Twitter 自動投稿（シングル） ==="
X_POST_LOG="/home/aiuser/kpop-ai-system/logs/x_post.log"
X_POST_RESULT=$(bash "$SCRIPT_DIR/google_metrics/post_to_x.sh" "$TITLE" "$POST_URL" "reports/4_sns.md" 2>&1) || {
  echo "X投稿スキップ (エラーはログ参照: $X_POST_LOG)"
  X_POST_RESULT="X投稿失敗"
}
X_TWEET_URL=$(echo "$X_POST_RESULT" | grep -oP 'https://x\.com/\S+' | head -1 || true)
X_TWEET_ID=$(echo "$X_POST_RESULT" | grep -oP '^TWEET_ID=\K[0-9]+' | head -1 || true)
# Tweet IDをローカルDBとWordPress投稿メタに保存（記事削除時のX投稿削除に使用）
if [ -n "$X_TWEET_ID" ] && [ -n "$POST_ID" ]; then
  # ローカルファイルDB（確実な保存先）
  TWEET_DB="$SCRIPT_DIR/logs/tweet_id_db.tsv"
  echo -e "${POST_ID}\t${X_TWEET_ID}\t${TITLE}\t$(date +%Y-%m-%dT%H:%M:%S)" >> "$TWEET_DB"
  echo "  tweet_id=$X_TWEET_ID をローカルDB保存 ($TWEET_DB)"
  # WordPressメタにも保存（show_in_rest=true が設定されていれば取得可能）
  curl -s -X POST "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/$POST_ID" \
    -K ~/.wp_auth \
    -H "Content-Type: application/json" \
    -d "{\"meta\": {\"_x_tweet_id\": \"$X_TWEET_ID\"}}" > /dev/null 2>&1 || true
fi
if [ -n "$X_TWEET_URL" ]; then
  X_STATUS="成功 ($X_TWEET_URL)"
elif echo "$X_POST_RESULT" | grep -q "DRY-RUN"; then
  X_STATUS="DRY-RUN（テストモード）"
elif echo "$X_POST_RESULT" | grep -q "スキップ"; then
  X_STATUS="スキップ (pre_score=$SNS_SCORE/100)"
else
  X_STATUS="失敗"
fi
log_step "x_post" "$(echo "$X_STATUS" | grep -q '成功' && echo ok || echo skipped)" "reports/4_sns.md" "$X_STATUS (pre_score=$SNS_SCORE/100)"

# === X投稿監査ログ（x_post_audit.jsonl）───────────────────────────────────
{
  _xaudit_ts=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
  _xaudit_status=""
  if echo "$X_STATUS" | grep -q "成功"; then
    _xaudit_status="posted"
  elif echo "$X_STATUS" | grep -q "DRY-RUN"; then
    _xaudit_status="plan_only"
  elif echo "$X_STATUS" | grep -q "スキップ\|フェイルセーフ"; then
    _xaudit_status="skipped"
  elif echo "$X_STATUS" | grep -q "失敗"; then
    _xaudit_status="failed"
  else
    _xaudit_status="unknown"
  fi
  _xaudit_mode=$([ "${ENABLE_X_POST:-0}" = "1" ] && echo "live" || echo "dry_run")
  _xaudit_tweet_id=$(echo "$X_POST_RESULT" | grep -oP 'TWEET_ID=\K[0-9]+' | head -1 || echo "")
  _xaudit_tweet_url=$(echo "$X_POST_RESULT" | grep -oP 'https://x\.com/\S+' | head -1 || echo "")
  _xaudit_main_text=$(head -c 200 "reports/4_sns.md" 2>/dev/null | tr '\n' ' ' | sed 's/"/\\"/g' || echo "")
  python3 - << XAUDIT_PY "${POST_ID:-}" "${POST_URL:-}" "$_xaudit_status" "$_xaudit_tweet_id" "$_xaudit_tweet_url" "$_xaudit_mode" "$_xaudit_ts" "${SNS_SCORE:-0}"
import json, sys
from pathlib import Path

post_id   = sys.argv[1]
art_url   = sys.argv[2]
status    = sys.argv[3]
tweet_id  = sys.argv[4]
tweet_url = sys.argv[5]
mode      = sys.argv[6]
ts        = sys.argv[7]
score     = sys.argv[8]

main_text = ""
try:
    main_text = Path("reports/4_sns.md").read_text(errors="replace")[:300].replace("\n"," ")
except Exception:
    pass

issues = []
if not tweet_id and status == "posted":
    issues.append("tweet_id取得失敗")

rec = {
    "post_id": post_id,
    "article_url": art_url,
    "main_post_text": main_text,
    "reply_text": "",
    "tweet_status": status,
    "tweet_id": tweet_id,
    "tweet_url": tweet_url,
    "posted_at": ts,
    "mode": mode,
    "pre_score": float(score) if score else 0,
    "issues": issues,
}
out = Path("/home/aiuser/kpop-ai-system/logs/x_post_audit.jsonl")
with out.open("a", encoding="utf-8") as f:
    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
XAUDIT_PY
} 2>/dev/null || true

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# タイトル学習: pending で記録（実CTR取得後に win/lose 確定）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
python3 "$SCRIPT_DIR/lib/title_learner.py" record \
  --title "$TITLE" --score 0 --pattern "シングル" \
  --post-id "$POST_ID" --pending 2>/dev/null || true
echo "  ✓ タイトル学習データ記録完了（pending）"

# サムネ学習: メタ情報を pending で記録
if [[ -n "$THUMB_META_LINE" ]]; then
  python3 - "$POST_ID" "$THUMB_META_LINE" << 'PYEOF' 2>/dev/null || true
import sys, json, subprocess
post_id = sys.argv[1]
try:
    meta = json.loads(sys.argv[2])
except Exception:
    sys.exit(0)
cmd = [
    "python3", "/home/aiuser/kpop-ai-system/lib/thumbnail_learner.py", "record",
    "--post-id", post_id,
    "--thumb-text", meta.get("thumb_text",""),
    "--genre", meta.get("genre",""),
    "--layout", meta.get("layout","v2"),
    "--has-image", "true" if meta.get("has_image") else "false",
    "--eng-hero", meta.get("eng_hero",""),
    "--image-source", meta.get("image_source",""),
]
subprocess.run(cmd, check=False)
PYEOF
  echo "  ✓ サムネ学習データ記録完了（pending）"
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# レジギガス: 実行履歴アーカイブ
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
mkdir -p "$ARCHIVE_DIR"
cp reports/* "$ARCHIVE_DIR/" 2>/dev/null
cat > "$ARCHIVE_DIR/summary.txt" << SUMMARY
実行ID      : $RUN_ID
パイプライン: speed
日時        : $TODAY
記事ID      : $POST_ID
URL         : $POST_URL
タイトルA   : $TITLE
タイトルB   : $TITLE_B
文字数      : $CONTENT_LENGTH
判定        : 投稿OK
X投稿A      : $X_STATUS
X投稿B      : dry-run保存（reports/4_sns_b.md）
SUMMARY

bash $SCRIPT_DIR/kpop_notify.sh success "速報" "記事投稿完了: $TITLE" "$POST_URL" 2>/dev/null

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# KPIログ記録（v1.2 Phase 4 #21）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PIPELINE_END=$(date +%s)
PROCESSING_TIME=$((PIPELINE_END - ${PIPELINE_START:-$PIPELINE_END}))
# CTA存在を実際の投稿済みコンテンツから確認（ローカル変数$CONTENTではなくWP APIから取得）
HAS_CTA="false"
FINAL_CONTENT_CHECK=$(curl -s "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/$POST_ID" \
  -K ~/.wp_auth | python3 -c "
import sys, json
data = json.load(sys.stdin)
content = data.get('content', {}).get('rendered', '')
has = 'cta-box' in content or 'revenue-cta' in content or 'abema-cta' in content or 'affiliate-link' in content or 'internal-link-cta' in content or 'px.a8.net' in content or 'amazon.co.jp' in content
print('true' if has else 'false')
" 2>/dev/null)
HAS_CTA="${FINAL_CONTENT_CHECK:-false}"
echo "HAS_CTA=$HAS_CTA (実投稿コンテンツ確認)"

# アルセウスの採点結果から50点満点スコアを抽出
ARCEUS_SCORE=$(python3 - << 'SCORE_PY' "reports/3_arceus.md"
import re, sys
score = 0
try:
    with open(sys.argv[1], encoding="utf-8") as f:
        text = f.read()
    # 方法1: 総合スコア行から抽出 (例: "総合スコア: 9.0/10") → x5で50点満点に換算
    m = re.search(r'総合スコア[：:]\s*([\d.]+)\s*/\s*10', text)
    if m:
        score = round(float(m.group(1)) * 5)
    else:
        # 方法2: エージェント別採点表の個別スコアを合算 (例: "| エージェント名 | **9.5/10** |")
        # 採点表の行のみを対象にし、本文中の無関係な "X/10" を拾わないようにする
        scores = re.findall(r'\|\s*\*{0,2}([\d.]+)\s*/\s*10\*{0,2}\s*\|', text)
        if not scores:
            # フォールバック: 太字で囲まれたスコアのみ (例: "**9.5/10**")
            scores = re.findall(r'\*\*([\d.]+)\s*/\s*10\*\*', text)
        if scores:
            total = sum(float(s) for s in scores)
            score = round(min(total, 50))
except Exception:
    pass
# 0-50の範囲に収める
print(max(0, min(50, score)))
SCORE_PY
)
ARCEUS_SCORE=${ARCEUS_SCORE:-0}
echo "ARCEUS_SCORE=$ARCEUS_SCORE"

# KPIログ: JSONをPythonで安全に構築（タイトル等の特殊文字でJSON破損を防止）
python3 - << 'KPI_PY' "$SCRIPT_DIR/lib/kpi_logger.py" "$POST_ID" "$TITLE" "$POST_URL" "$SLUG" "$CATEGORY_ID" "$PLAIN_CHARS" "$H2_COUNT" "$ARCEUS_SCORE" "$HAS_CTA" "${PIPELINE_TOKEN_COUNT:-0}" "$PROCESSING_TIME" "${SNS_SCORE:-0}" "${X_STATUS:-}"
import json, sys, importlib.util

logger_path, post_id, title, url, slug = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]
category_id, plain_chars, h2_count = sys.argv[6], sys.argv[7], sys.argv[8]
arceus_score, has_cta, token_count, proc_time = sys.argv[9], sys.argv[10], sys.argv[11], sys.argv[12]
x_pre_score_val = sys.argv[13] if len(sys.argv) > 13 else "0"
x_status_val = sys.argv[14] if len(sys.argv) > 14 else ""

def safe_int(v, default=0):
    try: return int(float(v))
    except: return default

def safe_bool(v):
    return v.lower() == "true"

def detect_article_type(cat_id):
    cat_id = safe_int(cat_id)
    if cat_id == 12:
        return "beauty"
    elif cat_id in (11, 70):
        return "travel"
    else:
        return "flow"

data = {
    "post_id": post_id,
    "title": title,
    "url": url,
    "slug": slug,
    "article_type": detect_article_type(category_id),
    "categories": [safe_int(category_id)],
    "char_count": safe_int(plain_chars),
    "h2_count": safe_int(h2_count),
    "score": safe_int(arceus_score),
    "pipeline": "speed",
    "has_cta": safe_bool(has_cta),
    "has_thumbnail": True,
    "token_count": safe_int(token_count),
    "processing_time_sec": safe_int(proc_time),
    "x_pre_score": safe_int(x_pre_score_val),
    "x_post_status": x_status_val,
}

spec = importlib.util.spec_from_file_location("kpi_logger", logger_path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
result = mod.log_post(data)
print(json.dumps(result, ensure_ascii=False))
KPI_PY
if [ $? -ne 0 ]; then
  echo "KPIログ記録スキップ"
fi

fi  # end DRAFT GUARD 2 else block

cleanup_reports_dir

echo ""
echo "========================================"
echo " ✅ 完了"
echo " 記事ID  : $POST_ID"
echo " URL     : $POST_URL"
echo " SNS戦略 : (archived) $ARCHIVE_DIR/4_sns.md"
echo " アーカイブ: $ARCHIVE_DIR"
echo "========================================"

# ─── 投稿後自動監査 ────────────────────────────────────────────────────────
echo ""
echo "=== 投稿後自動監査 ==="
if [[ -n "$POST_ID" ]] && [[ -n "$POST_URL" ]]; then
  env -u AUDIT_LOOP_COUNT bash "$SCRIPT_DIR/post_audit.sh" "$POST_ID" "$POST_URL" "$TITLE" "$RUN_ID" 2>&1 || true
else
  echo "  ⚠️ POST_IDまたはPOST_URLが未設定 → 監査スキップ"
fi
