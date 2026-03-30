# Zachsemble — Ensemble Store Observability Demo

A two-service e-commerce application simulating a clothing retailer's Black Friday outage
and full incident investigation workflow. Built to demonstrate the complete Grafana LGTM+
stack: metrics, logs, traces, and Azure Monitor — all wired together with real correlation.

**Tagline:** *Our Aesthetics Are Metrics*

---

## What This Demonstrates

The demo tells a real story: Ensemble's Black Friday site goes down. The root cause is
inventory database connection pool exhaustion cascading into checkout failures. The demo
walks through detection (alerts firing), investigation (metrics → logs → traces), and
recovery — using the same tools and workflows you'd use in production.

The full observability picture:

- **Metrics** — Prometheus via Grafana Alloy → Grafana Cloud Mimir
- **Logs** — Structured JSON from both services → Promtail DaemonSet → Grafana Cloud Loki
- **Traces** — OpenTelemetry instrumentation → OTLP → Grafana Cloud Tempo
- **Azure** — Three Logic Apps (fraud check, loyalty points, order notification) with real Azure Monitor data in Grafana Cloud via the Azure Monitor datasource

Logs carry `traceID` and `spanID` fields that link directly to Tempo spans. Every checkout
request produces a full trace waterfall showing time spent in each Logic App.

---

## Architecture

```
Browser
  └── ensemble-storefront  (Flask, port 5000, NodePort 30100, 2 replicas)
            ├── /api/products  → ensemble-inventory (Flask, port 5001, ClusterIP, 2 replicas)
            ├── /api/checkout  → ensemble-inventory (per-SKU lookup)
            │                  → Azure Logic App: fraud-check
            │                  → Azure Logic App: loyalty-points
            │                  → Azure Logic App: order-notification
            └── /metrics       → Grafana Alloy → Grafana Cloud

ensemble-inventory
  ├── /inventory/<sku>    — per-SKU lookup with DB pool simulation
  ├── /inventory/bulk     — full catalog fetch
  └── /metrics            → Grafana Alloy → Grafana Cloud

Promtail DaemonSet        → pod logs → Grafana Cloud Loki
OTel OTLP exporter        → traces   → Grafana Cloud Tempo
Azure Monitor datasource  → Logic App execution data in Grafana Cloud
```

Chaos is entirely env-var driven via Helm values — no image rebuilds required to switch modes.

---

## Prerequisites

- minikube (podman driver)
- kubectl, helm
- podman
- Python 3 + `requests` (`pip install requests`)
- Grafana Cloud stack with Alloy running as a systemd service
- `grafana-credentials` Kubernetes secret (see Setup)
- `promtail-secret` Kubernetes secret (see Setup)

---

## Setup

**1. Create the Kubernetes secrets**

```bash
# Grafana Cloud credentials — used by the storefront for OTLP trace export
kubectl create secret generic grafana-credentials \
  --from-literal=api-key=<YOUR_OTLP_TOKEN>

# Promtail credentials — used for log shipping to Loki
kubectl create secret generic promtail-secret \
  --from-literal=api-key=<YOUR_LOKI_TOKEN>
```

The OTLP token must be scoped for trace writes. Generate it from your Grafana Cloud stack
page under **OpenTelemetry → Configure**. The instance ID used for Basic auth is `1574720`.

**2. (Optional) Wire real Azure Logic Apps**

Copy `azure-values.yaml.example` to `azure-values.yaml` and fill in your Logic App URLs.
If this file is absent, all three Logic Apps run in simulated mode — realistic metrics are
still generated, real Azure Monitor data is not.

**3. Deploy**

```bash
chmod +x deploy.sh chaos-control.sh
./deploy.sh
```

The deploy script builds both images, loads them into minikube, runs helm install/upgrade
for both services, applies Azure values if present, and waits for pods to be ready.

**4. Apply the Promtail DaemonSet**

```bash
kubectl apply -f k8s-promtail.yaml
```

**5. Verify**

```bash
curl http://192.168.58.2:30100/health
curl http://192.168.58.2:30100/metrics
curl http://192.168.58.2:30100/api/logic-apps/status
```

---

## Running the Demo

### Full sequence

