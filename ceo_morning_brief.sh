#!/bin/bash
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CEO Morning Brief - 毎朝 9:00 JST
# ミュウツー（CFO/Data）主担当
#
# データソース:
#   必須: ~/kpop_archives/YYYYMMDD_*/summary.txt
#   任意: ~/google_metrics/metrics_yesterday.json
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/env_loader.sh"

TODAY=$(date '+%Y年%m月%d日')
YESTERDAY_KEY=$(date -d 'yesterday' '+%Y%m%d' 2>/dev/null || date -v-1d '+%Y%m%d' 2>/dev/null || echo "")
YESTERDAY_LABEL=$(date -d 'yesterday' '+%Y年%m月%d日' 2>/dev/null || date -v-1d '+%Y年%m月%d日' 2>/dev/null || echo "前日")
ARCHIVE_BASE=~/kpop_archives
METRICS_FILE=~/google_metrics/metrics_yesterday.json

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [1] 前日アーカイブ集計
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# データソース: data/auto_article_processed.jsonl（1行=1処理）。
# kind="breaking"=公開成功 / kind="*_blocked"=品質ゲートで停止。
# 旧 ~/kpop_archives/*/summary.txt は 2026-04-15 を最後に書き込み停止しており
# 集計に使うと「前日0本」と誤報する（2026-05-27 修正）。
PROCESSED_FILE="$SCRIPT_DIR/data/auto_article_processed.jsonl"
EVAL=$(YESTERDAY_KEY="$YESTERDAY_KEY" python3 -c "
import os, json, collections
key = os.environ['YESTERDAY_KEY']           # YYYYMMDD
ymd = f'{key[:4]}-{key[4:6]}-{key[6:8]}'    # ISO の日付プレフィックス
ok = ng = 0
by_type_ok = collections.Counter()
by_type_ng = collections.Counter()
lines = []
try:
    with open('$PROCESSED_FILE') as f:
        for raw in f:
            try:
                d = json.loads(raw)
            except Exception:
                continue
            if not str(d.get('ts', '')).startswith(ymd):
                continue
            kind = d.get('kind', '')
            typ = d.get('type', '') or 'other'
            if kind == 'breaking':
                ok += 1
                by_type_ok[typ] += 1
            elif kind.endswith('_blocked'):
                ng += 1
                by_type_ng[typ] += 1
    total = ok + ng
    rate = (ok * 100 // total) if total else 0
    # 出力: 集計値（KEY=VALUE 形式で bash に渡す）
    print(f'OK={ok}')
    print(f'NG={ng}')
    print(f'TOTAL={total}')
    print(f'RATE={rate}')
except FileNotFoundError:
    print('OK=0'); print('NG=0'); print('TOTAL=0'); print('RATE=0')
" 2>/dev/null)

SUCCESS=$(echo "$EVAL" | grep '^OK=' | cut -d= -f2); SUCCESS=${SUCCESS:-0}
STOPPED=$(echo "$EVAL" | grep '^NG=' | cut -d= -f2); STOPPED=${STOPPED:-0}
TOTAL=$(echo "$EVAL" | grep '^TOTAL=' | cut -d= -f2); TOTAL=${TOTAL:-0}
RATE=$(echo "$EVAL" | grep '^RATE=' | cut -d= -f2); RATE=${RATE:-0}

# 速報/戦略/チャートの旧3分類は auto_article_processed では区別されないため
# 「速報(breaking)」を speed 行に集約表示し、他は 0 とする。
SPEED_OK=$SUCCESS; SPEED_NG=$STOPPED
STRATEGY_OK=0; STRATEGY_NG=0
CHART_OK=0; CHART_NG=0
if [ "$SUCCESS" -gt 0 ]; then
  ARTICLE_LINES="  ✅ 速報 ${SUCCESS}本 公開\n"
else
  ARTICLE_LINES=""
fi
if [ "$STOPPED" -gt 0 ]; then
  ARTICLE_LINES="${ARTICLE_LINES}  ⛔ ${STOPPED}本 品質ゲートで停止（誤情報/無関係コンテンツ等）\n"
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [2] メトリクス（存在する場合のみ）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
METRICS_SECTION="※ メトリクスデータ未取得"

if [[ -f "$METRICS_FILE" ]]; then
  METRICS_SECTION=$(python3 -c "
import json, sys
try:
    with open('$METRICS_FILE') as f:
        d = json.load(f)
    lines = []
    # 鮮度チェック(2026-05-23): GA4計測が約6週間止まり古い値を報告し続けた事故の再発防止。
    # date(対象日) が今日から3日以上前なら警告を先頭に出す。
    from datetime import date as _date
    _dt = d.get('date', '')
    try:
        _y, _m, _dd = (int(x) for x in _dt.split('-'))
        _age = (_date.today() - _date(_y, _m, _dd)).days
        if _age >= 3:
            lines.append(f'  ⚠️ 計測データが古い(対象日 {_dt}・{_age}日前)。fetch_yesterday cron を確認')
    except Exception:
        lines.append('  ⚠️ 計測データの対象日が不明(metrics 未取得?)')
    _errs = d.get('errors', {}) or {}
    if _errs:
        lines.append(f\"  ⚠️ 取得失敗: {', '.join(_errs.keys())}\")
    ga4 = (d.get('ga4') or {}).get('summary', {}) or {}
    if ga4:
        lines.append(f\"  PV: {ga4.get('pageviews', '?')} / セッション: {ga4.get('sessions', '?')} / ユーザー: {ga4.get('users', '?')}\")
    gsc = d.get('gsc') or {}
    queries = gsc.get('top_queries', []) or []
    if queries:
        top = ', '.join(q['query'] for q in queries[:3])
        lines.append(f'  Top検索: {top}')
    adsense = d.get('adsense') or {}
    earnings = adsense.get('ESTIMATED_EARNINGS') if isinstance(adsense, dict) else None
    if earnings:
        lines.append(f'  AdSense: ¥{earnings}')
    if lines:
        print('\n'.join(lines))
    else:
        print('  データはあるが主要項目なし')
except Exception as e:
    print(f'  読み込みエラー: {e}')
" 2>/dev/null || echo "  メトリクス解析失敗")
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [3] 特筆事項
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NOTABLE=""

# STOPPED は品質ゲートのブロック数。高ブロック率は誤情報を弾いている＝正常動作の場合が
# 多いので「異常」とは断じない。判断材料は「処理は走ったのに公開ゼロ」かどうか。
if [ "$TOTAL" -eq 0 ]; then
  NOTABLE="${NOTABLE}  ⚠ 前日の記事処理がゼロ（collector/detector の起動を確認）\n"
fi
if [ "$SUCCESS" -eq 0 ] && [ "$TOTAL" -gt 0 ]; then
  NOTABLE="${NOTABLE}  🚨 処理${TOTAL}件すべてゲートで停止・公開ゼロ — ソース品質かゲート閾値を確認\n"
elif [ "$TOTAL" -gt 0 ] && [ "$RATE" -lt 20 ]; then
  NOTABLE="${NOTABLE}  ⚠ 公開率${RATE}%（${SUCCESS}/${TOTAL}）— ソースの品質低下かゲート過剰の可能性\n"
fi

[[ -z "$NOTABLE" ]] && NOTABLE="  特になし\n"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [4] 当日方針（ルールベース）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
POLICY=""

if [ "$TOTAL" -eq 0 ]; then
  POLICY="  → cron実行状況を確認。collector/detector が起動していない可能性"
elif [ "$SUCCESS" -eq 0 ]; then
  POLICY="  → 公開ゼロ。cron_breaking.log のブロック理由を確認しゲート閾値/ソースを点検"
elif [ "$SUCCESS" -ge 1 ]; then
  POLICY="  → 速報${SUCCESS}本公開・通常運用を継続（停止${STOPPED}件はゲート正常動作の範囲か確認）"
else
  POLICY="  → 通常運用を継続"
fi

if [[ "$METRICS_SECTION" == *"未取得"* ]]; then
  POLICY="${POLICY}\n  → fetch_yesterday_metrics.py の定期実行を検討"
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [5] ブリーフ組み立て
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BRIEF="📋 CEO Morning Brief — ${TODAY}

【1. 前日サマリー（${YESTERDAY_LABEL}）】
  記事: ${SUCCESS}本公開 / ${STOPPED}本ゲート停止 / 計${TOTAL}件処理（公開率${RATE}%）

【2. 投稿記事一覧】
$(echo -e "${ARTICLE_LINES:-  （なし）}")
【3. SEO/アクセス】
${METRICS_SECTION}

【4. 特筆事項】
$(echo -e "$NOTABLE")
【5. 当日の方針】
$(echo -e "$POLICY")

— Generated by ミュウツー (CFO/Data)"

echo "$BRIEF"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [6] Discord送信（#daily-ceo-report チャネル）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
source "$SCRIPT_DIR/lib/discord_channels.sh" 2>/dev/null || true
WEBHOOK=$(get_discord_webhook "daily_ceo_report" 2>/dev/null || echo "")
[ -z "$WEBHOOK" ] && WEBHOOK="${DISCORD_WEBHOOK:-}"

if [[ -z "$WEBHOOK" ]]; then
  echo ""
  echo "⚠ DISCORD_WEBHOOK 未設定 → Discord送信スキップ"
  exit 0
fi

# テキストメッセージとして送信（2000文字制限に収める）
MESSAGE=$(echo "$BRIEF" | head -c 1950)

HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
  -X POST "$WEBHOOK" \
  -H "Content-Type: application/json" \
  -d "$(python3 -c "import json,sys; print(json.dumps({'content': sys.argv[1]}))" "$MESSAGE")" \
  --connect-timeout 10 --max-time 15 2>/dev/null || echo "000")

if [[ "$HTTP_CODE" == "204" || "$HTTP_CODE" == "200" ]]; then
  echo ""
  echo "✅ Discord送信完了"
else
  echo ""
  echo "⚠ Discord送信失敗 (HTTP ${HTTP_CODE})"
fi
