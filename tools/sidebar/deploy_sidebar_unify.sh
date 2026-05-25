#!/usr/bin/env bash
# deploy_sidebar_unify.sh — 記事サイドバーのデザイン統一 + ミュージックチャート追加(最終仕上げ)。
#   ① append の重複「1ヶ月以内のイベント」block 削除(prepend のイベント枠 kpop_render_events_widget と重複)
#   ② prepend にミュージックチャート(kpop_render_chart_ranking / Soompi top10)を追加
#   ③ 統一CSS(widget-title→box-title・余白)+ 更新shortcode を配置
#   ④ Soompi チャートデータを wp_option に取り込み
#   全工程 .bak退避 + php -l + 失敗時ロールバック。owner 実行: sudo bash tools/sidebar/deploy_sidebar_unify.sh
set -uo pipefail
THEME="/var/www/wp_stg/wp-content/themes/generatepress-kpop"
SRC="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SRC/../.." && pwd)"
FUNC="$THEME/functions.php"
CSS="$THEME/style.css"
WP="sudo -u www-data wp --path=/var/www/wp_stg"
TS="$(date +%s)"
fail(){ echo "[FATAL] $1"; exit 1; }
lint(){ command -v php >/dev/null && php -l "$1" >/dev/null 2>&1; }

echo "================ ① 更新版 shortcode/CSS 配置 ================"
lint "$SRC/sidebar_shortcodes.php" || ! command -v php >/dev/null || fail "shortcode構文NG"
cp "$SRC/sidebar_shortcodes.php" "$THEME/widgets/sidebar_shortcodes.php" && echo "  shortcode更新(chart_ranking含む)"
if ! grep -q "見出し様式の統一" "$CSS"; then
  cp "$CSS" "$CSS.bak.$TS"
  { echo ""; cat "$SRC/sidebar_polish.css"; } >> "$CSS"; echo "  polish/統一CSS追記"
else echo "  CSS既存(skip)"; fi

echo ""
echo "================ ② functions.php: 重複イベント削除 + チャート追加 ================"
cp "$FUNC" "$FUNC.bak.$TS"; echo "  backup: $FUNC.bak.$TS"
python3 - "$FUNC" <<'PYEOF'
import sys, re
fn=sys.argv[1]
s=open(fn).read()
orig=s

# (a) append内の重複「1ヶ月以内のイベント」blockを削除
#     コメント "// 1ヶ月以内のイベント — TEC tribe_events から" から、その if(...){...} 全体を波括弧対応で除去。
marker=s.find("// 1ヶ月以内のイベント")
if marker!=-1:
    # markerからの if ( post_type_exists( 'tribe_events' ) ) { ... } を波括弧バランスで切る
    ifpos=s.find("if ( post_type_exists( 'tribe_events' ) )", marker)
    if ifpos!=-1:
        brace=s.find("{", ifpos)
        depth=0; i=brace
        while i<len(s):
            if s[i]=="{": depth+=1
            elif s[i]=="}":
                depth-=1
                if depth==0: break
            i+=1
        end=i+1
        # markerコメント行頭〜block末尾を削除(前の空白行も巻き込み過ぎない)
        line_start=s.rfind("\n", 0, marker)+1
        s=s[:line_start]+s[end+1:]
        print("  [ok] 重複『1ヶ月以内のイベント』block 削除")
    else:
        print("  [warn] tribe_events if が見つからず(削除skip)")
else:
    print("  [info] 1ヶ月以内のイベントblock 既に無し(skip)")

# (b) prepend のチャート描画: 直接 kpop_render_chart_ranking() を呼ぶ(guard付きshortcodeでなく)。
#     既存の do_shortcode('[kpop_chart_ranking]') があれば直接呼びに置換(記事で空にならないよう)。
if "echo do_shortcode( '[kpop_chart_ranking]' );" in s:
    s = s.replace("echo do_shortcode( '[kpop_chart_ranking]' );",
                  "if ( function_exists( 'kpop_render_chart_ranking' ) ) { kpop_render_chart_ranking(); }")
    print("  [ok] prepend のチャートを直接render呼びに置換(記事の空白/二重を解消)")
elif "kpop_render_chart_ranking()" in s:
    print("  [info] prepend 直接render 既存(skip)")
else:
    # 未挿入なら kpop_render_events_widget(); の直後に直接render呼びを挿入
    s2 = re.sub(
        r"(kpop_render_events_widget\(\);)",
        r"\1\n        if ( function_exists( 'kpop_render_chart_ranking' ) ) { kpop_render_chart_ranking(); }",
        s, count=1)
    if s2 != s:
        s = s2; print("  [ok] prepend にミュージックチャート(直接render)追加")
    else:
        print("  [warn] kpop_render_events_widget() が見つからずチャート未追加")

if s!=orig:
    open(fn,"w").write(s)
    print("  functions.php 更新完了")
else:
    print("  functions.php 変更なし")
PYEOF

# 構文チェック → NGならロールバック
if command -v php >/dev/null && ! php -l "$FUNC" >/dev/null 2>&1; then
  echo "  ⚠️ functions.php 構文NG → ロールバック"; cp "$FUNC.bak.$TS" "$FUNC"; fail "functions.php構文NG(復旧済)"
fi
echo "  functions.php 構文OK"

echo ""
echo "================ ③ Soompi チャートデータ取り込み ================"
if [ -f "$ROOT/data/soompi_chart_top10.json" ]; then
  $WP option update kpop_soompi_chart "$(cat "$ROOT/data/soompi_chart_top10.json")" >/dev/null 2>&1 \
    && echo "  ✅ wp_option kpop_soompi_chart 取り込み($($WP option get kpop_soompi_chart --format=json 2>/dev/null | python3 -c 'import json,sys;print(len(json.load(sys.stdin)["items"]))' 2>/dev/null || echo '?')件)" \
    || echo "  [warn] option取り込み失敗(update_soompi_chart.sh を別途)"
else
  echo "  [warn] chart JSON無し → update_soompi_chart.sh を先に実行"
fi

echo ""
echo "================ ④ トップ(sidebar-1)にミュージックチャートwidget追加 ================"
# トップにも Soompi チャートを出す。記事はprependのdo_shortcodeで出る(widget不要)。
if $WP widget list sidebar-1 --format=json 2>/dev/null | grep -q "kpop_chart_ranking"; then
  echo "  チャートwidget 既存(skip)"
else
  # 人気記事(custom_html-4)の次あたり=position 3 に挿入(誕生日→人気→チャート→…)
  $WP widget add custom_html sidebar-1 3 --title="" --content="[kpop_chart_ranking]" >/dev/null 2>&1 \
    && echo "  ✅ ミュージックチャートwidget追加(pos3)" || echo "  [warn] widget追加失敗"
fi

echo ""
echo "================ 完了 ================"
echo "  記事/トップ両方で再読込し、見出し統一・重複イベント解消・ミュージックチャート表示を確認。"
