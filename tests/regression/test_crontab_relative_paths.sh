#!/usr/bin/env bash
# crontab に「cd 無しの相対パス実行」が無いことを検査する。
#
# 2026-08-23: idol_wiki_release_daily.sh が相対パス指定で81日間毎日失敗していた。
# 同じセッション中に自分でも3回 cd を書き忘れた。cron は $HOME で実行されるため、
# リポジトリ相対のコマンド(venv_kpi/... や lib/... )は cd 無しでは必ず失敗する。
set -uo pipefail
bad=0
while IFS= read -r line; do
  case "$line" in
    ''|\#*|SHELL=*|PATH=*|MAILTO=*) continue ;;
  esac
  # 時刻5フィールドを除いたコマンド部
  cmd="$(echo "$line" | sed -E 's/^([^ ]+ +){5}//')"
  # 先頭の環境変数代入(VAR=value)を除く
  cmd="$(echo "$cmd" | sed -E 's/^([A-Za-z_][A-Za-z0-9_]*=[^ ]* +)+//')"
  case "$cmd" in
    cd\ /*) continue ;;                 # cd 付きは OK
    /*|*/usr/bin/env*|curl\ *) continue ;;  # 絶対パス/env/curl は OK
  esac
  # リポジトリ相対に見えるものだけ落とす
  case "$cmd" in
    venv_kpi/*|lib/*|tools/*|pipeline/*|scripts/*|*.sh\ *|*.py\ *)
      echo "  ✗ cd 無しの相対パス: $line"; bad=1 ;;
  esac
done < <(crontab -l 2>/dev/null)
[ "$bad" = 0 ] && echo "PASS: cd 無しの相対パス cron なし" || { echo "FAIL"; exit 1; }
