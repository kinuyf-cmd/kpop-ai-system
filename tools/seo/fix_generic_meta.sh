#!/usr/bin/env bash
# fix_generic_meta.sh — generic定型meta(AIOSEO自動fallback)だった8記事に、本文要約由来の
#   独自 meta description を設定する。RED TEAM/SEO監査(2026-05-25)。
#   AIOSEO は wp_aioseo_posts.description に保存(NULL=自動生成fallback=generic定型文の原因)。
#   descriptions.json(slug→新description、本文lead由来・検証済)を読み、行があればUPDATE、
#   無ければ最小INSERT。SQLインジェクション回避のため値はPython側で安全エスケープしSQL生成。
#   owner 実行: sudo -u www-data bash tools/seo/fix_generic_meta.sh        # dry-run
#               sudo -u www-data bash tools/seo/fix_generic_meta.sh --apply
set -uo pipefail
WP="wp --path=/var/www/wp_stg"
DIR="$(cd "$(dirname "$0")" && pwd)/meta_fix"
JSON="$DIR/descriptions.json"
APPLY="${1:-}"
[ -f "$JSON" ] || { echo "[FATAL] $JSON が無い"; exit 1; }

echo "================ generic meta 改善 ($([ "$APPLY" = "--apply" ] && echo APPLY || echo DRY-RUN)) ================"
# slug一覧をPythonで取り出してループ
python3 -c "import json;print('\n'.join(json.load(open('$JSON')).keys()))" | while IFS= read -r slug; do
  [ -z "$slug" ] && continue
  pid="$($WP post list --post_type=post --name="$slug" --field=ID 2>/dev/null | head -1)"
  if [ -z "$pid" ]; then echo "  [skip] slug未検出: $slug"; continue; fi
  # 新description と SQL(エスケープ済)をPythonで生成
  # 既存行の有無を確認(post_id は UNIQUE でないため ON DUPLICATE は使わず、行数で UPDATE/INSERT を分岐)
  rowcnt="$($WP db query "SELECT COUNT(*) FROM wp_aioseo_posts WHERE post_id=$pid" --skip-column-names 2>/dev/null)"
  read -r newlen sql < <(python3 - "$JSON" "$slug" "$pid" "$rowcnt" <<'PYEOF'
import json,sys
j,slug,pid,cnt=sys.argv[1],sys.argv[2],int(sys.argv[3]),int(sys.argv[4])
d=json.load(open(j))[slug]
esc=d.replace("\\","\\\\").replace("'","''")  # SQLリテラルエスケープ
if cnt>=1:
    # 既存1行を UPDATE(post_id重複行を作らない=安全)
    sql=f"UPDATE wp_aioseo_posts SET description='{esc}', updated=NOW() WHERE post_id={pid};"
else:
    sql=(f"INSERT INTO wp_aioseo_posts (post_id, description, updated, created) "
         f"VALUES ({pid}, '{esc}', NOW(), NOW());")
print(len(d), sql)
PYEOF
)
  if [ "$APPLY" = "--apply" ]; then
    if $WP db query "$sql" 2>/dev/null; then echo "  [set] $slug (pid=$pid, ${newlen}字, rows=$rowcnt)"; else echo "  [FAIL] $slug"; fi
  else
    echo "  [would-set] $slug (pid=$pid, ${newlen}字, 既存行=$rowcnt → $([ "$rowcnt" -ge 1 ] && echo UPDATE || echo INSERT))"
  fi
done

echo ""
echo "================ 検証 ================"
python3 -c "import json;print('\n'.join(json.load(open('$JSON')).keys()))" | while IFS= read -r slug; do
  [ -z "$slug" ] && continue
  pid="$($WP post list --post_type=post --name="$slug" --field=ID 2>/dev/null | head -1)"
  cur="$($WP db query "SELECT IFNULL(LEFT(description,40),'(NULL)') FROM wp_aioseo_posts WHERE post_id=$pid" --skip-column-names 2>/dev/null)"
  echo "  $slug → $cur"
done
[ "$APPLY" != "--apply" ] && echo "  ※ dry-run。実行は --apply を付けて再実行。"
echo "================ 完了 ================"
