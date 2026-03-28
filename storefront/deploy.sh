#!/bin/bash
# ══════════════════════════════════════════════════════════
#  Ensemble Store — Full Deploy Script
#  Builds both services and deploys them to minikube
# ══════════════════════════════════════════════════════════
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log() { echo -e "${GREEN}[deploy]${NC} $1"; }
warn() { echo -e "${YELLOW}[warn]${NC} $1"; }
err() { echo -e "${RED}[error]${NC} $1"; exit 1; }

# ── Preflight ─────────────────────────────────────────────
log "Checking prerequisites..."
command -v minikube &>/dev/null || err "minikube not found"
command -v kubectl &>/dev/null  || err "kubectl not found"
command -v helm &>/dev/null     || err "helm not found"
command -v podman &>/dev/null || command -v docker &>/dev/null || err "podman or docker not found"

# Detect container runtime
if command -v podman &>/dev/null; then
    RUNTIME="podman"
else
    RUNTIME="docker"
fi
log "Using container runtime: $RUNTIME"

# ── Check minikube ────────────────────────────────────────
if ! minikube status | grep -q "Running"; then
    warn "minikube not running, starting..."
    minikube start
fi

log "minikube is running ✓"

# ── Build images ──────────────────────────────────────────
log "Building ensemble-storefront image..."
cd "$SCRIPT_DIR/storefront"
$RUNTIME build -t localhost/ensemble-storefront:latest .
log "ensemble-storefront built ✓"

log "Building ensemble-inventory image..."
cd "$SCRIPT_DIR/inventory-service"
$RUNTIME build -t localhost/ensemble-inventory:latest .
log "ensemble-inventory built ✓"

# ── Load into minikube ────────────────────────────────────
log "Loading images into minikube..."

if [ "$RUNTIME" = "podman" ]; then
    $RUNTIME save localhost/ensemble-storefront:latest -o /tmp/ensemble-storefront.tar
    $RUNTIME save localhost/ensemble-inventory:latest  -o /tmp/ensemble-inventory.tar
    minikube image load /tmp/ensemble-storefront.tar
    minikube image load /tmp/ensemble-inventory.tar
    rm -f /tmp/ensemble-storefront.tar /tmp/ensemble-inventory.tar
else
    minikube image load localhost/ensemble-storefront:latest
    minikube image load localhost/ensemble-inventory:latest
fi

log "Images loaded into minikube ✓"

# ── Deploy with Helm ──────────────────────────────────────
cd "$SCRIPT_DIR"

log "Deploying ensemble-inventory..."
if helm status ensemble-inventory &>/dev/null 2>&1; then
    helm upgrade ensemble-inventory ./helm/inventory-service
    log "ensemble-inventory upgraded ✓"
else
    helm install ensemble-inventory ./helm/inventory-service
    log "ensemble-inventory installed ✓"
fi

log "Deploying ensemble-storefront..."
if helm status ensemble-storefront &>/dev/null 2>&1; then
    helm upgrade ensemble-storefront ./helm/storefront
    log "ensemble-storefront upgraded ✓"
else
    helm install ensemble-storefront ./helm/storefront
    log "ensemble-storefront installed ✓"
fi

# ── Wait for pods ─────────────────────────────────────────
log "Waiting for pods to be ready..."
kubectl rollout status deployment/ensemble-inventory --timeout=90s
kubectl rollout status deployment/ensemble-storefront --timeout=90s

# ── Done ──────────────────────────────────────────────────
MINIKUBE_IP=$(minikube ip)
echo ""
echo -e "${GREEN}══════════════════════════════════════════${NC}"
echo -e "${GREEN}  Ensemble Store deployed successfully!${NC}"
echo -e "${GREEN}══════════════════════════════════════════${NC}"
echo ""
echo "  Storefront:  http://$MINIKUBE_IP:30100"
echo "  Metrics:     http://$MINIKUBE_IP:30100/metrics"
echo ""
echo "  Or use port-forward:"
echo "  kubectl port-forward svc/ensemble-storefront 5000:5000"
echo ""
echo "  Run chaos:"
echo "  python3 chaos/chaos.py --mode normal"
echo "  python3 chaos/chaos.py --mode ramp"
echo "  python3 chaos/chaos.py --mode blackfriday"
echo ""
