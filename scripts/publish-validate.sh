#!/bin/bash
# 下書き(既定)または公開ページ(--live)を描画して公開可否を判定する。失敗なら exit 1。
# 詳細は tools/content_pipeline/publish_validate.py の docstring。
cd "$(dirname "$0")/.." || exit 2
PY=venv_kpi/bin/python3; [ -x "$PY" ] || PY=python3
exec "$PY" tools/content_pipeline/publish_validate.py "$@"
