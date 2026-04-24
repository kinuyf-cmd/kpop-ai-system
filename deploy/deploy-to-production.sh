#!/bin/bash
# ──────────────────────────────────────────────────────────────
# kpopjournal.tokyo — Deploy from AI server to production
# ──────────────────────────────────────────────────────────────
# Run on: AI server (163.44.96.56)
# Target: Production/WordPress server (160.251.148.187)
#
# This script:
#   1. Builds Next.js on the AI server
#   2. Packages as tar.gz
#   3. Transfers to production server via scp
#   4. Runs setup-production.sh on remote
#
# Usage:
#   bash deploy-to-production.sh              # deploy only (nginx untouched)
#   bash deploy-to-production.sh --activate   # deploy + switch nginx
#   bash deploy-to-production.sh --dry-run    # show what would happen
# ──────────────────────────────────────────────────────────────
set -euo pipefail

# ── Configuration ────────────────────────────
PROD_HOST="160.251.148.187"
PROD_USER="root"                     # change if using a non-root deploy user
PROD_SSH="${PROD_USER}@${PROD_HOST}"
SSH_KEY="${HOME}/.ssh/id_ed25519"     # adjust if using different key
SSH_OPTS="-o StrictHostKeyChecking=accept-new -o ConnectTimeout=10"

LOCAL_PROJECT_DIR="/home/aiuser/kpopjournal-frontend"
LOCAL_DEPLOY_DIR="/home/aiuser/kpop-ai-system/deploy"
REMOTE_DEPLOY_DIR="/tmp/kpopjournal-deploy"
REMOTE_FRONTEND_DIR="/home/kpopjournal-frontend"

ARCHIVE_NAME="kpopjournal-frontend.tar.gz"

# ── Parse flags ──────────────────────────────
ACTIVATE=""
DRY_RUN=false
for arg in "$@"; do
    case "$arg" in
        --activate) ACTIVATE="--activate" ;;
        --dry-run)  DRY_RUN=true ;;
    esac
done

# ── Helpers ──────────────────────────────────
info()  { echo "[$(date '+%H:%M:%S')] $*"; }
error() { echo "[$(date '+%H:%M:%S')] ERROR: $*" >&2; exit 1; }

ssh_cmd() {
    if [ -f "$SSH_KEY" ]; then
        ssh $SSH_OPTS -i "$SSH_KEY" "$PROD_SSH" "$@"
    else
        ssh $SSH_OPTS "$PROD_SSH" "$@"
    fi
}

scp_cmd() {
    if [ -f "$SSH_KEY" ]; then
        scp $SSH_OPTS -i "$SSH_KEY" "$@"
    else
        scp $SSH_OPTS "$@"
    fi
}

echo "╔══════════════════════════════════════════╗"
echo "║  Deploy to production                    ║"
echo "╚══════════════════════════════════════════╝"
echo "Source : ${LOCAL_PROJECT_DIR}"
echo "Target : ${PROD_SSH}:${REMOTE_FRONTEND_DIR}"
echo "Mode   : $([ -n "$ACTIVATE" ] && echo 'ACTIVATE nginx' || echo 'Deploy only')"
echo ""

# ═══════════════════════════════════════════════
# Step 1: Pre-flight checks
# ═══════════════════════════════════════════════
info "[1/6] Pre-flight checks..."

[ -d "$LOCAL_PROJECT_DIR" ] || error "Project directory not found: $LOCAL_PROJECT_DIR"
[ -f "$LOCAL_PROJECT_DIR/package.json" ] || error "No package.json in $LOCAL_PROJECT_DIR"

if [ ! -f "$SSH_KEY" ] && [ ! -f "${HOME}/.ssh/id_rsa" ]; then
    echo "  ⚠ No SSH key found at $SSH_KEY"
    echo "  Generate one:"
    echo "    ssh-keygen -t ed25519 -C 'kpop-ai-deploy'"
    echo "    ssh-copy-id ${PROD_SSH}"
    echo ""
    echo "  Or copy existing key. Then retry."
    if [ "$DRY_RUN" = false ]; then
        error "SSH key required for deployment"
    fi
fi

# Test SSH connectivity
if [ "$DRY_RUN" = false ]; then
    info "  Testing SSH to ${PROD_HOST}..."
    ssh_cmd "echo 'SSH OK: \$(hostname) \$(hostname -I | awk \"{print \\\$1}\")'" \
        || error "Cannot SSH to ${PROD_SSH}. Check key/connectivity."
    info "  ✓ SSH connection OK"
fi

# ═══════════════════════════════════════════════
# Step 2: Build Next.js
# ═══════════════════════════════════════════════
info ""
info "[2/6] Building Next.js..."

cd "$LOCAL_PROJECT_DIR"

if [ "$DRY_RUN" = true ]; then
    info "  [dry-run] Would run: npm ci && npm run build"
else
    info "  npm ci..."
    npm ci --production=false 2>&1 | tail -3

    info "  npm run build..."
    npm run build 2>&1 | tail -10

    [ -d ".next" ] || error "Build failed: .next directory not found"
    info "  ✓ Build complete"
