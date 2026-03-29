#!/bin/bash
# ══════════════════════════════════════════════════════════
#  Ensemble Chaos Controls
#  Toggle failure scenarios via Helm upgrade (no redeploy)
# ══════════════════════════════════════════════════════════

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

case "${1:-help}" in

  normal)
    echo "Setting NORMAL mode — all chaos disabled"
    helm upgrade ensemble-storefront "$SCRIPT_DIR/helm/storefront" \
      --set chaos.checkoutDelay=0 \
      --set chaos.errorRate=0 \
      --set chaos.userMultiplier=1 \
      --set chaos.logicAppErrorRate=0 \
      --set chaos.logicAppSlowRate=0
    helm upgrade ensemble-inventory "$SCRIPT_DIR/helm/inventory-service" \
      --set chaos.dbSaturation=0 \
      --set chaos.slowQueries=0 \
      --set chaos.errorRate=0
    echo "Normal mode active ✓"
    ;;

  slowdown)
    echo "Setting SLOWDOWN — latency increasing, pre-outage signal"
    helm upgrade ensemble-storefront "$SCRIPT_DIR/helm/storefront" \
      --set chaos.checkoutDelay=1.5 \
      --set chaos.userMultiplier=3 \
      --set chaos.logicAppSlowRate=0.5
    helm upgrade ensemble-inventory "$SCRIPT_DIR/helm/inventory-service" \
      --set chaos.slowQueries=0.8
    echo "Slowdown active — watch p95 latency climb in Grafana ✓"
    ;;

  blackfriday)
    echo "Setting BLACK FRIDAY — full chaos, database saturation"
    helm upgrade ensemble-storefront "$SCRIPT_DIR/helm/storefront" \
      --set chaos.checkoutDelay=4.0 \
      --set chaos.errorRate=0.25 \
      --set chaos.userMultiplier=8 \
      --set chaos.logicAppErrorRate=0.3 \
      --set chaos.logicAppSlowRate=2.0
    helm upgrade ensemble-inventory "$SCRIPT_DIR/helm/inventory-service" \
      --set chaos.dbSaturation=0.9 \
      --set chaos.slowQueries=2.0 \
      --set chaos.errorRate=0.3
    echo "BLACK FRIDAY MODE ACTIVE 🚨"
    echo "Watch Grafana: error rate, checkout latency, DB pool, Logic App failures"
    ;;

  recover)
    echo "Setting RECOVERY — gradually restoring normal operations"
    helm upgrade ensemble-storefront "$SCRIPT_DIR/helm/storefront" \
      --set chaos.checkoutDelay=0.5 \
      --set chaos.errorRate=0.05 \
      --set chaos.userMultiplier=2 \
      --set chaos.logicAppErrorRate=0.05 \
      --set chaos.logicAppSlowRate=0.2
    helm upgrade ensemble-inventory "$SCRIPT_DIR/helm/inventory-service" \
      --set chaos.dbSaturation=0.2 \
      --set chaos.slowQueries=0.2 \
      --set chaos.errorRate=0.05
    echo "Recovery mode — errors should be clearing in Grafana ✓"
    ;;

  logicapps-chaos)
    echo "Setting LOGIC APPS CHAOS — serverless layer failing"
    helm upgrade ensemble-storefront "$SCRIPT_DIR/helm/storefront" \
      --set chaos.logicAppErrorRate=0.4 \
      --set chaos.logicAppSlowRate=2.0 \
      --set chaos.userMultiplier=5
    echo "Logic Apps chaos active — watch ensemble_logic_app_failures_total in Grafana ✓"
    ;;

  wire-azure)
    if [ -z "$FRAUD_URL" ] || [ -z "$LOYALTY_URL" ] || [ -z "$NOTIFY_URL" ]; then
      echo "Usage: FRAUD_URL=<url> LOYALTY_URL=<url> NOTIFY_URL=<url> ./chaos-control.sh wire-azure"
      exit 1
    fi
    echo "Wiring real Azure Logic Apps..."
    helm upgrade ensemble-storefront "$SCRIPT_DIR/helm/storefront" \
      --set azure.fraudCheckUrl="$FRAUD_URL" \
      --set azure.loyaltyPointsUrl="$LOYALTY_URL" \
      --set azure.orderNotifyUrl="$NOTIFY_URL"
    echo "Azure Logic Apps wired ✓"
    echo "Verify: curl http://192.168.58.2:30100/api/logic-apps/status"
    ;;

  *)
    echo "Usage: ./chaos-control.sh [normal|slowdown|blackfriday|recover|logicapps-chaos|wire-azure]"
    echo ""
    echo "  normal          — All chaos disabled, clean baseline"
    echo "  slowdown        — Latency rising, Logic Apps slowing (pre-outage)"
    echo "  blackfriday     — Full failure: DB saturation, high errors, Logic App failures"
    echo "  recover         — Gradual recovery after incident"
    echo "  logicapps-chaos — Serverless layer failing independently"
    echo "  wire-azure      — Connect real Azure Logic Apps (requires FRAUD_URL, LOYALTY_URL, NOTIFY_URL)"
    echo ""
    echo "Demo sequence:"
    echo "  1. ./chaos-control.sh normal"
    echo "  2. python3 chaos/chaos.py --mode ramp"
    echo "  3. ./chaos-control.sh slowdown"
    echo "  4. ./chaos-control.sh blackfriday"
    echo "  5. ./chaos-control.sh normal"
    ;;
esac