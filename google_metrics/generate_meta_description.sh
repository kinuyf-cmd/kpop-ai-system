#!/bin/bash
TITLE="$1"
CONTENT="$2"

META=$(claude -p "
あなたはK-POPメディアのSEO担当です。

以下の記事からmeta descriptionを1つ作成してください。

【ルール】
・70〜120文字
・アーティスト名を入れる
・何が分かる記事か明確に
・煽りすぎ禁止
・1行のみ出力

タイトル:
$TITLE

本文:
$CONTENT
" | tail -n 1)

META=$(echo "$META" | tr '\n' ' ' | sed 's/  */ /g')
echo "$META"
