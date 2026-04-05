#!/bin/bash
# ============================================================
# agent_council.sh - 完全体 エージェント合議・意思決定システム v2
#
# 案A + 案B + 案C 統合フロー:
#   [Phase 0] WordPress接続確認
#   [Phase 1] deoxys 記事生成（差し戻しフィードバック対応・最大3回リトライ）
#   [Phase 2] lapras + mimikyu + meowth 並列合議 → スコア集計
#   [Phase 3] gengar 批判 → deoxys 反論・改善（最大2ラウンド）
#             ※ 合議平均 ≥ 8.0 の場合はスキップ
#   [Phase 4] arceus 全証拠を読んで最終裁定（GO/NO_GO）
#             NO_GO → フィードバック付きで Phase 1 へ差し戻し
#   [Phase 5] mewtwo CEO最終承認
#   [Phase 6] 品質ゲート（NGワード・文字数・見出し数）
#   [Phase 7] CTR採点 → サムネ生成 → WordPress投稿
#   [Phase 8] SNS戦略 → アーカイブ → Discord通知
# ============================================================
set -euo pipefail

BASE="$HOME/ai_company"
RUN_ID=$(date '+%Y%m%d_%H%M%S')
REPORTS="$BASE/council_reports/${RUN_ID}"
ARCHIVE_DIR="$HOME/kpop_archives/${RUN_ID}"
WEBHOOK=$(cat ~/.kpop_discord_webhook 2>/dev/null | tr -d '[:space:]' || echo "")
MAX_GEN_RETRIES=3
MAX_DEBATE_ROUNDS=2
TODAY=$(date '+%Y年%m月%d日')
START_TIME=$(date +%s)

mkdir -p "$REPORTS"

# ============================================================
# ユーティリティ
# ============================================================
log() { echo "[$(date '+%H:%M:%S')] $*"; }

elapsed() {
  local now=$(date +%s)
  local diff=$((now - START_TIME))
  local min=$((diff / 60))
  local sec=$((diff % 60))
  echo "${min}分${sec}秒"
}

phase_timer_start() { PHASE_START=$(date +%s); }
phase_timer_end() {
  local now=$(date +%s)
  local diff=$((now - PHASE_START))
  log "  ⏱ Phase所要時間: ${diff}秒"
}

discord() {
  local msg="$1"
  [ -z "$WEBHOOK" ] && return
  python3 -c "
import requests, sys
requests.post(sys.argv[1], json={'content': sys.argv[2][:1900]}, timeout=10)
" "$WEBHOOK" "$msg" 2>/dev/null || true
}

check_output() {
  local file="$1"
  local step="$2"
  if [[ ! -s "$file" ]]; then
    log "❌ [$step] 出力が空 → 停止"
    return 1
  fi
  if grep -qE '申し訳ありません|お手伝いできますか' "$file"; then
    log "❌ [$step] エラー応答を検出 → 停止"
    return 1
  fi
  log "  ✓ [$step] OK"
}

