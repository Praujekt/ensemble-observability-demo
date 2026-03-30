from flask import Flask, jsonify, request, send_from_directory
import requests
import random
import time
import os
import logging
import json
import base64
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST

# ── OpenTelemetry tracing ─────────────────────────────────────────────
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.sdk.resources import Resource

resource = Resource.create({
    "service.name": "ensemble-storefront",
    "service.version": "1.0.0",
    "deployment.environment": "demo",
})

_tempo_creds = base64.b64encode(
    f"1574720:{os.environ.get('GCLOUD_RW_API_KEY', '')}".encode()
).decode()

otlp_exporter = OTLPSpanExporter(
    endpoint="https://otlp-gateway-prod-us-west-0.grafana.net/otlp/v1/traces",
    headers={
        "Authorization": f"Basic {_tempo_creds}"
    },
)

provider = TracerProvider(resource=resource)
provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
trace.set_tracer_provider(provider)
tracer = trace.get_tracer("ensemble-storefront")

# ── Structured logging ───────────────────────────────────────────────
class JSONFormatter(logging.Formatter):
    def format(self, record):
        log = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "message": record.getMessage(),
            "service": "ensemble-storefront",
        }
        for key in ["endpoint", "sku", "user_id", "order_id", "duration_ms", "status_code", "error", "logic_app"]:
            if hasattr(record, key):
                log[key] = getattr(record, key)
        # Include trace context in logs for correlation
        span = trace.get_current_span()
        if span and span.is_recording():
            ctx = span.get_span_context()
            log["traceID"] = format(ctx.trace_id, '032x')
            log["spanID"]  = format(ctx.span_id, '016x')
        return json.dumps(log)

handler = logging.StreamHandler()
handler.setFormatter(JSONFormatter())
logger = logging.getLogger("ensemble")
logger.addHandler(handler)
logger.setLevel(logging.INFO)

app = Flask(__name__)

# Instrument Flask and requests AFTER app is created
FlaskInstrumentor().instrument_app(app)
RequestsInstrumentor().instrument()

# ── Prometheus metrics ───────────────────────────────────────────────
http_requests = Counter("ensemble_http_requests_total", "Total HTTP requests", ["endpoint", "method", "status_code"])
http_latency = Histogram("ensemble_http_request_duration_seconds", "HTTP request duration", ["endpoint"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0])
checkout_duration = Histogram("ensemble_checkout_duration_seconds", "Checkout processing duration",
    buckets=[0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0])
checkout_errors = Counter("ensemble_checkout_errors_total", "Total checkout errors", ["reason"])
checkout_total = Counter("ensemble_checkouts_total", "Total completed checkouts")
active_users = Gauge("ensemble_active_users", "Simulated concurrent active users")
cart_size = Histogram("ensemble_cart_items", "Items in cart at checkout", buckets=[1, 2, 3, 5, 8, 13])
inventory_call_duration = Histogram("ensemble_inventory_call_duration_seconds", "Inventory call duration",
    ["endpoint"], buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0])
inventory_call_errors = Counter("ensemble_inventory_call_errors_total", "Inventory call errors", ["status_code"])
revenue_total = Counter("ensemble_revenue_total_cents", "Total revenue in cents")

# ── Azure Logic App / Serverless metrics ─────────────────────────────
logic_app_calls = Counter(
    "ensemble_logic_app_calls_total",
    "Total Logic App calls — correlates with Azure Monitor RunsStarted",
    ["logic_app", "status"]
)
logic_app_duration = Histogram(
    "ensemble_logic_app_duration_seconds",
    "Logic App execution duration — correlates with Azure Monitor RunDuration",
    ["logic_app"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0]
)
logic_app_failures = Counter(
    "ensemble_logic_app_failures_total",
    "Logic App failures — correlates with Azure Monitor RunsFailed",
    ["logic_app", "error_type"]
)
serverless_throttles = Counter(
    "ensemble_serverless_throttles_total",
    "Throttled serverless calls — maps to Azure Monitor ThrottledRuns",
    ["service"]
)

