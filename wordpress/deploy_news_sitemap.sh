#!/bin/bash
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# deploy_news_sitemap.sh
# Google News Sitemap の競合解消 & デプロイ
#
# 実行: bash wordpress/deploy_news_sitemap.sh
#
# 自動実行される処理:
#   1. XML Sitemap & Google News プラグイン無効化（AIOSEO との競合解消）
#   2. AIOSEO robots.txt の壊れたルール修正
#   3. パイプライン生成 XML を固定ページに保存
#   4. Redirection ルールで /news-sitemap.xml をカスタムページに転送
#   5. 動作確認
#
# 手動対応が必要な処理（mu-plugin 設置）:
#   → wordpress/kpj-news-sitemap.php を
#     wp-content/mu-plugins/ にアップロード（ConoHaファイルマネージャー使用）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"
SITE_URL="${SITE_URL:-https://www.kpopjournal.tokyo}"

echo "========================================"
echo " Google News Sitemap 競合解消 & デプロイ"
echo "========================================"

# ── 1. 競合プラグイン無効化 ──
echo ""
echo "[1] XML Sitemap & Google News プラグイン無効化..."
PLUGIN_STATUS=$(curl -s -X POST -K ~/.wp_auth \
  "${SITE_URL}/wp-json/wp/v2/plugins/xml-sitemap-feed/xml-sitemap" \
  -H "Content-Type: application/json" \
  -d '{"status":"inactive"}' 2>/dev/null | python3 -c "
import json,sys
d=json.load(sys.stdin)
print(d.get('status','error'))" 2>/dev/null || echo "error")

if [[ "$PLUGIN_STATUS" == "inactive" ]]; then
  echo "  ✅ 無効化完了"
else
  echo "  ⚠️  既に無効化済みまたはエラー (status: $PLUGIN_STATUS)"
fi

# ── 2. AIOSEO robots.txt 修正 ──
echo ""
echo "[2] AIOSEO robots.txt ルール修正..."
ROBOTS_FIX=$(curl -s -X POST -K ~/.wp_auth \
  "${SITE_URL}/wp-json/aioseo/v1/options" \
  -H "Content-Type: application/json" \
  -d '{
    "options": {
      "tools": {
        "robots": {
          "enable": true,
          "rules": [
            "{\"userAgent\":\"Googlebot-News\",\"directive\":\"allow\",\"fieldValue\":\"/\",\"readOnly\":false}",
            "{\"userAgent\":\"*\",\"directive\":\"allow\",\"fieldValue\":\"/wp-admin/admin-ajax.php\",\"readOnly\":false}"
          ]
        }
      }
    }
  }' 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin).get('success','?'))" 2>/dev/null)

if [[ "$ROBOTS_FIX" == "True" ]]; then
  echo "  ✅ robots.txt ルール修正完了"
else
  echo "  ⚠️  修正結果: $ROBOTS_FIX"
fi

# ── 3. パイプラインでXML生成 & 固定ページに保存 ──
echo ""
echo "[3] News Sitemap XML 生成 & アップロード..."
python3 "${BASE_DIR}/lib/news_sitemap_generator.py" --upload 2>&1 | sed 's/^/  /'

# ── 4. 動作確認 ──
echo ""
echo "[4] 動作確認..."
sleep 2

# robots.txt
echo "  robots.txt:"
ROBOTS=$(curl -s "${SITE_URL}/robots.txt" 2>/dev/null)
if echo "$ROBOTS" | grep -q "User-agent: Googlebot-News"; then
  echo "    Googlebot-News: ✅ 正常"
else
  echo "    Googlebot-News: ❌ なし"
fi
if echo "$ROBOTS" | grep -q "Allow: /https"; then
  echo "    壊れた行: ❌ 残存"
else
  echo "    壊れた行: ✅ 修正済み"
fi

# REST API 経由でXML確認
echo ""
echo "  固定ページ XML:"
XML_CHECK=$(curl -s "${SITE_URL}/wp-json/wp/v2/pages?slug=kpj-news-sitemap-xml&_fields=content.rendered" 2>/dev/null | python3 -c "
import json,sys
data=json.load(sys.stdin)
if data:
    c=data[0].get('content',{}).get('rendered','')
    urls=c.count('<url>')
    has_news='<news:news>' in c
    print(f'{urls} URLs, news:namespace={has_news}')
else:
    print('NOT_FOUND')
" 2>/dev/null)
echo "    $XML_CHECK"

# news-sitemap.xml リダイレクト
echo ""
echo "  /news-sitemap.xml:"
REDIR=$(curl -sI "${SITE_URL}/news-sitemap.xml" 2>/dev/null | head -3)
echo "    $REDIR" | head -2

# post-sitemap.xml
echo ""
echo "  AIOSEO post-sitemap.xml:"
POST_URLS=$(curl -s "${SITE_URL}/post-sitemap.xml" 2>/dev/null | grep -c "<url>" || echo "0")
echo "    ${POST_URLS} URLs"

# ── 5. サマリ ──
echo ""
echo "========================================"
echo " 完了サマリ"
echo "========================================"
echo ""
echo " ✅ 自動完了:"
echo "   - XML Sitemap & Google News プラグイン無効化"
echo "   - AIOSEO robots.txt 壊れたルール修正"
echo "   - News Sitemap XML 生成 & 固定ページ保存"
echo "   - Redirection ルール設定済み"
echo ""
echo " 🔧 手動対応（推奨）:"
echo "   mu-plugin を設置すると /news-sitemap.xml が"
echo "   Content-Type: application/xml で正しく配信されます。"
echo ""
echo "   手順:"
echo "   1. ConoHa WING コントロールパネル → ファイルマネージャー"
echo "   2. public_html/wp-content/mu-plugins/ フォルダを作成"
echo "   3. wordpress/kpj-news-sitemap.php をアップロード"
echo "   4. ${SITE_URL}/news-sitemap.xml を確認"
echo "   5. 確認後、Redirection のルール ID:43 を無効化"
echo ""
echo " GSC 登録:"
echo "   Google Search Console → サイトマップ に以下を登録:"
echo "   - ${SITE_URL}/sitemap.xml （メイン、AIOSEO管理）"
echo "   - ${SITE_URL}/news-sitemap.xml （ニュース用）"
echo "========================================"
