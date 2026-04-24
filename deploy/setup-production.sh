#!/bin/bash
# ──────────────────────────────────────────────────────────────
# kpopjournal.tokyo — Production server setup
# ──────────────────────────────────────────────────────────────
# Target: WordPress server (160.251.148.187)
# This script is run ON the production server after deploy-to-production.sh
# transfers the build artifact.
#
# Usage: sudo bash setup-production.sh [--activate]
#   Without --activate: installs everything but does NOT switch nginx
#   With    --activate: also enables the new nginx config and reloads
# ──────────────────────────────────────────────────────────────
set -euo pipefail

ACTIVATE=false
[ "${1:-}" = "--activate" ] && ACTIVATE=true

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FRONTEND_DIR="/home/kpopjournal-frontend"
BACKUP_DIR="/root/nginx-backup-$(date +%Y%m%d_%H%M%S)"
DEPLOY_ARCHIVE="${SCRIPT_DIR}/kpopjournal-frontend.tar.gz"

echo "╔══════════════════════════════════════════╗"
echo "║  kpopjournal.tokyo — production setup    ║"
echo "╚══════════════════════════════════════════╝"
echo "Server : $(hostname -I | awk '{print $1}')"
echo "Date   : $(date '+%Y-%m-%d %H:%M:%S')"
echo "Mode   : $([ "$ACTIVATE" = true ] && echo 'FULL (nginx will be switched)' || echo 'PREPARE ONLY (nginx untouched)')"
echo ""

# ═══════════════════════════════════════════════
# Step 1: Install Node.js 20 if missing
# ═══════════════════════════════════════════════
echo "[1/8] Checking Node.js..."
if command -v node >/dev/null 2>&1; then
    NODE_VER=$(node -v)
    echo "  ✓ Node.js ${NODE_VER} found"
    # Warn if not v20
    if [[ ! "$NODE_VER" =~ ^v20\. ]]; then
        echo "  ⚠ WARNING: Node.js v20 recommended (found ${NODE_VER})"
    fi
else
    echo "  Installing Node.js 20..."
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
    apt-get install -y nodejs
    echo "  ✓ Node.js $(node -v) installed"
fi

# ═══════════════════════════════════════════════
# Step 2: Install PM2 if missing
# ═══════════════════════════════════════════════
echo ""
echo "[2/8] Checking PM2..."
if command -v pm2 >/dev/null 2>&1; then
    echo "  ✓ PM2 $(pm2 -v 2>/dev/null) found"
else
    echo "  Installing PM2..."
    npm install -g pm2
    echo "  ✓ PM2 $(pm2 -v) installed"
fi

# ═══════════════════════════════════════════════
# Step 3: Detect WordPress backend port
# ═══════════════════════════════════════════════
echo ""
echo "[3/8] Detecting WordPress backend..."
WP_PORT=""

# Method 1: Check what's currently listening
for port in 80 8080 8000 8443; do
    if ss -tlnp 2>/dev/null | grep -q ":${port} " ; then
        PROC=$(ss -tlnp 2>/dev/null | grep ":${port} " | head -1)
        echo "  Port ${port}: ${PROC}"
        if echo "$PROC" | grep -qiE 'apache|httpd|php-fpm|nginx'; then
            WP_PORT=$port
        fi
    fi
done