# ── Config ───────────────────────────────────────────────────────────
INVENTORY_URL      = os.environ.get("INVENTORY_URL", "http://ensemble-inventory:5001")
FRAUD_CHECK_URL    = os.environ.get("AZURE_FRAUD_CHECK_URL", "")
LOYALTY_POINTS_URL = os.environ.get("AZURE_LOYALTY_POINTS_URL", "")
ORDER_NOTIFY_URL   = os.environ.get("AZURE_ORDER_NOTIFY_URL", "")

PRODUCTS = [
    {"sku": "SKU-001", "name": "Merino Wool Sweater",  "price": 89.99},
    {"sku": "SKU-002", "name": "Slim Fit Chinos",       "price": 64.99},
    {"sku": "SKU-003", "name": "Oxford Button-Down",    "price": 49.99},
    {"sku": "SKU-004", "name": "Leather Derby Shoes",   "price": 129.99},
    {"sku": "SKU-005", "name": "Cashmere Scarf",        "price": 74.99},
    {"sku": "SKU-006", "name": "Trench Coat",           "price": 199.99},
    {"sku": "SKU-007", "name": "Linen Blazer",          "price": 149.99},
    {"sku": "SKU-008", "name": "Raw Denim Jeans",       "price": 94.99},
]


def get_chaos_config():
    return {
        "checkout_delay":          float(os.environ.get("CHAOS_CHECKOUT_DELAY", "0")),
        "error_rate":              float(os.environ.get("CHAOS_ERROR_RATE", "0")),
        "active_users_multiplier": float(os.environ.get("CHAOS_USER_MULTIPLIER", "1")),
        "logic_app_error_rate":    float(os.environ.get("CHAOS_LOGIC_APP_ERROR_RATE", "0")),
        "logic_app_slow_rate":     float(os.environ.get("CHAOS_LOGIC_APP_SLOW_RATE", "0")),
    }


def update_active_users():
    chaos = get_chaos_config()
    active_users.set(int(random.randint(40, 80) * chaos["active_users_multiplier"]))


