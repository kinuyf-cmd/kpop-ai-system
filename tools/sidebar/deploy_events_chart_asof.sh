#!/usr/bin/env bash
# deploy_events_chart_asof.sh — 2026-05-26 オーナー指示の3点を配置。
#   ① ミュージックチャートに「集計時点」表示  … sidebar_shortcodes.php + sidebar_polish.css(style.css sentinel再統合)
#   ② 1ヶ月以内のイベントはカレンダー(/events/)へ誘導 … events_widget.php
#   ③ /events/ のファーストビューを月カレンダーに    … TEC tribe_events_calendar_options.viewOption=month
# 全工程 .bak退避 + php -l。CSSは既存 sentinel ブロックを置換(色修正反映方式)。
# owner 実行: sudo bash tools/sidebar/deploy_events_chart_asof.sh
set -uo pipefail
THEME="/var/www/wp_stg/wp-content/themes/generatepress-kpop"
SRC="$(cd "$(dirname "$0")" && pwd)"
CSS="$THEME/style.css"
WP="sudo -u www-data wp --path=/var/www/wp_stg"
TS="$(date +%Y%m%d_%H%M%S)"
fail(){ echo "[FATAL] $1"; exit 1; }
lint(){ command -v php >/dev/null && php -l "$1" >/dev/null 2>&1; }

echo "================ ① shortcode(chart集計時点)配置 ================"
lint "$SRC/sidebar_shortcodes.php" || ! command -v php >/dev/null || fail "shortcode構文NG"
dst="$THEME/widgets/sidebar_shortcodes.php"
[ -f "$dst" ] && cp -p "$dst" "$dst.bak.$TS"
cp "$SRC/sidebar_shortcodes.php" "$dst" && chown www-data:www-data "$dst" 2>/dev/null || true
echo "  [OK] $dst (md5=$(md5sum "$dst" | cut -d' ' -f1))"

echo "================ ② events_widget(1ヶ月以内→カレンダー)配置 ================"
lint "$SRC/events_widget.php" || ! command -v php >/dev/null || fail "events_widget構文NG"
dst="$THEME/widgets/events_widget.php"
[ -f "$dst" ] && cp -p "$dst" "$dst.bak.$TS"
cp "$SRC/events_widget.php" "$dst" && chown www-data:www-data "$dst" 2>/dev/null || true
echo "  [OK] $dst (md5=$(md5sum "$dst" | cut -d' ' -f1))"

echo "================ ③ style.css の sidebar_polish sentinel 再統合 ================"
[ -f "$CSS" ] || fail "style.css なし: $CSS"
cp "$CSS" "$CSS.bak.$TS"
python3 - "$CSS" "$SRC/sidebar_polish.css" <<'PYEOF'
import sys, re
css_path, src_path = sys.argv[1], sys.argv[2]
BEGIN="/* >>> KPOP_SIDEBAR_POLISH_BEGIN <<< */"
END="/* >>> KPOP_SIDEBAR_POLISH_END <<< */"
css=open(css_path).read()
if BEGIN not in css or END not in css:
    sys.exit("[FATAL] style.css に sidebar_polish sentinel が無い(deploy_sidebar_unify.sh 未適用?)")
css=re.sub(re.escape(BEGIN)+r".*?"+re.escape(END), "", css, flags=re.S).rstrip()+"\n"
block="\n"+BEGIN+"\n"+open(src_path).read().rstrip()+"\n"+END+"\n"
open(css_path,"w").write(css+block)
print("  [OK] sentinel ブロック置換(mchart-asof 反映)")
PYEOF

echo "================ ④ TEC デフォルト表示を月カレンダーに ================"
# viewOption を month へ。tribeEnableViews に month が含まれることを前提(現状 list/month/day)。
cur="$($WP option get tribe_events_calendar_options --format=json 2>/dev/null)"
echo "  変更前 viewOption: $(echo "$cur" | python3 -c "import json,sys;print(json.load(sys.stdin).get('viewOption'))" 2>/dev/null || echo '?')"
$WP eval '
$o = get_option("tribe_events_calendar_options");
if (!is_array($o)) { echo "ERR: option not array\n"; exit; }
$views = isset($o["tribeEnableViews"]) ? (array)$o["tribeEnableViews"] : array();
if (!in_array("month", $views, true)) { $views[] = "month"; $o["tribeEnableViews"] = $views; }
$o["viewOption"] = "month";
update_option("tribe_events_calendar_options", $o);
echo "OK viewOption=month\n";
' 2>&1 | tail -2
echo "  変更後 viewOption: $($WP option get tribe_events_calendar_options --format=json 2>/dev/null | python3 -c "import json,sys;print(json.load(sys.stdin).get('viewOption'))" 2>/dev/null || echo '?')"

echo "================ 完了(backup ts=$TS)================"
echo "  確認: トップ/記事サイドバーの『イベント』枠 → 1ヶ月以内クリックで /events/、"
echo "        /events/ が月カレンダー表示、ミュージックチャートに集計時点が出ること。"