```bash
# Terminal 1 — set baseline chaos mode
./chaos-control.sh normal

# Terminal 2 — start traffic generator
python3 chaos/chaos.py --mode normal --url http://192.168.58.2:30100
```

Then progress through the outage scenario:

```bash
# Pre-outage signal — latency rising, Logic Apps slowing
./chaos-control.sh slowdown

# Full Black Friday failure
./chaos-control.sh blackfriday
python3 chaos/chaos.py --mode blackfriday --url http://192.168.58.2:30100

# Recovery
./chaos-control.sh recover
./chaos-control.sh normal
```

### Traffic generator modes

| Mode | Concurrent users | Checkout rate | Description |
|------|-----------------|---------------|-------------|
| `normal` | 15 | 15% | Steady background traffic |
| `ramp` | 10 → 80 over 3 min | 20% | Pre-Black Friday surge |
| `blackfriday` | 150+ | 35% | Peak load, high think speed |
| `recovery` | 20 | 10% | Post-incident tapering |

```bash
python3 chaos/chaos.py --mode <mode> --url http://192.168.58.2:30100
python3 chaos/chaos.py --mode blackfriday --duration 300  # run for 5 minutes then stop
```

### Chaos control modes

Chaos is applied via `helm upgrade` — no pod restarts required.

| Mode | Checkout delay | Error rate | DB pool used | Logic App errors |
|------|---------------|------------|--------------|-----------------|
| `normal` | 0s | 0% | 0% | 0% |
| `slowdown` | 1.5s | 0% | — | 50% slow |
| `blackfriday` | 4s | 25% | 90% | 30% fail |
| `recover` | 0.5s | 5% | 20% | 5% fail |
| `logicapps-chaos` | — | — | — | 40% fail |

```bash
./chaos-control.sh [normal|slowdown|blackfriday|recover|logicapps-chaos]
```

---

## Investigation Workflow

This is the core of the demo. Starting from an alert firing:

**1. Alert fires** — Checkout p95 latency or error rate threshold breached in Grafana

**2. Metrics** — Identify the pattern

```promql
# p95 checkout latency
histogram_quantile(0.95, rate(ensemble_checkout_duration_seconds_bucket[5m]))

# Error rate
sum(rate(ensemble_checkout_errors_total[5m]))
/ sum(rate(ensemble_http_requests_total{endpoint="/api/checkout"}[5m]))

# Root cause — DB pool saturation
1 - (inventory_db_pool_available / 10)

# Logic App failure breakdown
sum(rate(ensemble_logic_app_failures_total[5m])) by (logic_app)
```

**3. Logs** — Drill into what's failing

```logql
# Checkout errors with context
{app="ensemble-storefront"} | json | level="ERROR"

# Slow requests only
{app="ensemble-storefront"} | json | duration_ms > 1000

# Inventory pool exhaustion messages
{app="ensemble-inventory"} | json | level="ERROR"

# Logic App failures by service
{app="ensemble-storefront"} | json | logic_app != ""
```

**4. Traces** — Find the specific request

In Grafana Explore → Tempo:
```
{resource.service.name="ensemble-storefront"}
```

Click any trace to see the full waterfall: storefront root span → inventory lookup span →
each Logic App span with its own duration. The `order_id` attribute links the trace back
to the log lines.

**5. Logs ↔ Traces correlation**

Every log line from a traced request carries `traceID` and `spanID`. From Loki, clicking
the traceID opens the corresponding Tempo trace directly. From Tempo, the Loki data link
opens the log lines for that request.

---

## Metrics Reference

### Storefront

| Metric | Labels | Description |
|--------|--------|-------------|
| `ensemble_http_requests_total` | `endpoint`, `method`, `status_code` | All HTTP requests |
| `ensemble_http_request_duration_seconds` | `endpoint` | Request latency histogram |
| `ensemble_checkout_duration_seconds` | — | Checkout end-to-end latency |
| `ensemble_checkout_errors_total` | `reason` | Checkout failures by reason |
| `ensemble_checkouts_total` | — | Successful checkout count |
| `ensemble_active_users` | — | Simulated concurrent users |
| `ensemble_cart_items` | — | Items per checkout histogram |
| `ensemble_revenue_total_cents` | — | Total revenue counter |
| `ensemble_inventory_call_duration_seconds` | `endpoint` | Downstream call latency |
| `ensemble_inventory_call_errors_total` | `status_code` | Downstream call failures |
| `ensemble_logic_app_calls_total` | `logic_app`, `status` | Logic App call outcomes |
| `ensemble_logic_app_duration_seconds` | `logic_app` | Logic App latency histogram |
| `ensemble_logic_app_failures_total` | `logic_app`, `error_type` | Logic App failures |
| `ensemble_serverless_throttles_total` | `service` | Throttled Logic App calls |

