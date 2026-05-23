#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
KPOP JOURNAL stg — popup 個別ページ 3編集を1パスで適用するパッチャ。
  Edit A: CTA 移動(content-single.php、popup 限定、HTML 改変ゼロ・位置のみ)
  Edit B: 6色洗練(style.css、popup detail 上辺の多色 border-image → 単色ブランドピンク)
  Edit C: 主催ラベル抑制(functions.php、organizer が出典名=kbuzzlab のとき 主催行を出さない)

方針:
  - 正規表現でマークアップを推測しない。exact-string アンカーで置換。
  - アンカーが1回マッチしなければ即異常終了(壊さない)。
  - 適用前に *.bak-YYYYmmddHHMMSS バックアップ。
  - 実行は owner sudo: sudo python3 apply_cta_move_6color_organizer.py
"""
import sys, os, time, shutil, subprocess

THEME = "/var/www/wp_stg/wp-content/themes/generatepress-kpop"
CS  = os.path.join(THEME, "content-single.php")
CSS = os.path.join(THEME, "style.css")
FN  = os.path.join(THEME, "functions.php")
STAMP = time.strftime("%Y%m%d%H%M%S")

def die(msg):
    print("ABORT: " + msg, file=sys.stderr)
    sys.exit(1)

def replace_once(text, old, new, label):
    n = text.count(old)
    if n != 1:
        die("%s: anchor matched %d times (expected 1). No change made." % (label, n))
    return text.replace(old, new, 1)

def backup(path):
    b = path + ".bak-" + STAMP
    shutil.copy2(path, b)
    print("  backup: " + b)
    return b

# ── Edit A: content-single.php ─────────────────────────────────────────────
# the_content() ブロック(line 115-123 相当)を popup 限定でバッファ + CTA 分離。
A_OLD = """\t\t<div class="entry-content" itemprop="text">
\t\t\t<?php
\t\t\tthe_content();
\t\t\twp_link_pages( array(
\t\t\t\t'before' => '<div class="page-links">' . esc_html__( 'Pages:', 'generatepress' ),
\t\t\t\t'after'  => '</div>',
\t\t\t) );
\t\t\t?>
\t\t</div>
"""

A_NEW = """\t\t<div class="entry-content" itemprop="text">
\t\t\t<?php
\t\t\t/* ── popup 限定: CTA(citation-cta〜本文末)を本文から切り離し、
\t\t\t   開催情報box・SNS・地図の後ろへ移動する。位置だけ移動し HTML は改変しない。
\t\t\t   非popup・マーカー未検出は full content をそのまま出力(壊さない)。 */
\t\t\t$kpop_held_cta = '';
\t\t\tif ( $kpop_is_popup_single ) {
\t\t\t\tob_start();
\t\t\t\tthe_content();
\t\t\t\t$kpop_rendered = ob_get_clean();
\t\t\t\t$kpop_cta_pos  = strpos( $kpop_rendered, '<p class="kpop-citation-cta"' );
\t\t\t\tif ( false !== $kpop_cta_pos ) {
\t\t\t\t\techo substr( $kpop_rendered, 0, $kpop_cta_pos ); // 本文〜出典まで
\t\t\t\t\t$kpop_held_cta = substr( $kpop_rendered, $kpop_cta_pos ); // CTA〜本文末を保持
\t\t\t\t} else {
\t\t\t\t\techo $kpop_rendered; // マーカー未検出: 改変せず全出力
\t\t\t\t}
\t\t\t} else {
\t\t\t\tthe_content();
\t\t\t}
\t\t\twp_link_pages( array(
\t\t\t\t'before' => '<div class="page-links">' . esc_html__( 'Pages:', 'generatepress' ),
\t\t\t\t'after'  => '</div>',
\t\t\t) );
\t\t\t?>
\t\t</div>
"""

# popup ブロック(details/おすすめ/upcoming)の閉じ "}" 直後に CTA を再出力。
A2_OLD = """\t\t\tif ( function_exists( 'kpop_render_popup_upcoming' ) ) {
\t\t\t\tkpop_render_popup_upcoming( get_the_ID() );
\t\t\t}
\t\t}
\t\t?>
"""

A2_NEW = """\t\t\tif ( function_exists( 'kpop_render_popup_upcoming' ) ) {
\t\t\t\tkpop_render_popup_upcoming( get_the_ID() );
\t\t\t}
\t\t}
\t\t/* ── 保持していた CTA(出典〜a8 banner〜disclosure)を最後に出力。
\t\t   HTML は本文から切り出したまま無改変。PR/sponsored/nofollow/disclosure 維持。 */
\t\tif ( '' !== $kpop_held_cta ) {
\t\t\techo $kpop_held_cta;
\t\t}
\t\t?>
"""

# ── Edit B: style.css ──────────────────────────────────────────────────────
# popup detail 上辺の3色 border-image を単色ブランドピンクへ。--pp-* ペアは不変。
B_OLD = """\tborder-top: 4px solid var(--pp-rose-deep);
\tborder-image: linear-gradient(90deg, var(--pp-rose-deep), var(--pp-lav-deep) 60%, #1B5E20) 1;"""
B_NEW = """\t/* 6色洗練: 多色グラデ上辺 → 単色ブランドピンク(装飾borderのみ、--pp-* AAペアは不変)。 */
\tborder-top: 4px solid var(--kpop-pink);"""

# ── Edit C: functions.php ──────────────────────────────────────────────────
# 主催行: organizer が出典名(kbuzzlab)のときは値を空にして行を抑制(出典は別途明記済み、重複回避)。
# 既存の取得行 "$organizer = $get( 'popup_organizer' );" の直後に判定を挿入。
C_OLD = "\t$organizer    = $get( 'popup_organizer' );\n"
C_NEW = (
    "\t$organizer    = $get( 'popup_organizer' );\n"
    "\t/* 主催が出典名(例 kbuzzlab)の場合は『主催』行を抑制(出典は本文末に別途明記済み、重複回避)。\n"
    "\t   実ブランド名が入っているときは表示を維持する。survey: 396/397=kbuzzlab, 398-400=空。 */\n"
    "\t$kpop_source_organizers = array( 'kbuzzlab' );\n"
    "\tif ( is_string( $organizer ) && in_array( strtolower( trim( $organizer ) ), $kpop_source_organizers, true ) ) {\n"
    "\t\t$organizer = '';\n"
    "\t}\n"
)

def main():
    for p in (CS, CSS, FN):
        if not os.path.isfile(p):
            die("missing file: " + p)

    print("[1/4] backup")
    backup(CS); backup(CSS); backup(FN)

    print("[2/4] Edit A: content-single.php (CTA move, popup-only)")
    t = open(CS, encoding="utf-8").read()
    t = replace_once(t, A_OLD, A_NEW, "A entry-content")
    t = replace_once(t, A2_OLD, A2_NEW, "A2 popup-block close")
    open(CS, "w", encoding="utf-8").write(t)

    print("[3/4] Edit B: style.css (6-color -> single brand pink)")
    s = open(CSS, encoding="utf-8").read()
    s = replace_once(s, B_OLD, B_NEW, "B border-image")
    open(CSS, "w", encoding="utf-8").write(s)

    print("      Edit C: functions.php (organizer label suppression)")
    f = open(FN, encoding="utf-8").read()
    f = replace_once(f, C_OLD, C_NEW, "C organizer")
    open(FN, "w", encoding="utf-8").write(f)

    print("[4/4] php -l syntax check")
    ok = True
    for p in (CS, FN):
        r = subprocess.run(["php", "-l", p], capture_output=True, text=True)
        print("  " + r.stdout.strip())
        if r.returncode != 0:
            print("  " + r.stderr.strip(), file=sys.stderr)
            ok = False
    if not ok:
        die("php -l failed — restore from .bak-%s and investigate." % STAMP)
    print("DONE. backups stamped .bak-%s . Next: cache flush + visual (396 PC/mobile)." % STAMP)

if __name__ == "__main__":
    main()
