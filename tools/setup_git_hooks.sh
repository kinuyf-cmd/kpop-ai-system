#!/bin/bash
# Post-clone setup: install KpopJournal pre-commit hook into .git/hooks/.
#
# Why this exists:
#   .git/hooks/ is per-clone (not tracked by git), so the bundling guard +
#   memory_compliance pytest gate must be re-installed after every fresh clone.
#   Run this once after `git clone`.
#
# Usage:
#   ./tools/setup_git_hooks.sh
#
# Idempotent: re-running overwrites the existing pre-commit hook.

set -e

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

HOOK_PATH=".git/hooks/pre-commit"

cat > "$HOOK_PATH" <<'HOOK_EOF'
#!/bin/bash
# memory_compliance pre-commit hook
# memoryルールをコードに反映する責任を機械検証で強制
# violation時は commit を止める

set -e
cd "$(git rev-parse --show-toplevel)"

# bundling guard (巻き込みcommit検知)
if [ -x .claude/hooks/pre_commit_bundling_guard.py ]; then
    if ! .claude/hooks/pre_commit_bundling_guard.py; then
        exit 2
    fi
fi

# 高速化: tests/memory_compliance/ か lib/ と pipeline/ に変更がある場合のみ実行
CHANGED=$(git diff --cached --name-only --diff-filter=ACM)
NEEDS_CHECK=0
for f in $CHANGED; do
    case "$f" in
        tests/memory_compliance/*|lib/*|pipeline/*|config/*|CLAUDE.md|.claude/*)
            NEEDS_CHECK=1
            break
            ;;
    esac
done

if [ "$NEEDS_CHECK" -eq 0 ]; then
    exit 0
fi

echo "[pre-commit] memory_compliance テスト実行中..."
if ! python3 -m pytest tests/memory_compliance/ -q --tb=line 2>&1 | tail -20; then
    echo ""
    echo "❌ [pre-commit] memory_compliance テスト失敗"
    echo "   memoryルール違反です。以下のいずれかを行ってください:"
    echo "   1. コードを修正してmemoryに従わせる"
    echo "   2. memoryが古い場合: memory更新+test更新を同時に commit"
    echo "   3. 緊急時のみ: git commit --no-verify (記録残るため非推奨)"
    exit 1
fi
echo "[pre-commit] memory_compliance ✅ pass"
exit 0
HOOK_EOF

chmod +x "$HOOK_PATH"
echo "✓ installed $HOOK_PATH"

# bundling guard 自体は tracked file なので chmod +x のみ保証
if [ -f .claude/hooks/pre_commit_bundling_guard.py ]; then
    chmod +x .claude/hooks/pre_commit_bundling_guard.py
    echo "✓ chmod +x .claude/hooks/pre_commit_bundling_guard.py"
fi

echo ""
echo "smoke test:"
.claude/hooks/pre_commit_bundling_guard.py && echo "  ✓ bundling-guard runs (exit 0 with empty stage)"
