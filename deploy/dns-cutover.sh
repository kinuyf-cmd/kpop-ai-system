#!/bin/bash
# ──────────────────────────────────────────────
# DNS Cutover — kpopjournal.tokyo
# ──────────────────────────────────────────────
# Run BEFORE changing DNS at ConoHa Wing.
#
# Order of operations:
#   1. Run this script (updates nginx to use IP-direct WP proxy)
#   2. Change DNS at ConoHa Wing
#   3. Wait for propagation
#   4. Run certbot for SSL
# ──────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NGINX_CONF="/etc/nginx/sites-available/kpopjournal"
BACKUP="/root/nginx-pre-dns-$(date +%Y%m%d_%H%M%S).conf"

echo "=== DNS Cutover Preparation ==="
echo ""

# Step 1: Backup current config
echo "[1/4] Backing up current nginx config..."
sudo cp "$NGINX_CONF" "$BACKUP"
echo "  → Backup: $BACKUP"

# Step 2: Update nginx — switch WP proxy from domain to IP
echo ""
echo "[2/4] Updating nginx config (WP proxy → IP direct)..."

# Replace domain-based WP proxy with IP-based (prevent loop after DNS switch)
sudo sed -i \
    's|proxy_pass https://www\.kpopjournal\.tokyo/|proxy_pass https://160.251.148.187/|g' \
    "$NGINX_CONF"

echo "  ✓ proxy_pass updated: www.kpopjournal.tokyo → 160.251.148.187"

# Step 3: Test & reload
echo ""
echo "[3/4] Testing nginx config..."
if sudo nginx -t 2>&1; then
    echo "  ✓ Syntax OK"
    sudo systemctl reload nginx
    echo "  ✓ nginx reloaded"
else
    echo "  ✗ Syntax error! Rolling back..."
    sudo cp "$BACKUP" "$NGINX_CONF"
    sudo systemctl reload nginx
    echo "  Rolled back to backup."
    exit 1
fi

# Step 4: Verify WP API still works via IP
echo ""
echo "[4/4] Verifying WordPress API..."
STATUS=$(curl -sI http://localhost/wp-json/wp/v2/posts?per_page=1 | head -1)
echo "  WP API: $STATUS"

echo ""
echo "=== Ready for DNS cutover ==="
echo ""
echo "ConoHa Wing DNS settings:"
echo "  Type: A    Name: @    Value: 163.44.96.56"
echo "  Type: A    Name: www  Value: 163.44.96.56"
echo ""
echo "After DNS propagation (~5-30 min):"
echo "  1. Verify: dig www.kpopjournal.tokyo +short  (should show 163.44.96.56)"
echo "  2. SSL:    sudo certbot --nginx -d kpopjournal.tokyo -d www.kpopjournal.tokyo"
echo "  3. Test:   curl -I https://www.kpopjournal.tokyo"