### Inventory Service

| Metric | Labels | Description |
|--------|--------|-------------|
| `inventory_requests_total` | `endpoint`, `status` | All inventory requests |
| `inventory_request_duration_seconds` | `endpoint` | Request latency histogram |
| `inventory_db_pool_available` | — | Available DB connections (root cause metric) |
| `inventory_db_pool_total` | — | Total pool size (always 10) |
| `inventory_lookup_failures_total` | — | Failed inventory lookups |

---

## Alerts

Five rules deployed via Terraform in the **Ensemble SLOs** folder (all Provisioned):

| Alert | Condition | Severity | For |
|-------|-----------|----------|-----|
| Checkout p95 Latency Breach | p95 > 2.5s | critical | 2m |
| Checkout High Error Rate | error rate > 5% | critical | 2m |
| Logic Apps High Failure Rate | failures > 0.1/s | warning | 1m |
| Inventory DB Pool Saturation | pool used > 80% | critical | 1m |
| Black Friday Load Surge | active users > 500 | warning | 3m |

Deploy or update alerts:

```bash
cd terraform/grafana
terraform init
terraform apply \
  -var="grafana_url=https://praujekt.grafana.net" \
  -var="grafana_api_key=<YOUR_KEY>"
```

---

## Azure Infrastructure

Three Logic Apps in `ensemble-demo-rg` (East US) — deployed via Terraform:

- **ensemble-fraud-check** — HTTP trigger, called at checkout start, blocking
- **ensemble-loyalty-points** — HTTP trigger, called post-purchase, non-blocking
- **ensemble-order-notification** — HTTP trigger, called post-purchase, non-blocking

All three have diagnostic settings shipping `WorkflowRuntime` logs and metrics to Log
Analytics, surfaced in Grafana Cloud via the `azure-monitor-ensemble-demo` datasource.

The `grafana-cloud-reader` service principal has Monitoring Reader + Reader roles at
subscription scope. Terraform state is local in `terraform/azure/`.

```bash
cd terraform/azure
terraform init
terraform apply
```

Wire the Logic App URLs after apply:

```bash
FRAUD_URL=<url> LOYALTY_URL=<url> NOTIFY_URL=<url> ./chaos-control.sh wire-azure
```

---

## File Structure

```
ensemble-observability-demo/
├── deploy.sh                        # Full build + deploy to minikube
├── chaos-control.sh                 # Toggle chaos modes via Helm (no rebuild)
├── k8s-promtail.yaml                # Promtail DaemonSet for pod log collection
├── storefront/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── src/
│       ├── api/app.py               # Flask app — metrics, traces, Logic App calls
│       └── web/index.html           # Storefront UI
├── inventory-service/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── src/app.py                   # Inventory service — DB pool simulation
├── helm/
│   ├── storefront/                  # Helm chart — chaos values, secret mount, Azure URLs
│   └── inventory-service/           # Helm chart — DB saturation, slow query knobs
├── chaos/
│   └── chaos.py                     # Traffic generator — normal/ramp/blackfriday/recovery
└── terraform/
    ├── azure/                       # Logic Apps, Log Analytics, App Insights, SP
    └── grafana/                     # Alert rules as code
```

---

## Minikube Restart Checklist

```bash
minikube start
sudo systemctl start alloy.service
kubectl get pods
curl http://192.168.58.2:30100/health

# If Azure Logic Apps are configured
helm upgrade ensemble-storefront ./helm/storefront -f azure-values.yaml

# Start traffic
python3 chaos/chaos.py --mode normal --url http://192.168.58.2:30100 &
```