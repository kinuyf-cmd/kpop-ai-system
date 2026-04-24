#!/bin/bash
# news-sitemap.xml と WordPress sitemaps を正しく配信するための nginx 設定パッチ
# 使い方: sudo bash scripts/fix_nginx_sitemap.sh
#
# 修正内容:
# 1. サーバーブロック外にある無効な location ブロックを削除
# 2. HTTPS サーバーブロック内に正しいパスで挿入
# 3. パスを static/ ディレクトリに変更（reports/ は pipeline symlink で消失する）

set -euo pipefail

NGINX_CONF="/etc/nginx/sites-available/kpopjournal"

# バックアップ
cp "$NGINX_CONF" "${NGINX_CONF}.bak.$(date +%Y%m%d%H%M%S)"

# 1. サーバーブロック外の無効な location ブロックを削除
sed -i '/^location = \/news-sitemap\.xml {/,/^}/d' "$NGINX_CONF"

# 2. 既に挿入済みの場合はパスだけ更新（冪等性）
if grep -q 'location = /news-sitemap.xml' "$NGINX_CONF"; then
    sed -i 's|alias .*/news-sitemap\.xml;|alias /home/aiuser/kpop-ai-system/static/news-sitemap.xml;|' "$NGINX_CONF"
    echo "既存ブロックのパスを更新"
else
    # "# All other routes" の前にサイトマップ用 location ブロックを挿入
    sed -i '/# All other routes → Next.js/i\
    # Google News Sitemap — ローカルXMLファイルを直接配信\
    location = /news-sitemap.xml {\
        alias /home/aiuser/kpop-ai-system/static/news-sitemap.xml;\
        default_type application/xml;\
        add_header Cache-Control "public, max-age=300";\
        add_header X-Robots-Tag "noindex";\
    }\
\
    # WordPress sitemaps — ConoHa Wingへプロキシ\
    location ~* ^/(sitemap.*\\.xml|wp-sitemap.*\\.xml)$ {\
        proxy_pass https://160.251.148.187/$1;\
        proxy_set_header Host www.kpopjournal.tokyo;\
        proxy_ssl_server_name on;\
        proxy_ssl_name www.kpopjournal.tokyo;\
        proxy_ssl_verify off;\
        add_header Cache-Control "public, max-age=3600";\
    }\
' "$NGINX_CONF"
    echo "新規 location ブロックを挿入"
fi

# 設定テスト
nginx -t

# リロード
systemctl reload nginx

echo "✅ nginx 設定更新完了"
echo "確認: curl -sI https://www.kpopjournal.tokyo/news-sitemap.xml | head -3"
