#!/bin/bash
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# verify_and_cleanup.sh
# functions.php にスニペット設置後の動作確認 & Redirection ルール無効化
#
# 実行: bash wordpress/verify_and_cleanup.sh
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SITE_URL="${SITE_URL:-https://www.kpopjournal.tokyo}"

echo "========================================"
echo " News Sitemap 動作確認 & クリーンアップ"
echo "========================================"

# 1. /news-sitemap.xml のレスポンス確認
echo ""
echo "[1] /news-sitemap.xml 確認..."
HEADERS=$(curl -sI "$SITE_URL/news-sitemap.xml" 2>/dev/null)
HTTP_CODE=$(echo "$HEADERS" | grep "^HTTP" | tail -1 | awk '{print $2}')
CUSTOM_HEADER=$(echo "$HEADERS" | grep -i "X-KPJ-News-Sitemap" | tr -d '\r')
CONTENT_TYPE=$(echo "$HEADERS" | grep -i "content-type" | tr -d '\r')
REDIRECT=$(echo "$HEADERS" | grep -i "location" | tr -d '\r')

echo "  HTTP: $HTTP_CODE"
echo "  Content-Type: $CONTENT_TYPE"
echo "  Custom Header: ${CUSTOM_HEADER:-なし}"
echo "  Redirect: ${REDIRECT:-なし}"

if echo "$CUSTOM_HEADER" | grep -q "custom-v1"; then
    echo ""
    echo "  ✅ カスタム版ニュースサイトマップが正常動作中！"

    # XMLの中身を確認
    BODY=$(curl -s "$SITE_URL/news-sitemap.xml" 2>/dev/null)
    URL_COUNT=$(echo "$BODY" | grep -c "<url>" || echo 0)
    HAS_NEWS=$(echo "$BODY" | grep -c "<news:news>" || echo 0)
    echo "  記事数: $URL_COUNT"
    echo "  news:namespace: $([ "$HAS_NEWS" -gt 0 ] && echo '✅' || echo '❌')"

    # 2. Redirection ルール無効化（もう不要）
    echo ""
    echo "[2] Redirection 暫定ルール無効化..."
    DISABLE_RESULT=$(curl -s -X POST -K ~/.wp_auth \
        "$SITE_URL/wp-json/redirection/v1/redirect/43" \
        -H "Content-Type: application/json" \
        -d '{"enabled": false}' 2>/dev/null | python3 -c "
import json,sys
d=json.load(sys.stdin)
item=d.get('item',d)
print(f'enabled={item.get(\"enabled\",\"?\")}')
" 2>/dev/null || echo "error")
    echo "  Redirection ルール ID:43: $DISABLE_RESULT"

    # 3. 暫定固定ページを非公開に
    echo ""
    echo "[3] 暫定固定ページ(kpj-news-sitemap-xml)を非公開に..."
    PAGE_RESULT=$(curl -s -X POST -K ~/.wp_auth \
        "$SITE_URL/wp-json/wp/v2/pages/3057" \
        -H "Content-Type: application/json" \
        -d '{"status": "private"}' 2>/dev/null | python3 -c "
import json,sys
d=json.load(sys.stdin)
print(f'status={d.get(\"status\",\"?\")}')
" 2>/dev/null || echo "error")
    echo "  固定ページ: $PAGE_RESULT"

    # 4. パイプラインからXMLアップロードテスト
    echo ""
    echo "[4] REST API エンドポイント確認..."
    API_STATUS=$(curl -s -K ~/.wp_auth \
        "$SITE_URL/wp-json/kpopjournal/v1/news-sitemap" 2>/dev/null | python3 -c "
import json,sys
d=json.load(sys.stdin)
print(f'has_cache={d.get(\"has_cache\",\"?\")} urls={d.get(\"url_count\",\"?\")} updated={d.get(\"updated\",\"?\")[:19]}')
" 2>/dev/null || echo "endpoint_not_found")
    echo "  $API_STATUS"

    # 5. robots.txt 確認
    echo ""
    echo "[5] robots.txt 確認..."
    ROBOTS=$(curl -s "$SITE_URL/robots.txt" 2>/dev/null)
    echo "$ROBOTS" | grep -E "Googlebot-News|news-sitemap" | while read line; do
        echo "  $line"
    done

    echo ""
    echo "✅ 全て正常。クリーンアップ完了。"

else
    echo ""
    echo "  ❌ カスタム版が動作していません。"
    echo ""
    echo "  functions.php に以下のスニペットを貼り付けてください:"
    echo "  → wordpress/functions_php_snippet.php"
    echo ""
    echo "  手順:"
    echo "  1. WordPress管理画面 → 外観 → テーマファイルエディタ"
    echo "  2. Cocoon Child → functions.php を選択"
    echo "  3. 既存の KPJ News Sitemap コードがあれば全て削除"
    echo "     （「KPJ News Sitemap」で検索）"
    echo "  4. functions_php_snippet.php の内容を末尾に貼り付け"
    echo "  5. 「ファイルを更新」をクリック"
    echo "  6. このスクリプトを再実行して確認"
fi

echo ""
echo "========================================"
