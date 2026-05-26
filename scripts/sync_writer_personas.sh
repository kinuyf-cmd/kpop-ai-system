#!/usr/bin/env bash
# config/x_writer_personas.json をテーマ同梱コピーへ同期する。
# X 投稿生成(lib/x_persona_voice.py)は config/ を読み、サイトのライター紹介ページ
# (themes/.../inc/writer-profiles.php)はテーマ同梱コピーを読む。両者の真実のソースは
# config/ なので、JSON を編集したらこのスクリプトでテーマ側へ反映する(両者を一致させる)。
#
# 使い方: bash scripts/sync_writer_personas.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/config/x_writer_personas.json"
DST="$ROOT/themes/generatepress-kpop/data/x_writer_personas.json"

if [ ! -f "$SRC" ]; then
  echo "ERROR: source not found: $SRC" >&2
  exit 1
fi
# JSON 妥当性チェック(壊れたまま同期しない)
python3 -c "import json,sys; json.load(open('$SRC'))" || { echo "ERROR: $SRC is not valid JSON" >&2; exit 1; }

mkdir -p "$(dirname "$DST")"
cp "$SRC" "$DST"
echo "synced: config/x_writer_personas.json -> themes/generatepress-kpop/data/x_writer_personas.json"