fi

# ═══════════════════════════════════════════════
# Step 3: Package build artifact
# ═══════════════════════════════════════════════
info ""
info "[3/6] Packaging..."

ARCHIVE_PATH="${LOCAL_DEPLOY_DIR}/${ARCHIVE_NAME}"

if [ "$DRY_RUN" = true ]; then
    info "  [dry-run] Would create: $ARCHIVE_PATH"
else
    # Include only what's needed for production
    tar -czf "$ARCHIVE_PATH" \
        --exclude='node_modules' \
        --exclude='.git' \
        --exclude='.next/cache' \
        -C "$LOCAL_PROJECT_DIR" \
        .next \
        public \
        package.json \
        package-lock.json \
        next.config.js \
        next.config.mjs \
        2>/dev/null || \
    tar -czf "$ARCHIVE_PATH" \
        --exclude='node_modules' \
        --exclude='.git' \
        --exclude='.next/cache' \
        -C "$LOCAL_PROJECT_DIR" \
        .next \
        public \
        package.json \
        package-lock.json

    ARCHIVE_SIZE=$(du -h "$ARCHIVE_PATH" | cut -f1)
    info "  ✓ Archive: $ARCHIVE_PATH ($ARCHIVE_SIZE)"
fi

# ═══════════════════════════════════════════════
# Step 4: Transfer to production
# ═══════════════════════════════════════════════
info ""
info "[4/6] Transferring to ${PROD_HOST}..."

if [ "$DRY_RUN" = true ]; then
    info "  [dry-run] Would scp archive + deploy scripts"
else
    # Create remote deploy directory
    ssh_cmd "mkdir -p ${REMOTE_DEPLOY_DIR}/nginx ${REMOTE_DEPLOY_DIR}/pm2"

    # Transfer archive
    info "  Uploading build archive..."
    scp_cmd "$ARCHIVE_PATH" "${PROD_SSH}:${REMOTE_DEPLOY_DIR}/${ARCHIVE_NAME}"

    # Transfer deploy configs
    info "  Uploading config files..."
    scp_cmd "${LOCAL_DEPLOY_DIR}/nginx/kpopjournal-nextjs" "${PROD_SSH}:${REMOTE_DEPLOY_DIR}/nginx/"
    scp_cmd "${LOCAL_DEPLOY_DIR}/pm2/ecosystem.config.js"  "${PROD_SSH}:${REMOTE_DEPLOY_DIR}/pm2/"
    scp_cmd "${LOCAL_DEPLOY_DIR}/setup-production.sh"       "${PROD_SSH}:${REMOTE_DEPLOY_DIR}/"
    scp_cmd "${LOCAL_DEPLOY_DIR}/env.local"                 "${PROD_SSH}:${REMOTE_DEPLOY_DIR}/"

    info "  ✓ Transfer complete"
fi

# ═══════════════════════════════════════════════
# Step 5: Install dependencies on remote
# ═══════════════════════════════════════════════
info ""
info "[5/6] Installing production dependencies on remote..."

if [ "$DRY_RUN" = true ]; then
    info "  [dry-run] Would run npm ci --production on remote"
else
    ssh_cmd "
        mkdir -p ${REMOTE_FRONTEND_DIR} &&
        tar -xzf ${REMOTE_DEPLOY_DIR}/${ARCHIVE_NAME} -C ${REMOTE_FRONTEND_DIR} &&
        cd ${REMOTE_FRONTEND_DIR} &&
        npm ci --production 2>&1 | tail -5
    "
    info "  ✓ Dependencies installed"
fi

# ═══════════════════════════════════════════════
# Step 6: Run setup script on remote
# ═══════════════════════════════════════════════
info ""
info "[6/6] Running setup on remote..."

if [ "$DRY_RUN" = true ]; then
    info "  [dry-run] Would run: bash setup-production.sh $ACTIVATE"
else
    ssh_cmd "bash ${REMOTE_DEPLOY_DIR}/setup-production.sh ${ACTIVATE}"
fi

# ═══════════════════════════════════════════════
# Done
# ═══════════════════════════════════════════════
echo ""
echo "╔══════════════════════════════════════════╗"
echo "║  Deployment complete!                    ║"
echo "╚══════════════════════════════════════════╝"
echo ""
if [ -n "$ACTIVATE" ]; then
    echo "Site should now be live at: https://www.kpopjournal.tokyo"
    echo "Verify: curl -sI https://www.kpopjournal.tokyo | head -5"
else
    echo "Build deployed. To activate nginx:"
    echo "  ssh ${PROD_SSH} 'bash ${REMOTE_DEPLOY_DIR}/setup-production.sh --activate'"
    echo ""
    echo "Or re-run this script with --activate:"
    echo "  bash $0 --activate"
fi
echo ""
echo "Quick checks:"
echo "  ssh ${PROD_SSH} 'pm2 list'"
echo "  ssh ${PROD_SSH} 'curl -sI http://127.0.0.1:3000/ | head -5'"