def call_logic_app(name, url, payload, timeout=5):
    """
    Calls an Azure Logic App with OpenTelemetry span tracking.
    Each Logic App call gets its own span so the waterfall shows
    exactly how long each Azure service took.
    """
    chaos = get_chaos_config()
    start = time.time()

    with tracer.start_as_current_span(f"logic_app.{name}") as span:
        span.set_attribute("logic_app.name", name)
        span.set_attribute("logic_app.mode", "azure" if url else "simulated")

        # Chaos: throttle
        if random.random() < chaos["logic_app_slow_rate"] * 0.15:
            serverless_throttles.labels(service=name).inc()
            logic_app_calls.labels(logic_app=name, status="throttled").inc()
            logic_app_duration.labels(logic_app=name).observe(time.time() - start)
            span.set_attribute("logic_app.result", "throttled")
            span.set_status(trace.StatusCode.ERROR, "throttled")
            logger.warning("Logic App throttled", extra={"logic_app": name,
                "duration_ms": round((time.time()-start)*1000)})
            return False, "throttled"

        # Chaos: inject failures
        if random.random() < chaos["logic_app_error_rate"]:
            error_type = random.choice(["timeout", "upstream_error", "bad_request"])
            logic_app_failures.labels(logic_app=name, error_type=error_type).inc()
            logic_app_calls.labels(logic_app=name, status="failed").inc()
            logic_app_duration.labels(logic_app=name).observe(time.time() - start)
            span.set_attribute("logic_app.result", "failed")
            span.set_attribute("logic_app.error_type", error_type)
            span.set_status(trace.StatusCode.ERROR, error_type)
            logger.error("Logic App failed", extra={"logic_app": name, "error": error_type,
                "duration_ms": round((time.time()-start)*1000)})
            return False, error_type

        if url:
            try:
                if chaos["logic_app_slow_rate"] > 0:
                    time.sleep(random.uniform(chaos["logic_app_slow_rate"],
                        chaos["logic_app_slow_rate"] * 2.5))
                resp = requests.post(url, json=payload, timeout=timeout)
                duration = time.time() - start
                logic_app_duration.labels(logic_app=name).observe(duration)
                span.set_attribute("logic_app.duration_ms", round(duration * 1000))
                span.set_attribute("http.status_code", resp.status_code)
                if resp.status_code in [200, 202]:
                    logic_app_calls.labels(logic_app=name, status="success").inc()
                    span.set_attribute("logic_app.result", "success")
                    logger.info("Logic App succeeded", extra={"logic_app": name,
                        "duration_ms": round(duration*1000), "status_code": resp.status_code})
                    return True, "success"
                else:
                    logic_app_failures.labels(logic_app=name, error_type=str(resp.status_code)).inc()
                    logic_app_calls.labels(logic_app=name, status="failed").inc()
                    span.set_status(trace.StatusCode.ERROR, str(resp.status_code))
                    logger.error("Logic App error response", extra={"logic_app": name,
                        "status_code": resp.status_code, "duration_ms": round(duration*1000)})
                    return False, str(resp.status_code)
            except requests.Timeout:
                logic_app_failures.labels(logic_app=name, error_type="timeout").inc()
                logic_app_calls.labels(logic_app=name, status="failed").inc()
                logic_app_duration.labels(logic_app=name).observe(time.time()-start)
                span.set_status(trace.StatusCode.ERROR, "timeout")
                logger.error("Logic App timed out", extra={"logic_app": name,
                    "duration_ms": round((time.time()-start)*1000)})
                return False, "timeout"
            except Exception as e:
                logic_app_failures.labels(logic_app=name, error_type="exception").inc()
                logic_app_calls.labels(logic_app=name, status="failed").inc()
                logic_app_duration.labels(logic_app=name).observe(time.time()-start)
                span.set_status(trace.StatusCode.ERROR, str(e))
                logger.error("Logic App exception", extra={"logic_app": name, "error": str(e)})
                return False, "exception"
        else:
            base = {"fraud-check": 0.12, "loyalty-points": 0.08,
                    "order-notification": 0.05}.get(name, 0.1)
            if chaos["logic_app_slow_rate"] > 0:
                base += random.uniform(chaos["logic_app_slow_rate"],
                    chaos["logic_app_slow_rate"] * 2)
            time.sleep(base + random.uniform(0, 0.03))
            duration = time.time() - start
            logic_app_calls.labels(logic_app=name, status="success").inc()
            logic_app_duration.labels(logic_app=name).observe(duration)
            span.set_attribute("logic_app.result", "success")
            span.set_attribute("logic_app.duration_ms", round(duration * 1000))
            logger.info("Logic App simulated", extra={"logic_app": name,
                "duration_ms": round(duration*1000), "mode": "simulated"})
            return True, "success"


# ── Routes ───────────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(
        os.path.join(os.path.dirname(__file__), "..", "web"), "index.html")


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "service": "ensemble-storefront",
        "logic_apps_configured": bool(FRAUD_CHECK_URL),
    }), 200


@app.route("/metrics")
def metrics():
    update_active_users()
    return generate_latest(), 200, {"Content-Type": CONTENT_TYPE_LATEST}


