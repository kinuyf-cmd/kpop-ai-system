#!/bin/bash
TITLE="$1"

TEXT=$(claude --dangerously-skip-permissions -p "
K-POPサムネイル用のテキストを1行だけ出力せよ。

条件：
- 8〜14文字
- 日本語のみ
- インパクトある短文
- 前置き・説明・記号一切禁止
- 出力はテキストのみ（「」や説明文禁止）

禁止ワード：CLICKされる / 速報デザイン / サムネ文言 / 修正 / サマリー / まとめ / 解説 / 分析

タイトル：$TITLE

出力例：
衝撃の新曲解禁
" | grep -v "^$" | grep -v "^#" | tail -n 1)

TEXT=$(echo "$TEXT" | sed 's/修正//g' | sed 's/サマリー//g' | sed 's/CLICKされる//g' | sed 's/速報デザイン//g' | sed 's/サムネ文言//g')

echo "$TEXT"
