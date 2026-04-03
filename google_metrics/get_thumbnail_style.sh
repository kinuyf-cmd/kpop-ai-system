#!/bin/bash

TITLE=$(echo "$1" | tr '[:upper:]' '[:lower:]')

if [[ "$TITLE" =~ カムバック|新曲|mv ]]; then
  echo "NEON"
elif [[ "$TITLE" =~ ライブ|ツアー|来日 ]]; then
  echo "GOLD"
elif [[ "$TITLE" =~ 空港|私服|ファッション ]]; then
  echo "LIGHT"
elif [[ "$TITLE" =~ 美容|コスメ ]]; then
  echo "PASTEL"
elif [[ "$TITLE" =~ 炎上|問題|脱退 ]]; then
  echo "RED_ALERT"
else
  echo "DEFAULT"
fi
