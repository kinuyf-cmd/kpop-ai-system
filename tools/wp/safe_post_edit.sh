#!/bin/bash
# safe_post_edit.sh — 記事本文の安全な取得・更新ヘルパー(2026-07-02)
#
# 過去の2大事故を構造的に防ぐ:
#   1. stdin破壊事故: --post_content=- のliteral化で12記事本文消失
#      ([[wp-post-update-stdin-piping-data-loss]])
#   2. ラッパー出力汚染: kpop-wp-ro の db query/post get 出力には
#      カラムヘッダ行 + リテラル\n が混入し、それを書き戻すと本文が壊れる
#      ([[wp-ro-db-query-header-literal-newline-trap]], 2026-07-02実際に発生)
#
# 使い方:
#   tools/wp/safe_post_edit.sh fetch <slug> <out.html>
#       本番の実レンダリングHTML(curl)から entry-content を抽出して保存。
#       これが唯一信頼できる「正解ソース」。編集はこのファイルをベースに行う。
#
#   tools/wp/safe_post_edit.sh apply <post_id> <new_body.html>
#       安全チェック → 現本文をtimestampバックアップ → 更新 → 実レンダリング検証
#       → GSC再index申請 まで一気通貫。チェックに1つでも落ちると更新しない。
#
# 本番(live WP)への書き込みを含むため、apply は実行前に対象タイトルを表示して
# 5秒待つ(Ctrl-Cで中止可)。
set -euo pipefail

BASE=/home/aiuser/kpop-ai-system
SITE=https://www.kpopjournal.tokyo
BACKUP_DIR="$BASE/backups/post_edits"
RW=/usr/local/sbin/kpop/kpop-wp-rw.sh

cmd="${1:-}"

extract_entry_content() {
  # $1=html file → entry-content div の中身を stdout へ
  python3 - "$1" <<'PY'
import re, sys
h = open(sys.argv[1], encoding='utf-8', errors='replace').read()
m = re.search(r'<div class="entry-content[^>]*>(.*?)</div>\s*<footer', h, re.S)
if not m:
    sys.stderr.write("ERR: entry-content が見つからない\n"); sys.exit(1)
print(m.group(1).strip())
PY
}

case "$cmd" in
  fetch)
    slug="${2:?usage: fetch <slug> <out.html>}"; out="${3:?usage: fetch <slug> <out.html>}"
    tmp=$(mktemp)
    curl -sf -A "Mozilla/5.0" "$SITE/$slug/?nc=$(date +%s)" -o "$tmp"
    extract_entry_content "$tmp" > "$out"
    rm -f "$tmp"
    chars=$(wc -m < "$out")
    echo "[OK] 正解ソース保存: $out (${chars}字, curl実レンダリング由来=汚染なし)"
    echo "     このファイルを編集して apply に渡すこと"
    ;;

  apply)
    post_id="${2:?usage: apply <post_id> <new_body.html>}"
    body_file="${3:?usage: apply <post_id> <new_body.html>}"
    [ -f "$body_file" ] || { echo "[DENY] ファイルが無い: $body_file"; exit 3; }

    # ── 安全チェック(1つでも落ちたら更新しない) ──
    python3 - "$body_file" <<'PY'
import sys
s = open(sys.argv[1], encoding='utf-8').read()
errors = []
if len(s.strip()) < 500:
    errors.append(f"本文が短すぎる ({len(s.strip())}字 < 500) — 空/破損ファイルの疑い")
if s.strip() == '-':
    errors.append("本文が '-' — stdin literal化事故のパターン")
if s.lstrip().startswith('post_content'):
    errors.append("先頭に 'post_content' ヘッダ混入 — wp-ro出力汚染のパターン")
if '\\n' in s:
    errors.append(f"リテラル \\n が {s.count(chr(92)+'n')} 個混入 — wp-ro出力汚染のパターン")
if not s.lstrip().startswith('<'):
    errors.append("HTMLタグで始まっていない — プレーンテキスト/破損の疑い")
if errors:
    print("[DENY] 安全チェック失敗:")
    for e in errors: print(f"   ✗ {e}")
    sys.exit(4)
print(f"[OK] 安全チェック通過 ({len(s)}字)")
PY

    # ── 対象確認(誤ID防止) + 5秒待機 ──
    title=$(sudo -n /usr/local/sbin/kpop/kpop-wp-ro post get "$post_id" --field=post_title 2>/dev/null | tail -1)
    slug=$(sudo -n /usr/local/sbin/kpop/kpop-wp-ro post get "$post_id" --field=post_name 2>/dev/null | tail -1)
    echo "[対象] ID=$post_id 「$title」 (/$slug/)"
    echo "       5秒後に本番へ書き込みます (Ctrl-Cで中止)..."
    sleep 5

    # ── 現本文をバックアップ(curl実レンダリング=汚染なしの正解を保存) ──
    mkdir -p "$BACKUP_DIR"
    ts=$(date +%Y%m%d_%H%M%S)
    bak="$BACKUP_DIR/post${post_id}_${ts}.html"
    tmp=$(mktemp)
    if curl -sf -A "Mozilla/5.0" "$SITE/$slug/?nc=$(date +%s)" -o "$tmp"; then
      extract_entry_content "$tmp" > "$bak" || cp "$tmp" "$bak"
      echo "[OK] バックアップ: $bak"
    else
      echo "[WARN] 現ページのcurl失敗(非公開記事?) — バックアップなしで続行"
    fi
    rm -f "$tmp"

    # ── 更新(コマンド置換で直接渡し=stdin '-' 禁止) ──
    NEWBODY="$(cat "$body_file")"
    sudo -n "$RW" post update "$post_id" --post_content="$NEWBODY"

    # ── 実レンダリング検証(DB照合でなくcurlで見る) ──
    sleep 2
    tmp2=$(mktemp)
    curl -sf -A "Mozilla/5.0" "$SITE/$slug/?nc=$(date +%s)" -o "$tmp2"
    python3 - "$tmp2" <<'PY'
import re, sys
h = open(sys.argv[1], encoding='utf-8', errors='replace').read()
m = re.search(r'<div class="entry-content[^>]*>(.*?)</div>\s*<footer', h, re.S)
ec = m.group(1) if m else ''
bad = []
if 'post_content' in ec: bad.append("'post_content' ヘッダ混入")
if '\\n' in ec: bad.append("リテラル \\n 混入")
if len(ec.strip()) < 500: bad.append(f"本文が短い({len(ec.strip())}字)")
if bad:
    print("[FAIL] 実レンダリング検証NG: " + " / ".join(bad))
    print("       バックアップから復旧を検討してください")
    sys.exit(5)
print(f"[OK] 実レンダリング検証PASS ({len(ec.strip())}字)")
PY
    rm -f "$tmp2"

    # ── GSC再index申請([[always-gsc-submit-after-publish]]) ──
    cd "$BASE"
    venv_kpi/bin/python3 lib/gsc_indexing.py --url "$SITE/$slug/" 2>&1 | tail -1
    echo "[DONE] post $post_id 更新完了(バックアップ・検証・GSC申請済)"
    ;;

  *)
    echo "usage:"
    echo "  $0 fetch <slug> <out.html>       # 正解ソース取得(curl実レンダリング)"
    echo "  $0 apply <post_id> <body.html>   # 安全チェック→バックアップ→更新→検証→GSC"
    exit 2
    ;;
esac
