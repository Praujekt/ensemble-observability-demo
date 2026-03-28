#!/bin/bash
# ══════════════════════════════════════════════════════════
#  Ensemble Chaos Controls
#  Trigger failure scenarios via Helm upgrade (no redeploy)
#  These update env vars in running pods instantly
# ══════════════════════════════════════════════════════════

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

case "${1:-help}" in

  normal)
    echo "Setting NORMAL mode — all chaos disabled"
    helm upgrade ensemble-storefront "$SCRIPT_DIR/helm/storefront" \
      --set chaos.checkoutDelay=0 \
      --set chaos.errorRate=0 \
      --set chaos.userMultiplier=1
    helm upgrade ensemble-inventory "$SCRIPT_DIR/helm/inventory-service" \
      --set chaos.dbSaturation=0 \
      --set chaos.slowQueries=0 \
      --set chaos.errorRate=0
    echo "Normal mode active ✓"
    ;;

  slowdown)
    echo "Setting SLOWDOWN — checkout latency increasing (pre-outage signal)"
    helm upgrade ensemble-storefront "$SCRIPT_DIR/helm/storefront" \
      --set chaos.checkoutDelay=1.5 \
      --set chaos.userMultiplier=3
    helm upgrade ensemble-inventory "$SCRIPT_DIR/helm/inventory-service" \
      --set chaos.slowQueries=0.8
    echo "Slowdown active — watch p95 latency climb in Grafana ✓"
    ;;

  blackfriday)
    echo "Setting BLACK FRIDAY — full chaos, database saturation"
    helm upgrade ensemble-storefront "$SCRIPT_DIR/helm/storefront" \
      --set chaos.checkoutDelay=4.0 \
      --set chaos.errorRate=0.25 \
      --set chaos.userMultiplier=8
    helm upgrade ensemble-inventory "$SCRIPT_DIR/helm/inventory-service" \
      --set chaos.dbSaturation=0.9 \
      --set chaos.slowQueries=2.0 \
      --set chaos.errorRate=0.3
    echo "BLACK FRIDAY MODE ACTIVE 🚨"
    echo "Watch Grafana: error rate, checkout latency, DB pool exhaustion"
    ;;

  recover)
    echo "Setting RECOVERY — gradually restoring normal operations"
    helm upgrade ensemble-storefront "$SCRIPT_DIR/helm/storefront" \
      --set chaos.checkoutDelay=0.5 \
      --set chaos.errorRate=0.05 \
      --set chaos.userMultiplier=2
    helm upgrade ensemble-inventory "$SCRIPT_DIR/helm/inventory-service" \
      --set chaos.dbSaturation=0.2 \
      --set chaos.slowQueries=0.2 \
      --set chaos.errorRate=0.05
    echo "Recovery mode — errors should be clearing in Grafana ✓"
    ;;

  *)
    echo "Usage: ./chaos-control.sh [normal|slowdown|blackfriday|recover]"
    echo ""
    echo "  normal      — All chaos disabled, clean baseline"
    echo "  slowdown    — Checkout slowing down, latency rising (pre-outage)"
    echo "  blackfriday — Full failure: DB saturation, high errors, slow checkout"
    echo "  recover     — Gradual recovery after incident"
    echo ""
    echo "Demo sequence for presentation:"
    echo "  1. ./chaos-control.sh normal      (show healthy baseline)"
    echo "  2. python3 chaos/chaos.py --mode ramp   (traffic building)"
    echo "  3. ./chaos-control.sh slowdown    (latency starting to climb)"
    echo "  4. ./chaos-control.sh blackfriday (full outage scenario)"
    echo "  5. ./chaos-control.sh normal      (show recovery)"
    ;;
esac