@app.route("/api/products")
def get_products():
    start = time.time()
    update_active_users()
    try:
        inv_start = time.time()
        resp = requests.get(f"{INVENTORY_URL}/inventory/bulk", timeout=3)
        inventory_call_duration.labels(endpoint="/inventory/bulk").observe(
            time.time() - inv_start)
        inv_data = ({p["sku"]: p for p in resp.json().get("products", [])}
            if resp.status_code == 200 else {})
        if resp.status_code != 200:
            inventory_call_errors.labels(status_code=str(resp.status_code)).inc()
    except Exception as e:
        inventory_call_errors.labels(status_code="timeout").inc()
        inv_data = {}
        logger.warning("Inventory unavailable", extra={"error": str(e)})

    products = [{**p,
        "stock": inv_data.get(p["sku"], {}).get("stock", 0),
        "available": inv_data.get(p["sku"], {}).get("stock", 0) > 0}
        for p in PRODUCTS]
    duration = time.time() - start
    http_requests.labels(endpoint="/api/products", method="GET", status_code="200").inc()
    http_latency.labels(endpoint="/api/products").observe(duration)
    logger.info("Products fetched", extra={"endpoint": "/api/products",
        "duration_ms": round(duration*1000)})
    return jsonify({"products": products})


@app.route("/api/product/<sku>")
def get_product(sku):
    start = time.time()
    try:
        resp = requests.get(f"{INVENTORY_URL}/inventory/{sku}", timeout=3)
        inventory_call_duration.labels(endpoint="/inventory/sku").observe(
            time.time() - start)
        if resp.status_code == 200:
            http_requests.labels(endpoint="/api/product", method="GET",
                status_code="200").inc()
            http_latency.labels(endpoint="/api/product").observe(time.time() - start)
            return jsonify(resp.json())
        inventory_call_errors.labels(status_code=str(resp.status_code)).inc()
        http_requests.labels(endpoint="/api/product", method="GET",
            status_code=str(resp.status_code)).inc()
        http_latency.labels(endpoint="/api/product").observe(time.time() - start)
        return jsonify({"error": "Not found"}), resp.status_code
    except Exception:
        inventory_call_errors.labels(status_code="timeout").inc()
        http_requests.labels(endpoint="/api/product", method="GET",
            status_code="503").inc()
        http_latency.labels(endpoint="/api/product").observe(time.time() - start)
        return jsonify({"error": "Inventory unavailable"}), 503


