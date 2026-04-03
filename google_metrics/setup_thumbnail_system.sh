#!/bin/bash
set -e

mkdir -p ~/google_metrics

cat > ~/google_metrics/generate_thumbnail_text.sh << 'SH'
#!/bin/bash
TITLE="$1"

TEXT=$(claude --dangerously-skip-permissions -p "
あなたはK-POPメディアのサムネ編集者です。

以下のタイトルから"クリックされるサムネ文言"を作ってください。

【絶対ルール】
・8〜14文字
・インパクト重視
・1行のみ
・日本語
・誤字ゼロ
・説明文禁止
・句読点なるべく使わない

【禁止ワード】
修正 / サマリー / まとめました / 解説します / 分析します

タイトル:
$TITLE
" | tail -n 1)

TEXT=$(echo "$TEXT" | sed 's/修正//g' | sed 's/サマリー//g')

echo "$TEXT"
SH

chmod +x ~/google_metrics/generate_thumbnail_text.sh

cat > ~/google_metrics/get_thumbnail_style.sh << 'SH'
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
SH

chmod +x ~/google_metrics/get_thumbnail_style.sh

cat > ~/google_metrics/create_thumbnail.sh << 'SH'
#!/bin/bash

TITLE="$1"

TEXT=$(bash ~/google_metrics/generate_thumbnail_text.sh "$TITLE")
STYLE=$(bash ~/google_metrics/get_thumbnail_style.sh "$TITLE")

python3 - << PY
from PIL import Image, ImageDraw, ImageFont

img = Image.new("RGB", (1200, 675))

style = "$STYLE"

if style == "NEON":
    bg = (255, 20, 80)
elif style == "GOLD":
    bg = (180, 150, 60)
elif style == "LIGHT":
    bg = (240, 240, 240)
elif style == "PASTEL":
    bg = (255, 220, 230)
elif style == "RED_ALERT":
    bg = (200, 0, 0)
else:
    bg = (30, 30, 30)

img.paste(bg, [0,0,1200,675])

draw = ImageDraw.Draw(img)

try:
    font = ImageFont.truetype("/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc", 90)
except:
    font = ImageFont.load_default()

text = "$TEXT"

bbox = draw.textbbox((0,0), text, font=font)
w = bbox[2] - bbox[0]
h = bbox[3] - bbox[1]

x = (1200 - w) // 2
y = (675 - h) // 2

draw.text((x,y), text, fill=(255,255,255), font=font)

img.save("/tmp/thumb.jpg")
print("/tmp/thumb.jpg")
PY
SH

chmod +x ~/google_metrics/create_thumbnail.sh

echo "✅ サムネ自動生成システム導入完了"
