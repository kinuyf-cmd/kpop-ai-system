#!/usr/bin/env python3
"""M-final: 取り込み記事のインライン color/background をstyleから除去する。

救出記事のコールアウトボックスに41種のバラバラなインライン色があり、少数の
CSSクラスに集約できないため機械除去を採用(citation §7-2準拠 + WCAG AA担保)。
style属性から `color:` / `background:` / `background-color:` 宣言のみ削除し、
border/padding/margin/border-radius 等の構造プロパティは保持する。
空になった style="" は属性ごと削除。

mysql 直接 UPDATE(stg DBは /tmp/wp_stg.txt 認証で接続可)。
--dry-run(既定): 変更プレビュー。--apply: 実UPDATE。
"""
import argparse
import re
import subprocess

WP_STG_TXT = "/tmp/wp_stg.txt"


def db_conf():
    conf = {}
    for line in open(WP_STG_TXT):
        m = re.match(r'^(WP_DB_\w+)=(.*)$', line.strip())
        if m:
            conf[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return conf


def mysql(sql, conf, fetch=True):
    cmd = ["mysql", f"-u{conf['WP_DB_USER']}", f"-p{conf['WP_DB_PASSWORD']}",
           conf["WP_DB_NAME"], "-N", "-e", sql]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    return r.stdout, r.stderr


def strip_colors(html):
    """style属性から color/background 宣言を除去。空styleは属性削除。"""
    def fix_style(m):
        decls = m.group(1).split(";")
        kept = [d for d in decls
                if d.strip() and not re.match(r'\s*(color|background|background-color)\s*:', d, re.I)]
        if not kept:
            return ""  # style属性ごと削除
        return 'style="' + ";".join(d.strip() for d in kept) + '"'
    return re.sub(r'style="([^"]*)"', fix_style, html)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--ids", help="対象IDをカンマ区切りで限定(検証用)")
    args = ap.parse_args()
    conf = db_conf()

    if args.ids:
        ids = [x.strip() for x in args.ids.split(",") if x.strip().isdigit()]
    else:
        # 対象: draft で color/background を含む記事
        out, _ = mysql(
            "SELECT ID FROM wp_posts WHERE post_type='post' AND post_status='draft' "
            "AND (post_content LIKE '%style=%color:%' OR post_content LIKE '%style=%background:%');",
            conf)
        ids = [x for x in out.split() if x.isdigit()]
    print(f"対象記事: {len(ids)}件")

    import tempfile, os
    changed = 0
    for pid in ids:
        # HEX経由で取得(TO_BASE64は76文字毎に改行混入しデコード破損するため)
        out, _ = mysql(f"SELECT HEX(post_content) FROM wp_posts WHERE ID={pid};", conf)
        hexstr = re.sub(r"\s+", "", out)
        body = bytes.fromhex(hexstr).decode("utf-8", "replace")
        new = strip_colors(body)
        before_n = len(re.findall(r'(color|background)\s*:', body, re.I))
        after_n = len(re.findall(r'(color|background)\s*:', new, re.I))
        if new != body:
            changed += 1
            print(f"  ID{pid}: color/background宣言 {before_n}→{after_n}")
            if args.apply:
                # UPDATE も HEX(UNHEX)で安全に受け渡し
                new_hex = new.encode("utf-8").hex()
                with tempfile.NamedTemporaryFile("w", suffix=".sql", delete=False) as f:
                    f.write(f"UPDATE wp_posts SET post_content=UNHEX('{new_hex}') WHERE ID={pid};")
                    sqlpath = f.name
                cmd = ["mysql", f"-u{conf['WP_DB_USER']}", f"-p{conf['WP_DB_PASSWORD']}",
                       conf["WP_DB_NAME"]]
                with open(sqlpath) as sf:
                    subprocess.run(cmd, stdin=sf, capture_output=True, text=True, timeout=60)
                os.unlink(sqlpath)
    print(f"\n=== {'UPDATE適用' if args.apply else 'DRY(変更なし)'}: {changed}件 ===")
    if not args.apply:
        print("実適用は --apply。mysql UPDATE(sudo不要、stg DB認証で実行)。")


if __name__ == "__main__":
    main()
