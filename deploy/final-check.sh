#!/bin/bash
# ──────────────────────────────────────────────
# DNS切り替え後の最終確認スクリプト
# ──────────────────────────────────────────────
set -uo pipefail

PASS=0
FAIL=0
WARN=0

check() {
    if [ "$1" = "OK" ]; then
        echo "  ✓ $2"
        PASS=$((PASS+1))
    elif [ "$1" = "WARN" ]; then
        echo "  ⚠ $2"
        WARN=$((WARN+1))
    else
        echo "  ✗ $2"
        FAIL=$((FAIL+1))
    fi
}

echo "╔══════════════════════════════════════════╗"
echo "║  kpopjournal.tokyo 最終確認              ║"
echo "╚══════════════════════════════════════════╝"
echo "Date: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# ── 1. DNS ───────────────────────────────────
echo "=== 1. DNS確認 ==="
NAKED_IP=$(dig kpopjournal.tokyo +short 2>/dev/null)
WWW_IP=$(dig www.kpopjournal.tokyo +short 2>/dev/null)
VPS_IP="163.44.96.56"

echo "  kpopjournal.tokyo     → $NAKED_IP"
echo "  www.kpopjournal.tokyo → $WWW_IP"

[ "$NAKED_IP" = "$VPS_IP" ] && check OK "naked domain → VPS ($VPS_IP)" || check FAIL "naked domain: expected $VPS_IP, got $NAKED_IP"
[ "$WWW_IP" = "$VPS_IP" ] && check OK "www domain → VPS ($VPS_IP)" || check FAIL "www domain: expected $VPS_IP, got $WWW_IP"
echo ""