@app.route("/api/checkout", methods=["POST"])
def checkout():
    start = time.time()
    chaos = get_chaos_config()
    order_id = f"ORD-{random.randint(10000, 99999)}"
    data = request.get_json(silent=True) or {}
    items = data.get("items", [{"sku": "SKU-001", "qty": 1}])

    # Set order_id on the current span so it appears in traces
    span = trace.get_current_span()
    span.set_attribute("order.id", order_id)
    span.set_attribute("order.item_count", len(items))

    logger.info("Checkout started", extra={"order_id": order_id,
        "endpoint": "/api/checkout"})
    cart_size.observe(len(items))

    # Error injection
    if random.random() < chaos["error_rate"]:
        reason = random.choice(["payment_declined", "inventory_unavailable",
            "session_expired"])
        checkout_errors.labels(reason=reason).inc()
        checkout_duration.observe(time.time() - start)
        http_requests.labels(endpoint="/api/checkout", method="POST",
            status_code="500").inc()
        http_latency.labels(endpoint="/api/checkout").observe(time.time() - start)
        span.set_status(trace.StatusCode.ERROR, reason)
        logger.error("Checkout failed", extra={"order_id": order_id, "error": reason,
            "duration_ms": round((time.time()-start)*1000)})
        return jsonify({"error": f"Checkout failed: {reason}"}), 500

    # Step 1: Fraud check Logic App
    fraud_ok, fraud_status = call_logic_app("fraud-check", FRAUD_CHECK_URL,
        {"order_id": order_id, "items": items})
    if not fraud_ok and fraud_status in ["timeout", "upstream_error"]:
        logger.warning("Fraud check degraded, proceeding", extra={
            "order_id": order_id})

    # Step 2: Inventory check
    total = 0.0
    for item in items:
        sku = item.get("sku", "SKU-001")
        qty = item.get("qty", 1)
        with tracer.start_as_current_span(f"inventory.lookup") as inv_span:
            inv_span.set_attribute("inventory.sku", sku)
            inv_span.set_attribute("inventory.qty", qty)
            try:
                inv_start = time.time()
                resp = requests.get(f"{INVENTORY_URL}/inventory/{sku}", timeout=3)
                inventory_call_duration.labels(endpoint="/inventory/sku").observe(
                    time.time() - inv_start)
                if resp.status_code != 200:
                    inventory_call_errors.labels(
                        status_code=str(resp.status_code)).inc()
                    checkout_errors.labels(reason="inventory_unavailable").inc()
                    checkout_duration.observe(time.time() - start)
                    http_requests.labels(endpoint="/api/checkout", method="POST",
                        status_code="503").inc()
                    http_latency.labels(endpoint="/api/checkout").observe(
                        time.time() - start)
                    inv_span.set_status(trace.StatusCode.ERROR, "inventory_unavailable")
                    logger.error("Inventory check failed", extra={
                        "order_id": order_id, "sku": sku})
                    return jsonify({"error": "Inventory unavailable"}), 503
                total += resp.json().get("price", 0) * qty
                inv_span.set_attribute("inventory.price", resp.json().get("price", 0))
            except requests.Timeout:
                inventory_call_errors.labels(status_code="timeout").inc()
                checkout_errors.labels(reason="inventory_timeout").inc()
                checkout_duration.observe(time.time() - start)
                http_requests.labels(endpoint="/api/checkout", method="POST",
                    status_code="504").inc()
                http_latency.labels(endpoint="/api/checkout").observe(
                    time.time() - start)
                inv_span.set_status(trace.StatusCode.ERROR, "timeout")
                logger.error("Inventory timeout", extra={
                    "order_id": order_id, "sku": sku})
                return jsonify({"error": "Checkout timed out"}), 504

    # Step 3: Processing delay (chaos)
    if chaos["checkout_delay"] > 0:
        delay = random.uniform(chaos["checkout_delay"] * 0.5,
            chaos["checkout_delay"] * 1.5)
        time.sleep(delay)
        logger.warning("Checkout slow", extra={"order_id": order_id,
            "delay_ms": round(delay*1000)})

    # Step 4: Post-purchase Logic Apps (non-blocking)
    call_logic_app("loyalty-points", LOYALTY_POINTS_URL,
        {"order_id": order_id, "total_cents": int(total*100)})
    call_logic_app("order-notification", ORDER_NOTIFY_URL,
        {"order_id": order_id, "total": total})

    # Success
    checkout_total.inc()
    revenue_total.inc(int(total * 100))
    duration = time.time() - start
    checkout_duration.observe(duration)
    http_requests.labels(endpoint="/api/checkout", method="POST",
        status_code="200").inc()
    http_latency.labels(endpoint="/api/checkout").observe(duration)
    span.set_attribute("order.total", round(total, 2))
    logger.info("Checkout completed", extra={"order_id": order_id,
        "duration_ms": round(duration*1000), "status_code": 200})
    return jsonify({"order_id": order_id, "status": "confirmed",
        "total": round(total, 2), "estimated_delivery": "3-5 business days"})


@app.route("/api/chaos/status")
def chaos_status():
    return jsonify(get_chaos_config())


@app.route("/api/logic-apps/status")
def logic_apps_status():
    return jsonify({
        "fraud_check": {
            "mode": "azure" if FRAUD_CHECK_URL else "simulated",
            "configured": bool(FRAUD_CHECK_URL)
        },
        "loyalty_points": {
            "mode": "azure" if LOYALTY_POINTS_URL else "simulated",
            "configured": bool(LOYALTY_POINTS_URL)
        },
        "order_notification": {
            "mode": "azure" if ORDER_NOTIFY_URL else "simulated",
            "configured": bool(ORDER_NOTIFY_URL)
        },
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)