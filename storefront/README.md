# Ensemble Store — Grafana Observability Demo

A two-service e-commerce application simulating a mid-range clothing retailer.
Built specifically to demonstrate the Grafana LGTM stack for the Grafana Labs
Observability Architect interview practical.

## Architecture

```
Browser → ensemble-storefront (Flask, port 5000)
                ↓
         ensemble-inventory (Flask, port 5001)
                ↓
         (simulated DB with configurable pool)
```

Both services expose `/metrics` endpoints scraped by Grafana Alloy
and shipped to Grafana Cloud (Mimir + Loki).

## Quick Start

```bash
# Deploy everything to minikube
chmod +x deploy.sh chaos-control.sh
./deploy.sh

# Access the storefront
kubectl port-forward svc/ensemble-storefront 5000:5000
# Open http://localhost:5000

# Generate traffic
pip install requests
python3 chaos/chaos.py --mode normal
```

## Demo Sequence

### 1. Healthy baseline
```bash
./chaos-control.sh normal
python3 chaos/chaos.py --mode normal
```
Show: clean Grafana dashboards, all green, sub-100ms checkout latency.

### 2. Traffic ramp (pre-Black Friday)
```bash
python3 chaos/chaos.py --mode ramp
```
Show: request rate climbing, still healthy, SLO budget intact.

### 3. Latency degradation begins
```bash
./chaos-control.sh slowdown
```
Show: p95 checkout latency crossing threshold, alert fires, Grafana
      alert notification delivered. "This is what Ensemble didn't have."

### 4. Full Black Friday outage
```bash
./chaos-control.sh blackfriday
python3 chaos/chaos.py --mode blackfriday
```
Show: error rate spike, DB pool exhaustion metric hitting 100%,
      checkout failures, log correlation showing inventory errors,
      SLO error budget burning rapidly.

### 5. Investigation workflow
In Grafana Cloud Explore:
- Metrics: `ensemble_checkout_errors_total` rate spike
- Logs: `{app="ensemble-storefront"} |= "error"` — see the checkout failures
- Logs: `{app="ensemble-inventory"} |= "pool"` — see DB exhaustion messages
- Correlate: click from metric spike → log lines → (if tracing enabled) trace

### 6. Recovery
```bash
./chaos-control.sh recover
./chaos-control.sh normal
```
Show: error rate dropping, latency normalizing, SLO burn rate recovering.

## Key Metrics (for Grafana dashboards)

| Metric | Description | Demo use |
|--------|-------------|----------|
| `ensemble_http_requests_total` | Requests by endpoint/status | Traffic volume |
| `ensemble_checkout_duration_seconds` | Checkout latency histogram | p95 SLO target |
| `ensemble_checkout_errors_total` | Checkout failures by reason | Error rate alert |
| `ensemble_active_users` | Simulated concurrent users | Load indicator |
| `ensemble_inventory_call_duration_seconds` | Downstream call latency | Root cause |
| `ensemble_inventory_call_errors_total` | Inventory service errors | Cascade failure |
| `inventory_db_pool_available` | DB connections available | Pool saturation |
| `inventory_requests_total` | Inventory service traffic | Service health |

## Suggested PromQL Queries

```promql
# Checkout error rate (the alert that would have saved Ensemble)
rate(ensemble_checkout_errors_total[5m])

# p95 checkout latency (SLO signal)
histogram_quantile(0.95, rate(ensemble_checkout_duration_seconds_bucket[5m]))

# DB pool saturation (root cause)
1 - (inventory_db_pool_available / 10)

# Request success rate
rate(ensemble_http_requests_total{status_code="200"}[5m])
/ rate(ensemble_http_requests_total[5m])

# Inventory call latency p99
histogram_quantile(0.99, rate(ensemble_inventory_call_duration_seconds_bucket[5m]))
```

## Chaos Control Reference

Chaos is controlled via Helm values — no redeployment needed.

| Mode | Checkout delay | Error rate | DB saturation |
|------|---------------|------------|---------------|
| normal | 0s | 0% | 0% |
| slowdown | 1.5s | 0% | 80% queries slow |
| blackfriday | 4s | 25% | 90% pool used |
| recover | 0.5s | 5% | 20% pool used |

## File Structure

```
ensemble-store/
├── deploy.sh              # One-command deploy to minikube
├── chaos-control.sh       # Toggle chaos modes via Helm
├── storefront/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── src/
│       ├── api/app.py     # Flask app with full Prometheus instrumentation
│       └── web/index.html # Full storefront UI
├── inventory-service/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── src/app.py         # Inventory service with DB pool simulation
├── helm/
│   ├── storefront/        # Helm chart for storefront
│   └── inventory-service/ # Helm chart for inventory
└── chaos/
    └── chaos.py           # Traffic generator with 4 modes
```
