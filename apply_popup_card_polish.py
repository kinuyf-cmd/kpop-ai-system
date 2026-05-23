#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
KPOP JOURNAL stg — 開催情報box カード洗練(案1)。
  Edit D (functions.php): 住所/主催/予約/特典の dt+dd を per-item wrapper
                          <div class="kpop-popup-item ..."> で囲み、grid分割バグを根治。
  Edit E (style.css):     detail-list を「カード単位」grid に。dt/dd は wrapper 内で
                          縦積み(ラベル小→値大)。hero とトーン統一、余白/角丸/タイポ揃え。
                          --pp-* の AA検証済み 背景/文字 ペアは値を変えない(再検証不要)。

方針: exact-string アンカー、1回マッチ必須、バックアップ、php -l ゲート。
実行: sudo python3 apply_popup_card_polish.py
"""
import sys, os, time, shutil, subprocess

THEME = "/var/www/wp_stg/wp-content/themes/generatepress-kpop"
CSS = os.path.join(THEME, "style.css")
FN  = os.path.join(THEME, "functions.php")
STAMP = time.strftime("%Y%m%d%H%M%S")

def die(m): print("ABORT: "+m, file=sys.stderr); sys.exit(1)
def repl(t, old, new, label):
    n = t.count(old)
    if n != 1: die("%s: anchor matched %d times (expected 1)." % (label, n))
    return t.replace(old, new, 1)
def backup(p):
    b = p + ".bak-" + STAMP; shutil.copy2(p, b); print("  backup: " + b)

# ── Edit D: functions.php — per-item wrapper around dt+dd ───────────────────
D_OLD = """\t\techo '<dl class="kpop-popup-detail-list">';
\t\tforeach ( $rows as $r ) {
\t\t\tif ( ! $r['val'] ) { continue; }
\t\t\t$ccls = ' kpop-popup-row--' . sanitize_html_class( $r['color'] );
\t\t\techo '<dt class="kpop-popup-dt' . esc_attr( $ccls ) . '"><span class="kpop-popup-ic" aria-hidden="true">' . esc_html( $r['icon'] ) . '</span>' . esc_html( $r['label'] ) . '</dt>';
\t\t\techo '<dd class="kpop-popup-dd' . esc_attr( $ccls ) . '">' . nl2br( esc_html( $r['val'] ) ) . '</dd>';
\t\t}
\t\techo '</dl>';"""

D_NEW = """\t\techo '<dl class="kpop-popup-detail-list">';
\t\tforeach ( $rows as $r ) {
\t\t\tif ( ! $r['val'] ) { continue; }
\t\t\t$ccls = ' kpop-popup-row--' . sanitize_html_class( $r['color'] );
\t\t\t/* 住所分割バグ根治: dt+dd を1カード(.kpop-popup-item)で囲む。
\t\t\t   div in dl は HTML5 で valid。grid item が1カード=ラベルと値が分離しない。 */
\t\t\techo '<div class="kpop-popup-item' . esc_attr( $ccls ) . '">';
\t\t\techo '<dt class="kpop-popup-dt' . esc_attr( $ccls ) . '"><span class="kpop-popup-ic" aria-hidden="true">' . esc_html( $r['icon'] ) . '</span>' . esc_html( $r['label'] ) . '</dt>';
\t\t\techo '<dd class="kpop-popup-dd' . esc_attr( $ccls ) . '">' . nl2br( esc_html( $r['val'] ) ) . '</dd>';
\t\t\techo '</div>';
\t\t}
\t\techo '</dl>';"""

# ── Edit E: style.css — card-unit grid + unified dt/dd inside wrapper ────────
# 既存の detail-list grid + dt/dd ブロックを差し替え。--pp-* の色は別ルールで不変。
E_OLD = """.kpop-popup-detail-list {
\tdisplay: grid;
\tgrid-template-columns: repeat(auto-fill, minmax(15em, 1fr));
\tgap: 0.7em;
\tmargin: 0 0 0.4em;
}
.kpop-popup-dt {
\tdisplay: flex;
\talign-items: center;
\tgap: 0.4em;
\tfont-weight: 700;
\tpadding: 0.5em 0.8em 0.3em;
\tfont-size: 0.9em;
\tborder-radius: 12px 12px 0 0;
}
.kpop-popup-ic { font-size: 1.05em; line-height: 1; }
.kpop-popup-dd {
\tmargin: 0;
\tpadding: 0.15em 0.8em 0.65em;
\tcolor: var(--pp-ink); /* 不透明パステル背景上で 11.6〜12.8:1 の AAA */
\tline-height: 1.6;
\tborder-radius: 0 0 12px 12px;
\tword-break: break-word;
}"""

E_NEW = """.kpop-popup-detail-list {
\tdisplay: grid;
\tgrid-template-columns: repeat(auto-fill, minmax(16em, 1fr));
\tgap: 0.85em;
\tmargin: 0 0 0.4em;
\tpadding: 0; /* dl 既定 margin を打ち消す(GP リセット差異対策) */
}
/* 住所分割バグ根治: 各項目 = 1カード。dt(ラベル)とdd(値)はこの中で必ず縦積み。
   PC 多列でも 1カード=1 grid item なのでラベルと値が別カラムに割れない。 */
