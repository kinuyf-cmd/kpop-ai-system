#!/usr/bin/env bash
# Day12 速報DRAFT 4件を stg WordPress に status=draft で投入する。
# wp-cli はDB直結のため nginx Basic認証/REST App PW は不要。
# 【オーナー対話実行】sudo が要るため owner が VPS で実行:
#   cd /home/aiuser/kpop-ai-system && sudo bash stg_push_breaking_drafts.sh
# 認証値は一切引数に取らない(wp-cli が wp-config.php から読む)。
set -euo pipefail
WP_PATH=/var/www/wp_stg
DRAFT_DIR="$(cd "$(dirname "$0")" && pwd)/reports/breaking_drafts"
WP="sudo -u www-data wp --path=$WP_PATH"

echo "== stg WordPress 速報DRAFT 投入 =="
$WP option get siteurl

for key in stayc onf rescene riize; do
  html="$DRAFT_DIR/$key.html"
  meta="$DRAFT_DIR/$key.meta.json"
  [ -f "$html" ] && [ -f "$meta" ] || { echo "SKIP $key (file missing)"; continue; }
  title=$(python3 -c "import json;print(json.load(open('$meta'))['ja_title'])")
  slug=$(python3 -c "import json;print(json.load(open('$meta'))['slug'])")
  excerpt=$(python3 -c "import json;print(json.load(open('$meta'))['meta'])")
  # 重複防止: 同 slug の既存投稿があればスキップ
  existing=$($WP post list --post_type=post --name="$slug" --field=ID --post_status=any 2>/dev/null | head -1 || true)
  if [ -n "$existing" ]; then echo "SKIP $key: slug=$slug は既存(ID $existing)"; continue; fi
  id=$($WP post create "$html" \
        --post_type=post --post_status=draft \
        --post_title="$title" --post_name="$slug" \
        --post_excerpt="$excerpt" --porcelain)
  echo "OK  $key -> DRAFT post ID=$id (slug=$slug)"
  # メタディスクリプション(AIOSEO)を設定(プラグイン有効時のみ反映)
  $WP post meta update "$id" _aioseo_description "$excerpt" >/dev/null 2>&1 || true
done

echo "== 完了。下書き一覧: =="
$WP post list --post_status=draft --post_type=post --fields=ID,post_title,post_name --format=table
echo "視覚確認: https://stg.kpopjournal.tokyo/wp-admin/edit.php?post_status=draft (Basic認証はブラウザのダイアログで入力)"