# ── 2. Next.js (localhost) ───────────────────
echo "=== 2. Next.js (localhost:3000) ==="
NEXT_STATUS=$(curl -sI http://localhost:3000 2>/dev/null | head -1 | tr -d '\r')
echo "  $NEXT_STATUS"
echo "$NEXT_STATUS" | grep -q "200" && check OK "Next.js responding" || check FAIL "Next.js not responding"
echo ""

# ── 3. nginx (localhost:80) ──────────────────
echo "=== 3. nginx (HTTP) ==="
NGINX_STATUS=$(curl -sI http://localhost 2>/dev/null | head -1 | tr -d '\r')
echo "  $NGINX_STATUS"
echo "$NGINX_STATUS" | grep -qE "200|301" && check OK "nginx proxy working" || check FAIL "nginx not proxying"
echo ""

# ── 4. HTTPS ─────────────────────────────────
echo "=== 4. HTTPS (SSL) ==="
SSL_STATUS=$(curl -sI https://www.kpopjournal.tokyo 2>/dev/null | head -1 | tr -d '\r')
if [ -n "$SSL_STATUS" ]; then
    echo "  $SSL_STATUS"
    echo "$SSL_STATUS" | grep -q "200" && check OK "HTTPS working" || check WARN "HTTPS responded but not 200: $SSL_STATUS"

    # Check certificate
    SSL_EXPIRE=$(echo | openssl s_client -servername www.kpopjournal.tokyo -connect www.kpopjournal.tokyo:443 2>/dev/null | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)
    if [ -n "$SSL_EXPIRE" ]; then
        echo "  Certificate expires: $SSL_EXPIRE"
        check OK "SSL certificate valid"
    else
        check WARN "Could not read SSL certificate expiry"
    fi
else
    echo "  (no response)"
    check WARN "HTTPS not yet configured (run certbot after DNS propagation)"
fi
echo ""

# ── 5. Response headers ──────────────────────
echo "=== 5. レスポンスヘッダー ==="
HEADERS=$(curl -sI https://www.kpopjournal.tokyo 2>/dev/null || curl -sI http://localhost 2>/dev/null)

echo "$HEADERS" | grep -qi "X-Frame-Options" && check OK "X-Frame-Options present" || check WARN "X-Frame-Options missing"
echo "$HEADERS" | grep -qi "X-Content-Type-Options" && check OK "X-Content-Type-Options present" || check WARN "X-Content-Type-Options missing"
echo "$HEADERS" | grep -qi "Strict-Transport-Security" && check OK "HSTS present" || check WARN "HSTS missing (add after SSL)"

# Server header leak
echo "$HEADERS" | grep -qi "X-Powered-By: Next.js" && check WARN "X-Powered-By header exposed (consider removing)" || check OK "X-Powered-By not leaked"
echo ""

# ── 6. WordPress API proxy ───────────────────
echo "=== 6. WordPress API ==="

# wp/v2
WP_V2=$(curl -s -o /dev/null -w "%{http_code}" https://www.kpopjournal.tokyo/wp-json/wp/v2/posts?per_page=1 2>/dev/null || curl -s -o /dev/null -w "%{http_code}" http://localhost/wp-json/wp/v2/posts?per_page=1 2>/dev/null)
echo "  /wp-json/wp/v2/posts → HTTP $WP_V2"
[ "$WP_V2" = "200" ] && check OK "WordPress REST API (wp/v2)" || check FAIL "WordPress REST API not reachable (HTTP $WP_V2)"

# kpopjournal/v1
KPJ_V1=$(curl -s -o /dev/null -w "%{http_code}" https://www.kpopjournal.tokyo/wp-json/kpopjournal/v1/home 2>/dev/null || curl -s -o /dev/null -w "%{http_code}" http://localhost/wp-json/kpopjournal/v1/home 2>/dev/null)
echo "  /wp-json/kpopjournal/v1/home → HTTP $KPJ_V1"
[ "$KPJ_V1" = "200" ] && check OK "Custom API (kpopjournal/v1)" || check WARN "Custom API returned HTTP $KPJ_V1"

# Check for proxy loop (response should come back within 5s)
LOOP_CHECK=$(timeout 5 curl -s -o /dev/null -w "%{time_total}" http://localhost/wp-json/wp/v2/posts?per_page=1 2>/dev/null)
if [ -n "$LOOP_CHECK" ]; then
    SLOW=$(echo "$LOOP_CHECK > 4" | bc 2>/dev/null || echo 0)
    [ "$SLOW" = "1" ] && check FAIL "WP API slow (${LOOP_CHECK}s) — possible proxy loop!" || check OK "WP API response time: ${LOOP_CHECK}s"
fi
echo ""

# ── 7. Static assets ─────────────────────────
echo "=== 7. 静的アセットキャッシュ ==="
STATIC_CACHE=$(curl -sI http://localhost/_next/static/test 2>/dev/null | grep -i cache-control | tr -d '\r')
if [ -n "$STATIC_CACHE" ]; then
    echo "  $STATIC_CACHE"
    echo "$STATIC_CACHE" | grep -qi "immutable" && check OK "_next/static immutable cache" || check WARN "Cache-Control missing immutable"
else
    check WARN "Could not verify static cache headers"
fi
echo ""

# ── 8. PM2 ───────────────────────────────────
echo "=== 8. PM2 ==="
PM2_STATUS=$(pm2 list --no-color 2>/dev/null)
echo "$PM2_STATUS"
echo "$PM2_STATUS" | grep -q "online" && check OK "PM2 process online" || check FAIL "PM2 process not online"
echo ""

# ── 9. nginx service ─────────────────────────
echo "=== 9. nginx service ==="
NGINX_ACTIVE=$(systemctl is-active nginx 2>/dev/null)
NGINX_ENABLED=$(systemctl is-enabled nginx 2>/dev/null)
echo "  Active: $NGINX_ACTIVE"
echo "  Enabled: $NGINX_ENABLED"
[ "$NGINX_ACTIVE" = "active" ] && check OK "nginx running" || check FAIL "nginx not running"
[ "$NGINX_ENABLED" = "enabled" ] && check OK "nginx autostart enabled" || check WARN "nginx autostart not enabled"
echo ""

# ── 10. gzip ─────────────────────────────────
echo "=== 10. gzip圧縮 ==="
GZIP=$(curl -sI -H 'Accept-Encoding: gzip' http://localhost 2>/dev/null | grep -i 'content-encoding' | tr -d '\r')
if [ -n "$GZIP" ]; then
    echo "  $GZIP"
    check OK "gzip enabled"
else
    check WARN "gzip not detected (response may be too small)"
fi
echo ""

# ── Summary ──────────────────────────────────
echo "╔══════════════════════════════════════════╗"
echo "║  結果                                    ║"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "  ✓ PASS: $PASS"
echo "  ⚠ WARN: $WARN"
echo "  ✗ FAIL: $FAIL"
echo ""

if [ "$FAIL" -eq 0 ] && [ "$WARN" -eq 0 ]; then
    echo "  全チェック通過！本番稼働OK"
elif [ "$FAIL" -eq 0 ]; then
    echo "  基本機能OK。警告項目を確認してください。"
else
    echo "  失敗項目あり。修正が必要です。"
fi
