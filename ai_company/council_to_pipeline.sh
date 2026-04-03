#!/bin/bash
# council_to_pipeline.sh
# 合議システムで承認された記事をkpop_pipelineの投稿フローに流す

set -e

FINAL="$HOME/ai_company/council_final.md"

if [ ! -f "$FINAL" ]; then
  echo "❌ council_final.md が見つかりません。先に agent_council.sh を実行してください。"
  exit 1
fi

echo "=== 合議承認記事をパイプラインへ投入 ==="

# 記事をreports/2_checked.mdとして配置（パイプラインのジラーチ後フローへ）
mkdir -p ~/reports
cp "$FINAL" ~/reports/2_checked.md

echo "✅ ~/reports/2_checked.md にセット完了"
echo "続けてkpop_pipeline.shの投稿処理を実行中..."

# パイプラインの投稿処理部分のみ実行
bash ~/kpop_pipeline.sh --from-council 2>/dev/null || {
  # --from-councilオプションがない場合はフル実行
  # reports/2_checked.mdを使うため重複生成はスキップ
  echo "投稿はWordPress APIで直接実行します"

  TITLE=$(head -n 1 ~/reports/2_checked.md)
  CONTENT=$(tail -n +3 ~/reports/2_checked.md)

  TODAY=$(date '+%Y年%m月%d日')

  SLUG=$(claude -p "
以下のタイトルをSEOに強い英語スラッグに変換せよ。
小文字英数字とハイフンのみ。30〜50文字。1行のみ。
タイトル：$TITLE
" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9-]/-/g' | sed 's/-\+/-/g' | sed 's/^-\|-$//' | cut -c1-60)

  [ -z "$SLUG" ] && SLUG="kpop-council-$(date '+%Y%m%d-%H%M')"

  echo "タイトル: $TITLE"
  echo "スラッグ: $SLUG"

  python3 - << PY
import json, urllib.request, base64

title = open('/tmp/council_title.txt', 'w').write("""$TITLE""") or open('/tmp/council_title.txt').read()
content = """$CONTENT"""
slug = "$SLUG"

auth = base64.b64encode(b"kpop-bot:afX1 yOFd nlrp I751 3XgW zMmM").decode()
headers = {
    "Authorization": "Basic " + auth,
    "Content-Type": "application/json"
}

payload = json.dumps({
    "title": "$TITLE",
    "content": content,
    "status": "publish",
    "slug": slug,
}, ensure_ascii=False).encode()

req = urllib.request.Request(
    "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts",
    data=payload,
    headers=headers
)
with urllib.request.urlopen(req) as res:
    data = json.loads(res.read())
    print("投稿完了:", data.get("link"))
    print("記事ID:", data.get("id"))
PY
}
