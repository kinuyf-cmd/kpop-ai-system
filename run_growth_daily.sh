#!/bin/bash
# run_growth_daily.sh — KPOP JOURNAL 成長加速フェーズ 日次オーケストレータ（Xなし前提）
#
# 実行順:
#   1. GSC 最新メトリクス取得
#   2. CTR改善（最大20記事リライト score>=8 strict / meta 110-130字）
#   3. CV記事 1本ドラフト投入
#   4. CTA A/B割当（上位10記事）
#   5. 勝ちクラスター横展開（weekly: 月〜木）
#   6. 効果測定（ctr_effect_measurer）
#
# 制御モード:
#   LIVE=0                  完全 dry-run（デフォルト）
#   LIVE=1                  全機能本番実行
#   ENABLE_<FEATURE>=0/1    機能別マスク。LIVE=1 でも 0 指定で dry-run に落とせる
#
# 機能フラグ（LIVE=1 時に各個別に 0/1 切替可能、未指定ならLIVEに追従）:
#   ENABLE_CTA_AB           CTA A/B 差替
#   ENABLE_CV_DRAFT         CV記事ドラフト投入（draft のみ）
#   ENABLE_CTR_REWRITE      CTR低記事のタイトル上書き
#   ENABLE_CLUSTER_PUBLISH  勝ちクラスター publish (月〜木)
#
# 例:
#   LIVE=0 bash run_growth_daily.sh                                        # 全dry-run
#   LIVE=1 ENABLE_CTA_AB=1 ENABLE_CV_DRAFT=1 \
#         ENABLE_CTR_REWRITE=0 ENABLE_CLUSTER_PUBLISH=0 \
#         bash run_growth_daily.sh                                         # 部分LIVE
#   LIVE=1 bash run_growth_daily.sh                                        # full LIVE
#
# ログ: logs/growth_daily_YYYYMMDD.log

set -u
cd "$(dirname "$0")"

TODAY=$(date +%Y%m%d)
DOW=$(date +%u)  # 1=Mon, 7=Sun
LOG="logs/growth_daily_${TODAY}.log"
mkdir -p logs

LIVE="${LIVE:-0}"
# 機能フラグはLIVEをデフォルトとして継承。個別に 0/1 で上書き可能。
ENABLE_CTA_AB="${ENABLE_CTA_AB:-$LIVE}"
ENABLE_CV_DRAFT="${ENABLE_CV_DRAFT:-$LIVE}"
ENABLE_CTR_REWRITE="${ENABLE_CTR_REWRITE:-$LIVE}"
ENABLE_CLUSTER_PUBLISH="${ENABLE_CLUSTER_PUBLISH:-$LIVE}"

exec >> "$LOG" 2>&1
echo "=== [$(date '+%Y-%m-%d %H:%M:%S')] growth_daily start LIVE=$LIVE DOW=$DOW ==="
echo "    flags: CTA_AB=$ENABLE_CTA_AB CV_DRAFT=$ENABLE_CV_DRAFT CTR_REWRITE=$ENABLE_CTR_REWRITE CLUSTER=$ENABLE_CLUSTER_PUBLISH"

# 1. GSC 最新メトリクス (28日間)
echo "--- [1] gsc_metrics_fetcher ---"
bash -c "source .venv/bin/activate 2>/dev/null; python3 lib/gsc_metrics_fetcher.py --days 28" || echo "  ⚠️ gsc_metrics_fetcher 失敗 (権限/認証)"

# 2. CTR改善 — rewrite_candidates.jsonl 再生成 → ctr_title_rewriter で score>=8 strict
echo "--- [2] ctr_recovery_runner (candidates only) ---"
python3 lib/ctr_recovery_runner.py --candidates-only

echo "--- [2b] ctr_title_rewriter top=20 strict (ENABLE_CTR_REWRITE=$ENABLE_CTR_REWRITE) ---"
if [ "$ENABLE_CTR_REWRITE" = "1" ]; then
  python3 lib/ctr_title_rewriter.py --top 20 --strict \
    --daily-log "logs/ctr_rewrite_daily.jsonl"
else
  python3 lib/ctr_title_rewriter.py --top 20 --strict --dry-run
fi

# 3. CV記事 — 曜日ローテ (月:subsc, 火:cosme, 水:streaming, 木:ticket, 金:subsc, 土:cosme, 日:streaming)
CV_THEMES=(subsc cosme streaming ticket subsc cosme streaming)
CV_THEME=${CV_THEMES[$((DOW - 1))]}
echo "--- [3] cv_article_generator theme=$CV_THEME (ENABLE_CV_DRAFT=$ENABLE_CV_DRAFT) ---"
if [ "$ENABLE_CV_DRAFT" = "1" ]; then
  python3 lib/cv_article_generator.py --theme "$CV_THEME"
else
  python3 lib/cv_article_generator.py --theme "$CV_THEME" --dry-run
fi

# 4. CTA A/B 割当 (上位10記事)
echo "--- [4] cta_ab_runner top=10 (ENABLE_CTA_AB=$ENABLE_CTA_AB) ---"
if [ "$ENABLE_CTA_AB" = "1" ]; then
  python3 lib/cta_ab_runner.py --top 10
else
  python3 lib/cta_ab_runner.py --top 10 --dry-run
fi

# 5. 勝ちクラスター横展開 — 月〜木で4グループ消化
if [ "$DOW" = "1" ]; then
  GROUP="ive"
elif [ "$DOW" = "2" ]; then
  GROUP="newjeans"
elif [ "$DOW" = "3" ]; then
  GROUP="seventeen"
elif [ "$DOW" = "4" ]; then
  GROUP="lesserafim"
else
  GROUP=""
fi

if [ -n "$GROUP" ]; then
  echo "--- [5] cluster_generator group=$GROUP (ENABLE_CLUSTER_PUBLISH=$ENABLE_CLUSTER_PUBLISH) ---"
  if [ "$ENABLE_CLUSTER_PUBLISH" = "1" ]; then
    python3 lib/cluster_generator.py --group "$GROUP" --status publish
  else
    echo "  [dry] cluster_generator --group $GROUP (skipped — flag disabled)"
  fi
else
  echo "--- [5] cluster_generator skipped (DOW=$DOW, 金〜日は実施しない) ---"
fi

# 6. 効果測定
echo "--- [6] ctr_effect_measurer ---"
bash -c "source .venv/bin/activate 2>/dev/null; python3 lib/ctr_effect_measurer.py --auto" || echo "  ⚠️ ctr_effect_measurer 失敗"

echo "=== [$(date '+%Y-%m-%d %H:%M:%S')] growth_daily end ==="
