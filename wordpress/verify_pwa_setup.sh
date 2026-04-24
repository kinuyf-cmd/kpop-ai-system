#!/bin/bash
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━��
# PWA セット���ップ検証スクリプト
# WPCodeスニペット設置後に実行
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
set -uo pipefail
SITE="${SITE_URL:-https://www.kpopjournal.tokyo}"
PASS=0
FAIL=0

check() {
    local label="$1" url="$2" expect="$3"
    local headers
    headers=$(curl -sI "$url" 2>&1)
    local status=$(echo "$headers" | head -1 | awk '{print $2}')
    local ct=$(echo "$headers" | grep -i "^content-type:" | head -1 | tr -d '\r')

    if echo "$headers" | grep -qi "$expect"; then
        echo "  ✅ ${label}: ${status} ${ct}"
        ((PASS++))
    else
        echo "  ❌ ${label}: ${status} ${ct} (expected: ${expect})"
        ((FAIL++))
    fi
}

echo "════════════════════════════════════════"
echo " PWA セットアップ検証"
echo "════════════════════════════════════════"
echo ""

echo "[1] エンドポイント確認"
check "manifest.json" "${SITE}/manifest.json" "application/manifest+json"
check "sw.js" "${SITE}/sw.js" "application/javascript"
check "SW-Allowed header" "${SITE}/sw.js" "service-worker-allowed"
check "uploads/sw.js" "${SITE}/wp-content/uploads/2026/04/kpj-sw.js" "application/javascript"
echo ""

echo "[2] manifest.json 内容確認"
manifest=$(curl -s "${SITE}/manifest.json" 2>&1)
if echo "$manifest" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['name']=='K-POP Journal'" 2>/dev/null; then
    echo "  ✅ manifest.json は有効なJSON (name=K-POP Journal)"
    ((PASS++))
else
    echo "  ❌ manifest.json が無効またはアクセス不可"
    ((FAIL++))
fi
echo ""

echo "[3] HTMLヘッダー確認"
html=$(curl -s "${SITE}/" 2>&1)
for tag in 'rel="manifest"' 'theme-color' 'apple-mobile-web-app-capable' 'apple-touch-icon'; do
    if echo "$html" | grep -q "$tag"; then
        echo "  ✅ <head> に ${tag} あり"
        ((PASS++))
    else
        echo "  ❌ <head> に ${tag} なし"
        ((FAIL++))
    fi
done
echo ""

echo "[4] SW登録スクリプト確認"
if echo "$html" | grep -q "serviceWorker.register"; then
    echo "  ✅ SW登録スクリプトあり"
    ((PASS++))
else
    echo "  ❌ SW登録スクリプトなし"
    ((FAIL++))
fi
echo ""

echo "[5] REST API エンドポイント確認"
for ep in "kpopjournal/v1/comment-reaction" "kpopjournal/v1/webpush/subscribe"; do
    status=$(curl -s -o /dev/null -w "%{http_code}" "${SITE}/wp-json/${ep}" 2>&1)
    # 400/405 = endpoint exists but method/params wrong (OK)
    # 404 = not registered
    if [[ "$status" != "404" ]]; then
        echo "  ✅ ${ep}: ${status} (registered)"
        ((PASS++))
    else
        echo "  ❌ ${ep}: 404 (not registered)"
        ((FAIL++))
    fi
done
echo ""

echo "════════════════════════════════════════"
echo " 結果: ✅ ${PASS} passed / ❌ ${FAIL} failed"
echo "════════════════════════════════════════"