.kpop-popup-item {
\tdisplay: flex;
\tflex-direction: column;
\tborder-radius: 14px;
\toverflow: hidden;            /* 角丸を子の背景に効かせる */
\tbox-shadow: 0 1px 3px rgba(20, 20, 40, 0.05);
}
/* ラベル帯: 小さく控えめ(アイコン + ラベル)。値を主役にするためトーンを落とす。 */
.kpop-popup-dt {
\tdisplay: flex;
\talign-items: center;
\tgap: 0.45em;
\tfont-weight: 700;
\tpadding: 0.6em 0.95em 0.35em;
\tfont-size: 0.82em;
\tletter-spacing: 0.02em;
\tborder-radius: 0;
}
.kpop-popup-ic { font-size: 1.05em; line-height: 1; }
/* 値: 大きく主役。行間ゆったり、余白統一。 */
.kpop-popup-dd {
\tmargin: 0;
\tpadding: 0 0.95em 0.8em;
\tcolor: var(--pp-ink); /* 不透明パステル背景上で 11.6〜12.8:1 の AAA(値不変) */
\tfont-size: 1.05em;
\tfont-weight: 600;
\tline-height: 1.65;
\tborder-radius: 0;
\tword-break: break-word;
}"""

# モバイル: 1列(既存 @media が grid-template-columns:1fr を上書き)— そのまま機能。

def main():
    for p in (CSS, FN):
        if not os.path.isfile(p): die("missing: "+p)
    print("[1/3] backup"); backup(FN); backup(CSS)
    print("[2/3] Edit D: functions.php (per-item wrapper)")
    f = open(FN, encoding="utf-8").read()
    f = repl(f, D_OLD, D_NEW, "D wrapper")
    open(FN, "w", encoding="utf-8").write(f)
    print("       Edit E: style.css (card-unit grid + unified dt/dd)")
    s = open(CSS, encoding="utf-8").read()
    s = repl(s, E_OLD, E_NEW, "E detail-list css")
    open(CSS, "w", encoding="utf-8").write(s)
    print("[3/3] php -l")
    r = subprocess.run(["php", "-l", FN], capture_output=True, text=True)
    print("  " + r.stdout.strip())
    if r.returncode != 0:
        print("  " + r.stderr.strip(), file=sys.stderr)
        die("php -l failed — restore .bak-%s" % STAMP)
    print("DONE (.bak-%s). Next: cache flush + visual 607 (PC/mobile)." % STAMP)

if __name__ == "__main__":
    main()
