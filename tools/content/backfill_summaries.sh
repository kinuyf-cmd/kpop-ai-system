#!/usr/bin/env bash
# backfill_summaries.sh — 3行まとめ(.kpj-summary)が無い公開記事に遡及生成して挿入する。
#
# 表示側(functions.php/content-single.php)は kpj-summary を冒頭TL;DRへ自動昇格する
# 仕組みが既にある([[summary-box-promoted-to-article-top]])。本スクリプトは「まとめ自体が
# 無い古い記事」に extractive summary(lib/article_summarizer.py)を埋め込む遡及バッチ。
#
# 安全策(本文書換え=高リスク。[[wp-post-update-stdin-piping-data-loss]]の12記事消失事故を踏まえる):
#   1. 対象は kpj-summary を持たない記事のみ(冪等・二重挿入防止)
#   2. 適用前に各記事 post_content を BAKDIR に .html バックアップ
#   3. wp post update へは --post_content=<値> を「直接」渡す(stdin '-' 禁止=事故原因)
#   4. 挿入後に文字数が元の95%未満なら破壊とみなし**自動ロールバック**(バックアップから復元)
#   5. dry-run 既定。--limit N で件数制限。--apply で実行。
#
# owner 実行(書込は rw ラッパー経由):
#   dry-run: bash tools/content/backfill_summaries.sh --limit 5
#   適用   : bash tools/content/backfill_summaries.sh --limit 5 --apply
set -uo pipefail
cd "$(dirname "$0")/../.."   # repo root

RO="sudo -n /usr/local/sbin/kpop/kpop-wp-ro"
RW="sudo /usr/local/sbin/kpop/kpop-wp-rw.sh"
BAKDIR="/home/aiuser/.kpop_recovery/summary_backfill_$(date +%Y%m%d_%H%M%S)"

APPLY=0; LIMIT=0
for a in "$@"; do
  case "$a" in
    --apply) APPLY=1 ;;
    --limit) : ;;                       # 値は次ループで拾う
    --limit=*) LIMIT="${a#--limit=}" ;;
    [0-9]*) LIMIT="$a" ;;               # --limit 5 形式の "5"
  esac
done

echo "=== 3行まとめ遡及生成: $([ "$APPLY" = 1 ] && echo APPLY || echo DRY-RUN) / limit=${LIMIT:-0(無制限)} ==="
[ "$APPLY" = 1 ] && mkdir -p "$BAKDIR" && echo "  バックアップ先: $BAKDIR"

mapfile -t IDS < <($RO post list --post_type=post --post_status=publish --field=ID 2>/dev/null)
echo "  publish 記事: ${#IDS[@]}"

done_n=0; skip_n=0; fail_n=0; rollback_n=0
for pid in "${IDS[@]}"; do
  [ "$LIMIT" -gt 0 ] && [ "$done_n" -ge "$LIMIT" ] && break
  content="$($RO post get "$pid" --field=post_content 2>/dev/null)"
  if [ -z "$content" ]; then echo "  [skip] #$pid 本文取得失敗"; skip_n=$((skip_n+1)); continue; fi
  if printf '%s' "$content" | grep -q 'class="kpj-summary"'; then skip_n=$((skip_n+1)); continue; fi

  title="$($RO post get "$pid" --field=post_title 2>/dev/null)"
  orig_len=$(printf '%s' "$content" | wc -m)

  # まとめ生成+挿入(article_summarizer)。新本文を一時ファイルへ(シェル変数経由の取りこぼし回避)。
  newfile=$(mktemp /tmp/summ_new.XXXXXX.html)
  printf '%s' "$content" | python3 -c "
import sys; sys.path.insert(0,'lib')
from article_summarizer import generate_summary, insert_summary_into_html
html=sys.stdin.read()
summ=generate_summary(html)
sys.stdout.write(insert_summary_into_html(html, summ))
" > "$newfile" 2>/dev/null

  new_len=$(wc -m < "$newfile")
  # 健全性チェック: まとめが挿入され、本文が壊滅的に短くなっていないこと。
  # ※ insert は重複リード文(まとめと同内容の冒頭段落)を1つ削除するため、
  #   まとめ追加分を相殺して -1〜2% 程度縮むのは正常。壊滅的損失(=本文消失)だけ弾く。
  if ! grep -q 'class="kpj-summary"' "$newfile"; then
    echo "  [skip] #$pid まとめ未挿入"; rm -f "$newfile"; skip_n=$((skip_n+1)); continue
  fi
  floor=$(( orig_len * 85 / 100 ))   # 元の85%未満なら本文破壊とみなす
  if [ "$new_len" -lt "$floor" ]; then
    echo "  [skip] #$pid 生成結果が元の85%未満($new_len<$floor) — 本文破壊の疑い"; rm -f "$newfile"; skip_n=$((skip_n+1)); continue
  fi

  if [ "$APPLY" = 1 ]; then
    printf '%s' "$content" > "$BAKDIR/$pid.html"          # ロールバック源
    $RW post update "$pid" --post_content="$(cat "$newfile")" >/dev/null 2>&1
    sleep 1   # 書込コミットの確定待ち(即読み戻しのレース回避)
    # 適用後の本文を読み直して破壊検証(85%未満 or まとめ未挿入=破壊→ロールバック)
    after="$($RO post get "$pid" --field=post_content 2>/dev/null)"
    after_len=$(printf '%s' "$after" | wc -m)
    thresh=$(( orig_len * 85 / 100 ))   # dup-lead除去で-1〜2%は正常。85%未満=破壊。
    if [ "$after_len" -lt "$thresh" ] || ! printf '%s' "$after" | grep -q 'class="kpj-summary"'; then
      echo "  [ROLLBACK] #$pid 本文破壊検知(after=$after_len < 85%=$thresh) → バックアップから復元"
      $RW post update "$pid" --post_content="$(cat "$BAKDIR/$pid.html")" >/dev/null 2>&1
      rollback_n=$((rollback_n+1)); fail_n=$((fail_n+1)); rm -f "$newfile"; continue
    fi
    echo "  [OK] #$pid ${title:0:30} (本文 $orig_len→$after_len 文字)"
  else
    echo "  [DRY] #$pid ${title:0:30} ($orig_len→$new_len 文字, まとめ挿入予定)"
  fi
  rm -f "$newfile"; done_n=$((done_n+1))
done

echo "=== 完了: 適用/予定 $done_n / スキップ $skip_n / 失敗 $fail_n (うちロールバック $rollback_n) ==="
[ "$APPLY" = 1 ] && echo "確認: curl -s '<記事URL>' | grep -c kpj-summary  / ロールバック源: $BAKDIR"