# Method 2: Check existing nginx config for proxy_pass
if [ -z "$WP_PORT" ]; then
    for conf in /etc/nginx/sites-enabled/* /etc/nginx/conf.d/*.conf; do
        [ -f "$conf" ] || continue
        FOUND=$(grep -oP 'proxy_pass\s+http://127\.0\.0\.1:\K\d+' "$conf" 2>/dev/null | head -1)
        if [ -n "$FOUND" ]; then
            WP_PORT=$FOUND
            break
        fi
    done
fi

# Method 3: Check Apache ports.conf
if [ -z "$WP_PORT" ] && [ -f /etc/apache2/ports.conf ]; then
    WP_PORT=$(grep -oP 'Listen\s+\K\d+' /etc/apache2/ports.conf | head -1)
fi

if [ -n "$WP_PORT" ]; then
    echo "  → WordPress detected on port: ${WP_PORT}"
else
    echo "  ⚠ Could not auto-detect WordPress port."
    echo "  Defaulting to 8080. Edit nginx config if incorrect."
    WP_PORT=8080
fi

# ═══════════════════════════════════════════════
# Step 4: Backup current nginx configs
# ═══════════════════════════════════════════════
echo ""
echo "[4/8] Backing up nginx configs..."
mkdir -p "$BACKUP_DIR"
BACKED=0
for dir in /etc/nginx/sites-enabled /etc/nginx/sites-available /etc/nginx/conf.d; do
    if [ -d "$dir" ] && [ "$(ls -A "$dir" 2>/dev/null)" ]; then
        mkdir -p "$BACKUP_DIR/$(basename "$dir")"
        cp -rv "$dir"/* "$BACKUP_DIR/$(basename "$dir")/" 2>/dev/null || true
        BACKED=1
    fi
done
[ "$BACKED" -eq 0 ] && echo "  (no existing configs found)"
echo "  → Backup: $BACKUP_DIR"

# ═══════════════════════════════════════════════
# Step 5: Deploy Next.js build
# ═══════════════════════════════════════════════
echo ""
echo "[5/8] Deploying Next.js..."
mkdir -p "$FRONTEND_DIR/logs"

if [ -f "$DEPLOY_ARCHIVE" ]; then
    echo "  Extracting build archive..."
    tar -xzf "$DEPLOY_ARCHIVE" -C "$FRONTEND_DIR"
    echo "  ✓ Archive extracted to $FRONTEND_DIR"
else
    echo "  ⚠ No archive found at $DEPLOY_ARCHIVE"
    echo "    Build will need to be done locally: cd $FRONTEND_DIR && npm ci && npm run build"
fi

# Install ecosystem.config.js
cp "$SCRIPT_DIR/pm2/ecosystem.config.js" "$FRONTEND_DIR/ecosystem.config.js"
echo "  ✓ ecosystem.config.js installed"

# Install .env.local
if [ -f "$SCRIPT_DIR/env.local" ]; then
    cp "$SCRIPT_DIR/env.local" "$FRONTEND_DIR/.env.local"
    echo "  ✓ .env.local installed"
fi

# ═══════════════════════════════════════════════
# Step 6: Install nginx config (with port replacement)
# ═══════════════════════════════════════════════
echo ""
echo "[6/8] Installing nginx config (WP port=${WP_PORT})..."
mkdir -p /etc/nginx/sites-available /etc/nginx/sites-enabled

# Replace the __WP_PORT__ placeholder with the detected port
sed "s/__WP_PORT__/${WP_PORT}/g" \
    "$SCRIPT_DIR/nginx/kpopjournal-nextjs" \
    > /etc/nginx/sites-available/kpopjournal-nextjs

echo "  ✓ Installed: /etc/nginx/sites-available/kpopjournal-nextjs"
echo "  WordPress upstream: 127.0.0.1:${WP_PORT}"

# ═══════════════════════════════════════════════
# Step 7: PM2 startup + logrotate
# ═══════════════════════════════════════════════
echo ""
echo "[7/8] Configuring PM2..."

# PM2 startup
PM2_USER="${SUDO_USER:-root}"
PM2_HOME=$(eval echo "~$PM2_USER")
pm2 startup systemd -u "$PM2_USER" --hp "$PM2_HOME" 2>/dev/null || true
echo "  ✓ PM2 systemd startup: user=${PM2_USER}"

# PM2 logrotate
pm2 install pm2-logrotate 2>/dev/null || true
pm2 set pm2-logrotate:max_size   50M  2>/dev/null || true
pm2 set pm2-logrotate:retain     30   2>/dev/null || true
pm2 set pm2-logrotate:compress   true 2>/dev/null || true
pm2 set pm2-logrotate:dateFormat YYYY-MM-DD_HH-mm-ss 2>/dev/null || true
echo "  ✓ pm2-logrotate: 50MB / 30 files / compressed"

# Start or restart Next.js
echo ""
echo "  Starting Next.js via PM2..."
cd "$FRONTEND_DIR"
if pm2 describe kpopjournal >/dev/null 2>&1; then
    pm2 reload kpopjournal
    echo "  ✓ PM2: kpopjournal reloaded (zero-downtime)"
else
    pm2 start ecosystem.config.js
    echo "  ✓ PM2: kpopjournal started (2 instances)"
fi
pm2 save
echo "  ✓ PM2 state saved"

# ═══════════════════════════════════════════════
# Step 8: Activate nginx (or skip)
# ═══════════════════════════════════════════════
echo ""
echo "[8/8] nginx activation..."

# Check SSL certs
SSL_OK=false
if [ -f /etc/letsencrypt/live/kpopjournal.tokyo/fullchain.pem ]; then
    SSL_OK=true
    echo "  ✓ SSL certificate found"
    openssl x509 -in /etc/letsencrypt/live/kpopjournal.tokyo/fullchain.pem \
        -noout -enddate 2>/dev/null | sed 's/^/    /'
elif [ -f /etc/letsencrypt/live/www.kpopjournal.tokyo/fullchain.pem ]; then
    # Some setups use www subdomain as the cert name
    SSL_OK=true
    echo "  ✓ SSL certificate found (www.kpopjournal.tokyo)"
    echo "  ⚠ Update nginx config cert paths to: /etc/letsencrypt/live/www.kpopjournal.tokyo/"
fi

if [ "$ACTIVATE" = true ]; then
    if [ "$SSL_OK" = false ]; then
        echo "  ✗ Cannot activate: SSL certificates not found"
        echo "    Run: certbot certonly --webroot -w /var/www/certbot -d kpopjournal.tokyo -d www.kpopjournal.tokyo"
        echo "    Then re-run: sudo bash $0 --activate"
        exit 1
    fi

    echo "  Activating new nginx config..."
    ln -sf /etc/nginx/sites-available/kpopjournal-nextjs /etc/nginx/sites-enabled/kpopjournal-nextjs

    # Test before reload
    if nginx -t 2>&1; then
        echo "  ✓ nginx syntax OK"
        systemctl reload nginx
        echo "  ✓ nginx reloaded — site is now serving via Next.js"
    else
        echo "  ✗ nginx syntax error! Rolling back..."
        rm -f /etc/nginx/sites-enabled/kpopjournal-nextjs
        systemctl reload nginx 2>/dev/null || true
        echo "  Rolled back. Fix errors and retry."
        exit 1
    fi
else
    echo "  SKIPPED (run with --activate to switch nginx)"
    echo "  Manual activation:"
    echo "    ln -sf /etc/nginx/sites-available/kpopjournal-nextjs /etc/nginx/sites-enabled/"
    echo "    nginx -t && systemctl reload nginx"
fi

# ═══════════════════════════════════════════════
# Done
# ═══════════════════════════════════════════════
echo ""
echo "╔══════════════════════════════════════════╗"
echo "║  Setup complete!                         ║"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "Status:"
pm2 list 2>/dev/null || true
echo ""
echo "Verify:"
echo "  curl -sI http://127.0.0.1:3000/ | head -5"
echo ""
echo "Rollback:"
echo "  pm2 stop kpopjournal"
echo "  rm -f /etc/nginx/sites-enabled/kpopjournal-nextjs"
echo "  cp $BACKUP_DIR/sites-enabled/* /etc/nginx/sites-enabled/"
echo "  nginx -t && systemctl reload nginx"
