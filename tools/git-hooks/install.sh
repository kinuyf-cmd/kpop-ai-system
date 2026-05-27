#!/usr/bin/env bash
# install.sh — tools/git-hooks/* を .git/hooks/ に導入する(.git配下は版管理外のため)。
# 冪等。既存 hook がある場合は .bak に退避してから上書き。
set -euo pipefail
cd "$(dirname "$0")/../.."
HOOKDIR=".git/hooks"
SRCDIR="tools/git-hooks"
for hook in pre-push; do
  src="$SRCDIR/$hook"; dst="$HOOKDIR/$hook"
  [ -f "$src" ] || continue
  if [ -f "$dst" ] && ! cmp -s "$src" "$dst"; then
    cp "$dst" "$dst.bak.$(date +%Y%m%d_%H%M%S)"
    echo "  既存 $hook を .bak に退避"
  fi
  cp "$src" "$dst"; chmod +x "$dst"
  echo "  ✓ 導入: $dst"
done
echo "完了。確認: git push 時に [pre-push] 行が出れば有効。"
