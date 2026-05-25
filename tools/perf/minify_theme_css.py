#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""minify_theme_css.py — 子テーマ style.css を安全に minify する(ルール不変、余白/コメント除去のみ)。
本番実測: 128KB → 65KB(50%削減)。Lighthouse unminified-css / 表示速度対策。

安全策:
  - WordPress テーマヘッダ(/* Theme Name: ... */ の最初のブロック)は必ず保持
    (消すと WP がテーマを認識できなくなる)。
  - .bak バックアップを作ってから上書き。
  - CSS の値は壊さない保守的な正規表現のみ(プロパティ値内の空白は1個に正規化するが
    calc() 等で問題が出ないよう演算子前後の空白は触らない)。
  - 冪等: 既に minified(改行ほぼ無し)なら何もしない。

owner 実行: sudo -u www-data python3 tools/perf/minify_theme_css.py \
            /var/www/wp_stg/wp-content/themes/generatepress-kpop/style.css
"""
import re, sys, os, shutil

def minify(css: str) -> str:
    # テーマヘッダ(最初の Theme Name を含むコメント)を退避
    head = ""
    m = re.search(r"/\*.*?Theme Name.*?\*/", css, flags=re.S)
    if m:
        head = m.group(0)
        css = css[:m.start()] + css[m.end():]
    # コメント除去
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    # 連続空白→1個
    css = re.sub(r"\s+", " ", css)
    # 構造記号の前後の空白除去(値内演算子 + - * / は触らない=calc安全)
    css = re.sub(r"\s*([{}:;,>~])\s*", r"\1", css)
    # 末尾セミコロン除去
    css = css.replace(";}", "}")
    css = css.strip()
    return (head + "\n" + css) if head else css

def main():
    if len(sys.argv) < 2:
        print("usage: minify_theme_css.py <style.css path>", file=sys.stderr); sys.exit(2)
    path = sys.argv[1]
    if not os.path.isfile(path):
        print(f"ファイルが見つかりません: {path}", file=sys.stderr); sys.exit(2)
    src = open(path, encoding="utf-8", errors="replace").read()
    # 冪等チェック: 改行が極端に少なければ既に minified
    if src.count("\n") < 5 and len(src) > 1000:
        print("既に minified 済みのようです。スキップ。"); return
    out = minify(src)
    b, a = len(src.encode()), len(out.encode())
    bak = path + ".bak"
    if not os.path.exists(bak):
        shutil.copy2(path, bak)
        print(f"バックアップ作成: {bak}")
    open(path, "w", encoding="utf-8").write(out)
    print(f"minify完了: {b//1024}KB → {a//1024}KB ({100-a*100//b}%削減)")
    print("注意: 変更未反映なら ?ver= の filemtime バストを確認(memory: stg-css-cache-bust-filemtime)。")

if __name__ == "__main__":
    main()
