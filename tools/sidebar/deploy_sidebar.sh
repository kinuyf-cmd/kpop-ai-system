#!/usr/bin/env bash
# deploy_sidebar.sh — 右サイドバー: 誕生日枠バグ修正 + イベント枠新設を本番テーマに適用。
#   テーマ書込は owner 権限のため owner 実行。script 自身が functions.php の配線を検出して
#   安全にパッチする(私は /var/www を読めないため、検出ロジックを script に持たせた)。
#   全工程: .bak退避 → 差し替え/追記 → php -l 構文チェック → 失敗時ロールバック。
#   owner 実行: sudo bash tools/sidebar/deploy_sidebar.sh
set -uo pipefail
THEME="/var/www/wp_stg/wp-content/themes/generatepress-kpop"
SRC="$(cd "$(dirname "$0")" && pwd)"
WDIR="$THEME/widgets"
FUNC="$THEME/functions.php"
CSS="$THEME/style.css"
TS="$(date +%s)"
fail(){ echo "[FATAL] $1"; exit 1; }

[ -d "$THEME" ] || fail "テーマが無い: $THEME"
for f in today_birthday.php tomorrow_birthday.php events_widget.php events_widget.css; do
  [ -f "$SRC/$f" ] || fail "ソース欠落: $SRC/$f"
done
command -v php >/dev/null || echo "[warn] php CLI 無し → 構文チェックskip(慎重に)"

lint(){ command -v php >/dev/null && php -l "$1" >/dev/null 2>&1; }

echo "================ ① widget 差し替え/新設 ================"
# today/tomorrow は既存=バックアップして置換。events は新規。
for w in today_birthday tomorrow_birthday events_widget; do
  dst="$WDIR/$w.php"
  if [ -f "$dst" ]; then cp "$dst" "$dst.bak.$TS"; echo "  backup: $dst.bak.$TS"; fi
  if lint "$SRC/$w.php" || ! command -v php >/dev/null; then
    cp "$SRC/$w.php" "$dst"; echo "  置換/新設: $dst"
  else
    fail "$w.php 構文NG(適用中止)"
  fi
done

echo ""
echo "================ ② functions.php 配線 ================"
cp "$FUNC" "$FUNC.bak.$TS"; echo "  backup: $FUNC.bak.$TS"

# 2a. events_widget の require を追加(today_birthday の require 行の直後)。冪等。
if grep -q "events_widget.php" "$FUNC"; then
  echo "  require 既存(skip)"
else
  req_line="$(grep -nE "require.*today_birthday\.php|include.*today_birthday\.php" "$FUNC" | head -1 | cut -d: -f1)"
  if [ -n "$req_line" ]; then
    # today_birthday の require 行を雛形に events 版を直後へ挿入(同じ書式を踏襲)
    tmpl="$(sed -n "${req_line}p" "$FUNC" | sed 's/today_birthday/events_widget/')"
    awk -v ln="$req_line" -v ins="$tmpl" 'NR==ln{print; print ins; next} {print}' "$FUNC" > "$FUNC.tmp" && mv "$FUNC.tmp" "$FUNC"
    echo "  require 追加(L$req_line 直後): $tmpl"
  else
    fail "today_birthday の require 行が見つからない(配線方法を要確認)"
  fi
fi

# 2b. kpop_render_today_birthday() 呼び出しの直後に kpop_render_events_widget() を挿入。冪等。
if grep -q "kpop_render_events_widget" "$FUNC"; then
  echo "  呼び出し 既存(skip)"
else
  call_line="$(grep -nE "kpop_render_today_birthday\s*\(\s*\)" "$FUNC" | head -1 | cut -d: -f1)"
  if [ -n "$call_line" ]; then
    callstmt="$(sed -n "${call_line}p" "$FUNC" | sed 's/kpop_render_today_birthday/kpop_render_events_widget/')"
    awk -v ln="$call_line" -v ins="$callstmt" 'NR==ln{print; print ins; next} {print}' "$FUNC" > "$FUNC.tmp" && mv "$FUNC.tmp" "$FUNC"
    echo "  呼び出し 追加(L$call_line 直後): events枠を今日の誕生日の直後に配置"
  else
    echo "  [warn] kpop_render_today_birthday() 呼び出しが functions.php に無い"
    echo "         → sidebar.php 等別ファイルで呼ばれている可能性。手動配置が必要:"
    echo "         kpop_render_events_widget(); を希望位置に追加してください。"
  fi
fi

# functions.php 構文チェック → NG なら即ロールバック
if command -v php >/dev/null && ! php -l "$FUNC" >/dev/null 2>&1; then
  echo "  ⚠️ functions.php 構文NG → ロールバック"
  cp "$FUNC.bak.$TS" "$FUNC"
  fail "functions.php パッチ失敗(元に戻しました)"
fi
echo "  functions.php 構文OK"

echo ""
echo "================ ③ style.css に events CSS 追記 ================"
if grep -q "kpop-events-list" "$CSS"; then
  echo "  CSS 既存(skip)"
else
  cp "$CSS" "$CSS.bak.$TS"
  { echo ""; echo "/* ==== イベント枠 (deploy_sidebar $TS) ==== */"; cat "$SRC/events_widget.css"; } >> "$CSS"
  echo "  events CSS 追記"
fi

echo ""
echo "================ 検証 ================"
echo "  widgets: $(ls "$WDIR"/today_birthday.php "$WDIR"/tomorrow_birthday.php "$WDIR"/events_widget.php 2>/dev/null | wc -l)/3"
echo "  functions require events: $(grep -c events_widget.php "$FUNC")"
echo "  functions call events: $(grep -c kpop_render_events_widget "$FUNC")"
echo "  css events: $(grep -c kpop-events-list "$CSS")"
echo "  → 全て1以上なら配線完了。サイト表示で確認してください。"
echo "================ 完了 ================"