archive_and_exit() {
  local code="${1:-1}"
  mkdir -p "$ARCHIVE_DIR"
  cp "$REPORTS"/* "$ARCHIVE_DIR/" 2>/dev/null || true
  cat > "$ARCHIVE_DIR/summary.txt" << SUMMARY
実行ID      : $RUN_ID
パイプライン: council
日時        : $TODAY
経過時間    : $(elapsed)
判定        : $([ "$code" -eq 0 ] && echo "投稿OK" || echo "停止")
SUMMARY
  log "アーカイブ保存: $ARCHIVE_DIR"
  bash ~/kpop_notify.sh error "合議" "パイプライン停止 (RUN: $RUN_ID)" 2>/dev/null || true
  exit "$code"
}

# ============================================================
# Phase 0: WordPress接続確認
# ============================================================
phase0_wp_check() {
  log "Phase 0: WordPress接続確認"
  phase_timer_start

  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
    "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts?per_page=1" \
    -u "$WP_USER:$WP_PASS" \
    --connect-timeout 10 --max-time 15)

  if [[ "$HTTP_CODE" != "200" ]]; then
    log "❌ WordPress API 接続失敗 (HTTP ${HTTP_CODE})"
    discord "❌ 合議システム: WordPress API 接続失敗"
    exit 1
  fi
  log "  ✓ WordPress API 正常 (HTTP ${HTTP_CODE})"
  phase_timer_end
}

# ============================================================
# Phase 1: 記事生成（差し戻しフィードバック対応）
# ============================================================
phase1_generate() {
  local attempt="$1"
  local feedback="$2"

  log "Phase 1: 記事生成 試行${attempt}/${MAX_GEN_RETRIES}"
  phase_timer_start

  local feedback_block=""
  if [ -n "$feedback" ]; then
    feedback_block="
【前回の却下理由・改善指示】
${feedback}

上記の指摘を必ず全て反映して改善した記事を生成せよ。"
  fi

  claude --dangerously-skip-permissions --agent deoxys_kpop -p "
今日は${TODAY}です。K-POP速報記事を生成せよ。
${feedback_block}

【出力形式・絶対厳守】
1行目：タイトル文字列のみ
2行目：空行
3行目以降：<h2>から始まるHTML本文のみ
末尾に情報元と「※本記事は${TODAY}時点の情報です」を明記
" > "$REPORTS/draft_${attempt}.md"

  local size=$(wc -c < "$REPORTS/draft_${attempt}.md")
  log "  → 生成完了: ${size} bytes"
  check_output "$REPORTS/draft_${attempt}.md" "deoxys 試行${attempt}"

  # eevee タイトルA/B選定
  log "  eevee: タイトルA/B選定..."
  local draft_content_eevee
  draft_content_eevee=$(cat "$REPORTS/draft_${attempt}.md")
  claude --dangerously-skip-permissions --agent eevee -p "
以下の記事のタイトルを複数パターンで比較・評価し、最もCTRが高いタイトルを選定せよ。

【絶対ルール】
- 📄最終出力セクションのみ出力（比較表は内部で検討するだけ）
- 1行目：採用タイトルのみ
- 2行目：空行
- 3行目以降：記事本文そのまま（変更なし）

---
${draft_content_eevee}
" > "$REPORTS/draft_${attempt}_eevee.md" 2>/dev/null

  if [ -s "$REPORTS/draft_${attempt}_eevee.md" ]; then
    cp "$REPORTS/draft_${attempt}_eevee.md" "$REPORTS/draft_${attempt}.md"
    log "  ✓ eeveeタイトル選定完了"
  else
    log "  ⚠ eeveeスキップ（元タイトル維持）"
  fi

  phase_timer_end
}

# ============================================================
# Phase 2: 合議評価（3エージェント並列）
# ============================================================
phase2_council() {
  local draft="$1"
  log "Phase 2: 合議評価（lapras + mimikyu + meowth 並列実行）"
  phase_timer_start

  local draft_content
  draft_content=$(cat "$draft")

  claude --dangerously-skip-permissions --agent lapras -p "
SEO責任者として以下の記事を厳格に評価せよ。

${draft_content}

出力形式（必須・この形式以外禁止）:
【SEOスコア】X/10
【良い点】
-
【問題点】
-
【改善提案】
-
" > "$REPORTS/council_lapras.md" &
  PID_LAPRAS=$!

  claude --dangerously-skip-permissions --agent mimikyu -p "
競合分析責任者として以下の記事を厳格に評価せよ。

${draft_content}

出力形式（必須・この形式以外禁止）:
【競合スコア】X/10
【良い点】
-
【問題点】
-
【改善提案】
-
" > "$REPORTS/council_mimikyu.md" &
  PID_MIMIKYU=$!

  claude --dangerously-skip-permissions --agent meowth -p "
収益化責任者として以下の記事を厳格に評価せよ。

${draft_content}

出力形式（必須・この形式以外禁止）:
【収益スコア】X/10
【良い点】
-
【問題点】
-
【改善提案】
-
" > "$REPORTS/council_meowth.md" &
  PID_MEOWTH=$!

  # 並列待機
  wait $PID_LAPRAS  && log "  ✓ lapras完了"  || log "  ⚠ lapras失敗"
  wait $PID_MIMIKYU && log "  ✓ mimikyu完了" || log "  ⚠ mimikyu失敗"
  wait $PID_MEOWTH  && log "  ✓ meowth完了"  || log "  ⚠ meowth失敗"

  # スコア集計・判定
  python3 - "$REPORTS" << 'PY'
import re, sys
from pathlib import Path

reports = Path(sys.argv[1])
total = 0
count = 0
all_issues = []

for fname, label, key in [
    ("council_lapras.md",  "SEO",  "SEOスコア"),
    ("council_mimikyu.md", "競合", "競合スコア"),
    ("council_meowth.md",  "収益", "収益スコア"),
]:
    try:
        text = (reports / fname).read_text()
        m = re.search(r'【' + key + r'】\s*(\d+)', text)
        score = int(m.group(1)) if m else 5
        total += score
        count += 1
        print(f"  {label}: {score}/10")
        m2 = re.search(r'【問題点】(.*?)(?=【|\Z)', text, re.DOTALL)
        if m2:
            issues = m2.group(1).strip()
            if issues and issues != "-":
                all_issues.append(f"[{label}] {issues}")
    except Exception as e:
        print(f"  {label}: 読み込み失敗 ({e})")

avg = total / count if count > 0 else 0
print(f"\n  合議平均スコア: {avg:.1f}/10")

summary = f"avg:{avg:.1f}\n" + "\n".join(all_issues)
(reports / "council_summary.txt").write_text(summary)

# 判定結果を別ファイルに保存（シェルから読み取り用）
(reports / "council_avg.txt").write_text(f"{avg:.1f}")
verdict = "COUNCIL_GO" if avg >= 6.0 else "COUNCIL_NO_GO"
(reports / "council_verdict.txt").write_text(verdict)
print(f"\n  判定: {verdict}")
PY

  phase_timer_end
}

# ============================================================
# Phase 3: ディベート（gengar批判 → deoxys反論・改善）
# ============================================================
phase3_debate() {
  local draft="$1"
  local round="$2"
  log "Phase 3: ディベート Round ${round}/${MAX_DEBATE_ROUNDS}"
  phase_timer_start

  local draft_content
  draft_content=$(cat "$draft")

  local council_lapras council_mimikyu council_meowth
  council_lapras=$(cat "$REPORTS/council_lapras.md" 2>/dev/null || echo "なし")
  council_mimikyu=$(cat "$REPORTS/council_mimikyu.md" 2>/dev/null || echo "なし")
  council_meowth=$(cat "$REPORTS/council_meowth.md" 2>/dev/null || echo "なし")

  log "  gengar: 批判・問題点指摘..."
  claude --dangerously-skip-permissions --agent gengar -p "
SEO・品質監査担当として、以下の記事の欠陥を厳しく指摘せよ。
「このままでは投稿不可」という前提で批判せよ。

【記事】
${draft_content}

【合議評価（参考）】
${council_lapras}
${council_mimikyu}
${council_meowth}

出力形式：
【批判1】（SEO上の欠陥）
【批判2】（事実・信頼性上の欠陥）
【批判3】（読者体験上の欠陥）
【最低限の修正要件】
" > "$REPORTS/debate_gengar_r${round}.md"
  log "  ✓ gengar批判完了"

  local gengar_criticism
  gengar_criticism=$(cat "$REPORTS/debate_gengar_r${round}.md")

  log "  deoxys: 反論・改善記事生成..."
  claude --dangerously-skip-permissions --agent deoxys_kpop -p "
gengarの批判を受け止め、全項目に反論または改善した完成記事を出力せよ。
説明・前置き禁止。完成記事のみ出力。

【元記事】
${draft_content}

【gengarの批判 Round${round}】
${gengar_criticism}

【出力形式・絶対厳守】
1行目：タイトルのみ
2行目：空行
3行目以降：改善済みHTML本文のみ
末尾に情報元と「※本記事は${TODAY}時点の情報です」を明記
" > "$REPORTS/debate_deoxys_r${round}.md"
  log "  ✓ deoxys改善完了"

  phase_timer_end
  echo "$REPORTS/debate_deoxys_r${round}.md"
}

# ============================================================
# Phase 4: arceus 全証拠読んで最終裁定
# ============================================================
phase4_arceus() {
  local draft="$1"
  log "Phase 4: arceus 最終裁定"
  phase_timer_start

  local draft_content
  draft_content=$(cat "$draft")

  # ディベート記録を結合
  local debate_log
  debate_log=$(cat "$REPORTS"/debate_gengar_r*.md "$REPORTS"/debate_deoxys_r*.md 2>/dev/null || echo "ディベートなし")

  local council_summary
  council_summary=$(cat "$REPORTS/council_summary.txt" 2>/dev/null || echo "なし")

  claude --dangerously-skip-permissions --agent arceus -p "
編集長として、全証拠を精読し最終判定を下せ。
判定基準は厳しく。GO は「このまま投稿して問題ない」場合のみ。

【最終記事】
${draft_content}

【合議評価サマリー】
${council_summary}

【ディベート記録】
${debate_log}

【判定基準】
- タイトルが明確でクリックしたくなるか
- 本文800文字以上（純テキスト）
- h2見出しが2つ以上
- 事実・時制に問題なし
- 情報元の記載あり
- AI定型文・コードブロックの混入なし

出力形式（必須）:
【最終判定】GO
または
【最終判定】NO_GO
【判定理由】
【NO_GO時の差し戻し指示】（GO時は省略可）
" > "$REPORTS/arceus_verdict.md"

  local verdict
  verdict=$(grep -o "【最終判定】GO\|【最終判定】NO_GO" "$REPORTS/arceus_verdict.md" | head -1 | grep -o "GO\|NO_GO" || echo "NO_GO")
  log "  arceus裁定: ${verdict}"
  phase_timer_end
  echo "${verdict}"
}

# ============================================================
# Phase 5: mewtwo CEO最終承認
# ============================================================
phase5_mewtwo() {
  local final_article="$1"
  log "Phase 5: mewtwo CEO最終承認"
  phase_timer_start

  local article_content
  article_content=$(cat "$final_article")

  local council_summary arceus_verdict
  council_summary=$(cat "$REPORTS/council_summary.txt" 2>/dev/null || echo "なし")
  arceus_verdict=$(cat "$REPORTS/arceus_verdict.md")

  claude --dangerously-skip-permissions --agent mewtwo -p "
CEO・編集長として最終承認を行え。

【最終記事】
${article_content}

【合議結果】
${council_summary}

【arceus裁定】
${arceus_verdict}

出力形式：
【CEO判断】承認 または 却下
【総合評価コメント】
【投稿後の改善指示】
【次回生成への学習事項】
" > "$REPORTS/mewtwo_final.md"

  cat "$REPORTS/mewtwo_final.md"
  phase_timer_end

  if grep -q "承認" "$REPORTS/mewtwo_final.md"; then
    echo "CEO_APPROVED"
  else
    echo "CEO_REJECTED"
  fi
}

# ============================================================
# Phase 6: 品質ゲート
# ============================================================
phase6_quality_gate() {
  local article="$1"
  log "Phase 6: 品質ゲート"
  phase_timer_start

  TITLE=$(head -n 1 "$article")
  CONTENT=$(tail -n +3 "$article")

  # タイトル空チェック
  if [[ -z "$TITLE" ]]; then
    log "❌ 品質NG: タイトルが空"
    archive_and_exit 1
  fi

  # タイトルNGワード
  TITLE_NG_RESULT=$(python3 - "$TITLE" << 'PY'
import sys
t = sys.argv[1]
ng_words = [
    "お手伝いできますか", "申し訳ありません", "承知しました", "以下に",
    "まとめました", "解説します", "ご質問", "サポート",
    "AIとして", "言語モデル", "できません", "お答えできません",
    "修正箇所", "修正サマリー", "##",
]
hit = [w for w in ng_words if w in t]
if t.startswith("#") or "```" in t:
    hit.append("markdown記法")
print("|".join(hit) if hit else "OK")
PY
  )
  if [[ "$TITLE_NG_RESULT" != "OK" ]]; then
    log "❌ 品質NG: タイトルにNGワード（$TITLE_NG_RESULT）"
    archive_and_exit 1
  fi

  # タイトル文字数
  TITLE_LEN=${#TITLE}
  if [ "$TITLE_LEN" -lt 20 ]; then
    log "❌ 品質NG: タイトルが短すぎる（${TITLE_LEN}文字）"
    archive_and_exit 1
  fi
  if [ "$TITLE_LEN" -gt 60 ]; then
    log "⚠️  警告: タイトルが長い（${TITLE_LEN}文字）→ 続行"
  fi
  log "  ✓ タイトル文字数OK（${TITLE_LEN}文字）"

  # 本文空チェック
  if [[ -z "$CONTENT" ]]; then
    log "❌ 品質NG: 本文が空"
    archive_and_exit 1
  fi

  # 本文NGワード
  CONTENT_NG_RESULT=$(python3 - "$CONTENT" << 'PY'
import sys
c = sys.argv[1]
ng_words = [
    "申し訳ありません", "お手伝いできますか", "承知しました",
    "以下に示します", "AIとして", "言語モデル", "お答えできません",
    "修正箇所：", "修正サマリー", "チェック項目：", "【修正内容】", "申し訳",
]
hit = [w for w in ng_words if w in c]
if "```" in c:
    hit.append("codeblock混入")
print("|".join(hit) if hit else "OK")
PY
  )
  if [[ "$CONTENT_NG_RESULT" != "OK" ]]; then
    log "❌ 品質NG: 本文にNGワード（$CONTENT_NG_RESULT）"
    archive_and_exit 1
  fi

  # 実文字数・構造チェック
  CONTENT_STATS=$(python3 - "$CONTENT" << 'PY'
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

  log "  純テキスト: ${PLAIN_CHARS}文字 / h2:${H2_COUNT} / h3:${H3_COUNT} / p:${P_COUNT} / 情報元:${HAS_SOURCE}"

  if [ "$PLAIN_CHARS" -lt 800 ]; then
    log "❌ 品質NG: 純テキストが短すぎる（${PLAIN_CHARS}文字）"
    archive_and_exit 1
  fi
  if [ "$H2_COUNT" -lt 2 ]; then
    log "❌ 品質NG: h2見出しが少ない（${H2_COUNT}個）"
    archive_and_exit 1
  fi
  if [[ "$HAS_SOURCE" == "NO" ]]; then
    log "⚠️  警告: 情報元の記載なし → 続行"
  fi

  log "✅ 品質ゲート通過（${PLAIN_CHARS}文字 / h2:${H2_COUNT}）"
  phase_timer_end
}

# ============================================================
# Phase 7: 重複チェック → CTR採点 → サムネ → WordPress投稿
# ============================================================
phase7_publish() {
  local article="$1"
  log "Phase 7: 投稿準備・実行"
  phase_timer_start

  TITLE=$(head -n 1 "$article")
  CONTENT=$(tail -n +3 "$article")
  TITLE="【速報】${TITLE}"

  # --- 重複チェック ---
  log "  重複投稿チェック（過去2日）..."
  local days=2
  RECENT_TITLES=$(python3 - "$days" << 'PYEOF'
import sys, json, urllib.request, base64, urllib.parse
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

  if [[ -n "$RECENT_TITLES" ]]; then
    log "  直近${days}日の投稿: $(echo "$RECENT_TITLES" | grep -c . || echo 0)件"
    SIMILARITY=$(claude -p "
【タスク】類似記事重複チェック
新しく投稿しようとしている記事タイトルが、過去${days}日間の投稿済みタイトルと内容が重複しているか判定せよ。
【新タイトル】${TITLE}
【過去${days}日間の投稿済みタイトル】
${RECENT_TITLES}
【判定基準】
- 同じアーティスト＋同じイベント＋同じ時期 → 重複（YES）
- 同じアーティストでも別イベント・別テーマ → 重複なし（NO）
- チャートランキングは毎週異なるため常に重複なし（NO）
【出力ルール】YESまたはNOの1単語のみ。他は出力禁止。
")
    if [[ "$SIMILARITY" == "YES" ]]; then
      log "  ⚠️  重複あり → 投稿スキップ"
      discord "⚠️ 合議: 重複検出 → 投稿スキップ"
      archive_and_exit 0
    fi
    log "  ✓ 重複なし"
  else
    log "  ⚠️  投稿履歴取得失敗 → チェックスキップ"
  fi

  # --- CTRタイトル採点 ---
  log "  CTRタイトル採点..."
  TITLE_SCORE_JSON=$(python3 ~/google_metrics/score_title_ctr.py "$TITLE" 2>/dev/null || echo '{"pass": true, "score": 0}')
  echo "  $TITLE_SCORE_JSON"

  TITLE_PASS=$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); print('YES' if d.get('pass') else 'NO')" "$TITLE_SCORE_JSON" 2>/dev/null || echo "YES")
  TITLE_SCORE=$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); print(d.get('score', 0))" "$TITLE_SCORE_JSON" 2>/dev/null || echo "0")

  if [ "$TITLE_PASS" != "YES" ]; then
    log "❌ CTR NG: タイトルが弱い → 投稿停止"
    archive_and_exit 1
  fi
  log "  ✓ CTRスコア: ${TITLE_SCORE}"

  # --- サムネ文言生成 ---
  log "  サムネ文言生成..."
  THUMB_TITLE=$(claude -p "
あなたはK-POPニュースのサムネイルCTR改善担当です。
以下のタイトルに対して、サムネイル用の短い訴求文言を1つだけ作ってください。
【ルール】
・4〜14文字・短く強く・クリックしたくなる言葉
・本文タイトルのコピペ禁止・説明禁止・1行だけ出力
タイトル：$TITLE
" | tail -n 1)
  log "  サムネ文言: $THUMB_TITLE"

  # サムネ採点
  THUMB_SCORE_JSON=$(python3 ~/google_metrics/score_thumbnail_text.py "$THUMB_TITLE" 2>/dev/null || echo '{"pass": true, "score": 0}')
  THUMB_PASS=$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); print('YES' if d.get('pass') else 'NO')" "$THUMB_SCORE_JSON" 2>/dev/null || echo "YES")
  if [ "$THUMB_PASS" != "YES" ]; then
    log "  ⚠ サムネ文言NG → デフォルト文言に切替"
    THUMB_TITLE="緊急発表"
  fi

  # --- サムネ生成・アップロード ---
  log "  アイキャッチ生成..."
  python3 ~/make_thumbnail.py "$THUMB_TITLE" --genre breaking --title "$TITLE" 2>/dev/null || log "  ⚠ サムネ生成スキップ"

  MEDIA_ID=""
  if [ -f thumbnail.jpg ]; then
    log "  アイキャッチアップロード..."
    MEDIA_RESPONSE=$(curl -s -X POST https://www.kpopjournal.tokyo/wp-json/wp/v2/media \
      -u "$WP_USER:$WP_PASS" \
      -H "Content-Disposition: attachment; filename=thumbnail.jpg" \
      -H "Content-Type: image/jpeg" \
      --data-binary @thumbnail.jpg)
    MEDIA_ID=$(echo "$MEDIA_RESPONSE" | python3 -c "import json,sys; print(json.load(sys.stdin).get('id',''))" 2>/dev/null || echo "")
    log "  メディアID: $MEDIA_ID"
  fi

  # --- カテゴリ自動判定 ---
  CATEGORY_ID=$(python3 - "$TITLE" << 'PY'
import sys
title = sys.argv[1].lower()
rules = [
    (71, ['チャート','ランキング','1位','top10','top 10','billboard','spotify']),
    (3,  ['カムバック','カムバ','復帰','新アルバム','ミニアルバム']),
    (6,  ['新曲','mv公開','ミュージックビデオ','配信開始','音源公開']),
    (5,  ['ライブ','コンサート','ツアー','来日','ファンミ','チケット']),
    (7,  ['出演','出演決定','テレビ','番組','ラジオ']),
    (28, ['音楽番組','人気歌謡','music bank','m countdown']),
    (8,  ['ドラマ','主演','俳優','女優']),
    (27, ['映画','映画出演']),
    (10, ['コラボ','feat','featuring','ユニット']),
    (15, ['広告','アンバサダー','モデル起用','cm']),
    (13, ['新商品','発売','限定発売','グッズ']),
    (12, ['美容','コスメ','スキンケア','韓国コスメ']),
    (11, ['旅行','ソウル','釜山','渡韓']),
    (14, ['熱愛','炎上','騒動','脱退','訴訟']),
    (9,  ['話題','注目','バズ','拡散','海外の反応']),
    (4,  ['考察','分析','比較','解説','特集']),
]
for cid, keywords in rules:
    if any(word in title for word in keywords):
        print(cid); sys.exit()
print(2)
PY
  )

  # --- アーティスト別カテゴリ ---
  ARTIST_CATEGORY_IDS=$(python3 - "$TITLE" << 'PY'
import sys
title = sys.argv[1].lower()
artist_rules = [
    (19, ['bigbang','g-dragon','gd','taeyang','daesung']),
    (23, ['blackpink','jennie','jisoo','rose','rosé','lisa']),
    (18, ['bts','rm','jin','suga','j-hope','jimin','v','jungkook']),
    (25, ['aespa','karina','winter','ningning','giselle']),
    (38, ['babymonster','ahyeon','ruka','pharita','rami','rora']),
    (44, ['illit','iroha','wonhee','minju','moka','yunah']),
    (68, ['ive','wonyoung','yujin','rei','gaeul','liz','leeseo']),
    (41, ['le sserafim','lesserafim','sakura','chaewon','yunjin','kazuha','eunchae']),
    (40, ['nct','nct wish','mark','haechan','taeyong','jaehyun','doyoung']),
    (32, ['newjeans','minji','hani','danielle','haerin','hyein']),
    (39, ['riize','shotaro','sungchan','wonbin','sohee','anton','eunseok']),
    (24, ['seventeen','svt','scoups','jeonghan','joshua','hoshi','wonwoo','woozi','mingyu']),
    (43, ['stray kids','skz','bang chan','hyunjin','felix','han']),
    (22, ['twice','nayeon','momo','sana','jihyo','mina','dahyun','tzuyu']),
    (42, ['zerobaseone','zb1','sung hanbin','zhang hao']),
    (60, ['exo','baekhyun','kai','suho','chanyeol']),
    (37, ['itzy','yeji','ryujin','chaeryeong','yuna']),
    (45, ['boa']),
    (33, ['xg','jurin','chisa','hinata','harvey']),
]
matched = []
for cid, keywords in artist_rules:
    if any(word in title for word in keywords):
        matched.append(str(cid))
print(",".join(matched))
PY
  )

  # --- タグ自動生成・取得 ---
  TAG_NAMES=$(python3 - "$TITLE" << 'PY'
import sys
title = sys.argv[1].lower()
rules = [
    ('BTS', ['bts','rm','jin','suga','j-hope','jimin','jungkook']),
    ('BIGBANG', ['bigbang','g-dragon','gd','taeyang','daesung']),
    ('BLACKPINK', ['blackpink','jennie','jisoo','rose','rosé','lisa']),
    ('aespa', ['aespa','karina','winter','ningning','giselle']),
    ('BABYMONSTER', ['babymonster']),
    ('ILLIT', ['illit']),
    ('IVE', ['ive','wonyoung','yujin']),
    ('LE SSERAFIM', ['le sserafim','lesserafim']),
    ('SEVENTEEN', ['seventeen','svt']),
    ('TWICE', ['twice']),
    ('Stray Kids', ['stray kids','skz']),
    ('NewJeans', ['newjeans']),
    ('XG', ['xg']),
    ('カムバック', ['カムバック','カムバ','復帰']),
    ('ワールドツアー', ['ワールドツアー','ツアー','ライブ','コンサート']),
    ('K-POP速報', ['速報','最新情報']),
]
matched = []
for tag_name, keywords in rules:
    if any(word in title for word in keywords):
        matched.append(tag_name)
print('|'.join(dict.fromkeys(matched)))
PY
  )

  TAG_IDS=$(python3 - "$TAG_NAMES" << 'PY'
import sys, json, urllib.request, urllib.parse, base64
raw = sys.argv[1].strip()
if not raw:
    print(""); sys.exit()
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
            tag_ids.append(str(match["id"])); continue
    except: pass
    req = urllib.request.Request(base_url,
        data=json.dumps({"name": name}).encode(), headers=headers)
    try:
        with urllib.request.urlopen(req) as res:
            tag = json.loads(res.read())
            tag_ids.append(str(tag["id"]))
    except: pass
print(",".join(tag_ids))
PY
  )

  # --- スラッグ生成 ---
  SLUG=$(claude -p "
以下の日本語タイトルをSEOに強い英語スラッグに変換せよ。
小文字英数字とハイフンのみ。30〜50文字。アーティスト名・イベント種別・年を含める。1行のみ出力。
タイトル：$TITLE
" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9-]/-/g' | sed 's/-\+/-/g' | sed 's/^-\|-$//' | cut -c1-60)
  [[ -z "$SLUG" ]] || [[ ${#SLUG} -lt 5 ]] && SLUG="kpop-council-$(date '+%Y%m%d-%H%M')"

  DESC=$(echo "$CONTENT" | sed -e 's/<[^>]*>//g' | python3 -c "import sys; t=sys.stdin.read().strip(); print(t[:120])")

  log "  タイトル: $TITLE"
  log "  スラッグ: $SLUG"
  log "  カテゴリ: $CATEGORY_ID / アーティスト: $ARTIST_CATEGORY_IDS"
  log "  タグ: $TAG_IDS"

  # --- WordPress投稿 ---
  echo "$TITLE"   > /tmp/kpop_title.txt
  echo "$CONTENT" > /tmp/kpop_content.txt
  echo "$DESC"    > /tmp/kpop_desc.txt

  JSON=$(python3 - "$SLUG" "$CATEGORY_ID" "${MEDIA_ID:-0}" "$ARTIST_CATEGORY_IDS" "$TAG_IDS" "publish" << 'PY'
import json, sys
slug           = sys.argv[1]
main_category  = int(sys.argv[2])
media_id       = int(sys.argv[3]) if sys.argv[3] else 0
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
        if x: categories.append(int(x))
categories = list(dict.fromkeys(categories))

tags = []
if tag_ids_raw:
    for x in tag_ids_raw.split(","):
        x = x.strip()
        if x: tags.append(int(x))

payload = {
    'title': title, 'content': content, 'status': status,
    'slug': slug, 'excerpt': desc, 'categories': categories, 'tags': tags,
}
if media_id > 0:
    payload['featured_media'] = media_id

print(json.dumps(payload, ensure_ascii=False))
PY
  )

  RESPONSE=$(curl -s -X POST https://www.kpopjournal.tokyo/wp-json/wp/v2/posts \
    -u "$WP_USER:$WP_PASS" \
    -H "Content-Type: application/json" \
    -d "$JSON")

  POST_URL=$(echo "$RESPONSE" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('link',''))" 2>/dev/null || echo "")
  POST_ID=$(echo "$RESPONSE"  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('id',''))"  2>/dev/null || echo "")

  if [[ -z "$POST_ID" ]] || [[ "$POST_ID" == "None" ]]; then
    log "❌ WordPress投稿失敗"
    log "  レスポンス: $RESPONSE"
    archive_and_exit 1
  fi

  log "✅ 投稿完了: ID=${POST_ID}"
  log "  URL: ${POST_URL}"

  # 収益導線自動挿入
  bash ~/google_metrics/inject_revenue_links.sh "$POST_ID" 2>/dev/null || log "  ⚠ 収益導線スキップ"

  # 内部リンク自動挿入
  if [[ -n "$SLUG" ]]; then
    log "  内部リンク挿入..."
    bash ~/google_metrics/add_internal_links.sh "/$SLUG/" 2>/dev/null && log "  ✓ 内部リンク追加" || log "  ⚠ 内部リンクスキップ"
  fi

  # Google Indexing API
  if [[ -n "$POST_URL" ]] && [[ "$POST_URL" != "None" ]]; then
    log "  Google Indexing API リクエスト..."
    bash ~/google_metrics/request_index.sh "$POST_URL" 2>/dev/null && log "  ✓ Google インデックス送信" || log "  ⚠ Google インデックススキップ"
    # Bing URL Submission API
    log "  Bing URL Submission..."
    bash ~/google_metrics/request_bing_index.sh "$POST_URL" 2>/dev/null && log "  ✓ Bing インデックス送信" || log "  ⚠ Bing インデックススキップ"
  fi

  phase_timer_end
}

# ============================================================
# Phase 8: SNS戦略 → アーカイブ → 通知
# ============================================================
phase8_finalize() {
  local article="$1"
  log "Phase 8: SNS戦略・アーカイブ"
  phase_timer_start

  TITLE=$(head -n 1 "$article")
  CONTENT=$(tail -n +3 "$article")
  local content_plain
  content_plain=$(echo "$CONTENT" | sed 's/<[^>]*>//g' | head -c 300)

  # SNS戦略
  claude --dangerously-skip-permissions --agent persian -p "
今日は${TODAY}です。
以下のK-POP速報記事が投稿されました。SNS拡散戦略を設計せよ。

【記事タイトル】${TITLE}
【記事URL】${POST_URL}
【記事冒頭】${content_plain}

X投稿文3パターン・推奨ハッシュタグセット・最適投稿タイミング・採用推奨パターンを出力せよ。
" > "$REPORTS/sns_strategy.md" 2>/dev/null || log "  ⚠ SNS戦略スキップ"

  # X/Twitter自動投稿
  log "  X/Twitter自動投稿..."
  bash ~/google_metrics/post_to_x.sh "$TITLE" "$POST_URL" "$REPORTS/sns_strategy.md" 2>/dev/null && log "  ✓ X投稿完了" || log "  ⚠ X投稿スキップ"

  # アーカイブ
  mkdir -p "$ARCHIVE_DIR"
  cp "$REPORTS"/* "$ARCHIVE_DIR/" 2>/dev/null || true

  PLAIN_CHARS=$(echo "$CONTENT" | sed 's/<[^>]*>//g' | python3 -c "import sys; print(len(sys.stdin.read().strip()))")

  cat > "$ARCHIVE_DIR/summary.txt" << SUMMARY
実行ID      : $RUN_ID
パイプライン: council (完全体)
日時        : $TODAY
記事ID      : $POST_ID
URL         : $POST_URL
タイトル    : $TITLE
文字数      : $PLAIN_CHARS
経過時間    : $(elapsed)
判定        : 投稿OK
SUMMARY

  bash ~/kpop_notify.sh success "合議" "記事投稿完了: $TITLE" "$POST_URL" 2>/dev/null || true
  discord "✅ 合議完全体 完了 → ${POST_URL} ($(elapsed))"

  phase_timer_end
}


# ============================================================
# ████ メインループ ████
# ============================================================
echo ""
echo "╔════════════════════════════════════════════════╗"
echo "║  AI合議システム 完全体 v2 起動                  ║"
echo "║  案A(差し戻し) + 案B(合議) + 案C(ディベート)   ║"
echo "║  $(date '+%Y-%m-%d %H:%M:%S')                          ║"
echo "╚════════════════════════════════════════════════╝"
echo ""

discord "🏛️ AI合議 完全体v2 起動 (${TODAY})"

# Phase 0
phase0_wp_check

FINAL_ARTICLE=""
GEN_FEEDBACK=""

for gen_attempt in $(seq 1 $MAX_GEN_RETRIES); do
  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  生成サイクル ${gen_attempt}/${MAX_GEN_RETRIES}  (経過: $(elapsed))"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

  # ── Phase 1: deoxys 記事生成 ──
  phase1_generate "$gen_attempt" "$GEN_FEEDBACK"
  CURRENT_DRAFT="$REPORTS/draft_${gen_attempt}.md"

  # ── Phase 2: 合議（案B）──
  phase2_council "$CURRENT_DRAFT"
  COUNCIL_VERDICT=$(cat "$REPORTS/council_verdict.txt" 2>/dev/null || echo "COUNCIL_GO")
  COUNCIL_AVG=$(cat "$REPORTS/council_avg.txt" 2>/dev/null || echo "5.0")
  log "合議判定: $COUNCIL_VERDICT (avg: $COUNCIL_AVG)"

  # ── Phase 3: ディベート（案C）──
  # 合議平均 ≥ 8.0 → ディベートスキップ（高品質と判断）
  SKIP_DEBATE=$(python3 -c "print('YES' if float('${COUNCIL_AVG}') >= 8.0 else 'NO')")
  if [[ "$SKIP_DEBATE" == "YES" ]]; then
    log "合議平均 ≥ 8.0 → ディベートスキップ"
  else
    for debate_round in $(seq 1 $MAX_DEBATE_ROUNDS); do
      CURRENT_DRAFT=$(phase3_debate "$CURRENT_DRAFT" "$debate_round")
    done
  fi

  # ── Phase 4: arceus 最終裁定（案A: 差し戻しゲート）──
  VERDICT=$(phase4_arceus "$CURRENT_DRAFT")

  if [[ "$VERDICT" == "GO" ]]; then
    log "✅ arceus: 投稿承認"
    FINAL_ARTICLE="$CURRENT_DRAFT"
    break
  else
    log "❌ arceus: 差し戻し (試行 ${gen_attempt}/${MAX_GEN_RETRIES})"

    # 差し戻し理由を抽出してフィードバック（案A）
    GEN_FEEDBACK=$(python3 -c "
import re
text = open('${REPORTS}/arceus_verdict.md').read()
m = re.search(r'【NO_GO時の差し戻し指示】(.*)', text, re.DOTALL)
feedback = m.group(1).strip()[:500] if m else ''
# 合議の問題点も追加
try:
    council = open('${REPORTS}/council_summary.txt').read()
    lines = [l for l in council.split('\n') if l.strip() and not l.startswith('avg:')]
    if lines:
        feedback += '\n\n【合議からの追加指摘】\n' + '\n'.join(lines[:5])
except: pass
print(feedback if feedback else '品質を全体的に改善せよ')
" 2>/dev/null || echo "品質を全体的に改善せよ")

    discord "⚠️ 差し戻し ${gen_attempt}回目: ${GEN_FEEDBACK:0:100}"

    if [ "$gen_attempt" -ge "$MAX_GEN_RETRIES" ]; then
      echo ""
      log "❌ 最大リトライ（${MAX_GEN_RETRIES}回）到達 → 中断"
      discord "❌ 合議完全体: 最大リトライ到達 → 投稿中止"
      archive_and_exit 1
    fi
  fi
done

if [ -z "$FINAL_ARTICLE" ]; then
  log "❌ 最終記事が確定しませんでした"
  archive_and_exit 1
fi

# ── Phase 5: mewtwo CEO承認 ──
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Phase 5: mewtwo CEO最終承認  (経過: $(elapsed))"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
CEO_RESULT=$(phase5_mewtwo "$FINAL_ARTICLE")

if ! echo "$CEO_RESULT" | grep -q "CEO_APPROVED"; then
  log "❌ CEO却下"
  discord "❌ 合議完全体: CEO却下"
  archive_and_exit 1
fi

# ── Phase 6: 品質ゲート ──
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Phase 6: 品質ゲート  (経過: $(elapsed))"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
phase6_quality_gate "$FINAL_ARTICLE"

# ── Phase 7: WordPress投稿 ──
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Phase 7: WordPress投稿  (経過: $(elapsed))"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
phase7_publish "$FINAL_ARTICLE"

# ── Phase 8: SNS・アーカイブ ──
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Phase 8: SNS・アーカイブ  (経過: $(elapsed))"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
phase8_finalize "$FINAL_ARTICLE"

# 最終記事を共有パスにもコピー
cp "$FINAL_ARTICLE" "$BASE/council_final.md"

echo ""
echo "╔════════════════════════════════════════════════╗"
echo "║  ✅ 合議完全体 全Phase完了                      ║"
echo "║  記事ID  : ${POST_ID}                          ║"
echo "║  URL     : ${POST_URL}                         ║"
echo "║  経過時間: $(elapsed)                           ║"
echo "╚════════════════════════════════════════════════╝"
