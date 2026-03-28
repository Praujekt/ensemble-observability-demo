from flask import Flask, jsonify, request, send_from_directory
import requests
import random
import time
import os
import logging
import json
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST

# ── Structured logging ───────────────────────────────────────────────
class JSONFormatter(logging.Formatter):
    def format(self, record):
        log = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "message": record.getMessage(),
            "service": "ensemble-storefront",
        }
        for key in ["endpoint", "sku", "user_id", "order_id", "duration_ms", "status_code", "error"]:
            if hasattr(record, key):
                log[key] = getattr(record, key)
        return json.dumps(log)

handler = logging.StreamHandler()
handler.setFormatter(JSONFormatter())
logger = logging.getLogger("ensemble")
logger.addHandler(handler)
logger.setLevel(logging.INFO)

app = Flask(__name__)

# ── Prometheus metrics ───────────────────────────────────────────────
http_requests = Counter(
    "ensemble_http_requests_total",
    "Total HTTP requests",
    ["endpoint", "method", "status_code"]
)
http_latency = Histogram(
    "ensemble_http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["endpoint"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
)
checkout_duration = Histogram(
    "ensemble_checkout_duration_seconds",
    "Checkout processing duration",
    buckets=[0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0]
)
checkout_errors = Counter(
    "ensemble_checkout_errors_total",
    "Total checkout errors",
    ["reason"]
)
checkout_total = Counter(
    "ensemble_checkouts_total",
    "Total completed checkouts"
)
active_users = Gauge(
    "ensemble_active_users",
    "Simulated concurrent active users"
)
cart_size = Histogram(
    "ensemble_cart_items",
    "Number of items in cart at checkout",
    buckets=[1, 2, 3, 5, 8, 13]
)
inventory_call_duration = Histogram(
    "ensemble_inventory_call_duration_seconds",
    "Time spent calling inventory service",
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0]
)
inventory_call_errors = Counter(
    "ensemble_inventory_call_errors_total",
    "Errors calling inventory service",
    ["status_code"]
)
revenue_total = Counter(
    "ensemble_revenue_total_cents",
    "Total revenue in cents"
)

# ── Config ───────────────────────────────────────────────────────────
INVENTORY_URL = os.environ.get("INVENTORY_URL", "http://ensemble-inventory:5001")

PRODUCTS = [
    {"sku": "SKU-001", "name": "Merino Wool Sweater", "price": 89.99, "image": "sweater"},
    {"sku": "SKU-002", "name": "Slim Fit Chinos", "price": 64.99, "image": "chinos"},
    {"sku": "SKU-003", "name": "Oxford Button-Down", "price": 49.99, "image": "shirt"},
    {"sku": "SKU-004", "name": "Leather Derby Shoes", "price": 129.99, "image": "shoes"},
    {"sku": "SKU-005", "name": "Cashmere Scarf", "price": 74.99, "image": "scarf"},
    {"sku": "SKU-006", "name": "Trench Coat", "price": 199.99, "image": "coat"},
    {"sku": "SKU-007", "name": "Linen Blazer", "price": 149.99, "image": "blazer"},
    {"sku": "SKU-008", "name": "Raw Denim Jeans", "price": 94.99, "image": "jeans"},
]


def get_chaos_config():
    return {
        "checkout_delay": float(os.environ.get("CHAOS_CHECKOUT_DELAY", "0")),
        "error_rate": float(os.environ.get("CHAOS_ERROR_RATE", "0")),
        "active_users_multiplier": float(os.environ.get("CHAOS_USER_MULTIPLIER", "1")),
    }


def update_active_users():
    chaos = get_chaos_config()
    base = random.randint(40, 80)
    active_users.set(int(base * chaos["active_users_multiplier"]))


# ── Routes ───────────────────────────────────────────────────────────
@app.route("/")
def index():
    web_dir = os.path.join(os.path.dirname(__file__), "..", "web")
    return send_from_directory(web_dir, "index.html")


@app.route("/health")
def health():
    return jsonify({"status": "ok", "service": "ensemble-storefront"}), 200


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
        inv_duration = time.time() - inv_start
        inventory_call_duration.observe(inv_duration)

        if resp.status_code == 200:
            inv_data = {p["sku"]: p for p in resp.json().get("products", [])}
        else:
            inventory_call_errors.labels(status_code=str(resp.status_code)).inc()
            inv_data = {}
    except Exception as e:
        inventory_call_errors.labels(status_code="timeout").inc()
        inv_data = {}
        logger.warning("Inventory service unavailable", extra={"error": str(e)})

    products = []
    for p in PRODUCTS:
        inv = inv_data.get(p["sku"], {})
        products.append({
            **p,
            "stock": inv.get("stock", 0),
            "available": inv.get("stock", 0) > 0,
        })

    duration = time.time() - start
    http_requests.labels(endpoint="/api/products", method="GET", status_code="200").inc()
    http_latency.labels(endpoint="/api/products").observe(duration)
    logger.info("Products fetched", extra={"endpoint": "/api/products", "duration_ms": round(duration * 1000)})
    return jsonify({"products": products})


@app.route("/api/product/<sku>")
def get_product(sku):
    start = time.time()

    try:
        inv_start = time.time()
        resp = requests.get(f"{INVENTORY_URL}/inventory/{sku}", timeout=3)
        inv_duration = time.time() - inv_start
        inventory_call_duration.observe(inv_duration)

        if resp.status_code == 200:
            data = resp.json()
            duration = time.time() - start
            http_requests.labels(endpoint="/api/product", method="GET", status_code="200").inc()
            http_latency.labels(endpoint="/api/product").observe(duration)
            return jsonify(data)
        else:
            inventory_call_errors.labels(status_code=str(resp.status_code)).inc()
            duration = time.time() - start
            http_requests.labels(endpoint="/api/product", method="GET", status_code=str(resp.status_code)).inc()
            http_latency.labels(endpoint="/api/product").observe(duration)
            return jsonify({"error": "Product not found"}), resp.status_code
    except Exception as e:
        inventory_call_errors.labels(status_code="timeout").inc()
        duration = time.time() - start
        http_requests.labels(endpoint="/api/product", method="GET", status_code="503").inc()
        http_latency.labels(endpoint="/api/product").observe(duration)
        return jsonify({"error": "Inventory service unavailable"}), 503


@app.route("/api/checkout", methods=["POST"])
def checkout():
    start = time.time()
    chaos = get_chaos_config()
    order_id = f"ORD-{random.randint(10000, 99999)}"
    data = request.get_json(silent=True) or {}
    items = data.get("items", [{"sku": "SKU-001", "qty": 1}])

    logger.info("Checkout started", extra={"order_id": order_id, "endpoint": "/api/checkout"})
    cart_size.observe(len(items))

    # Simulate error rate
    if random.random() < chaos["error_rate"]:
        reason = random.choice(["payment_declined", "inventory_unavailable", "session_expired"])
        checkout_errors.labels(reason=reason).inc()
        duration = time.time() - start
        checkout_duration.observe(duration)
        http_requests.labels(endpoint="/api/checkout", method="POST", status_code="500").inc()
        http_latency.labels(endpoint="/api/checkout").observe(duration)
        logger.error("Checkout failed", extra={
            "order_id": order_id,
            "endpoint": "/api/checkout",
            "error": reason,
            "duration_ms": round(duration * 1000)
        })
        return jsonify({"error": f"Checkout failed: {reason}"}), 500

    # Check inventory for each item
    total = 0.0
    for item in items:
        sku = item.get("sku", "SKU-001")
        qty = item.get("qty", 1)
        try:
            inv_start = time.time()
            resp = requests.get(f"{INVENTORY_URL}/inventory/{sku}", timeout=3)
            inventory_call_duration.observe(time.time() - inv_start)

            if resp.status_code != 200:
                inventory_call_errors.labels(status_code=str(resp.status_code)).inc()
                checkout_errors.labels(reason="inventory_unavailable").inc()
                duration = time.time() - start
                checkout_duration.observe(duration)
                http_requests.labels(endpoint="/api/checkout", method="POST", status_code="503").inc()
                http_latency.labels(endpoint="/api/checkout").observe(duration)
                logger.error("Checkout blocked by inventory failure", extra={
                    "order_id": order_id, "sku": sku, "error": "inventory_503"
                })
                return jsonify({"error": "Inventory service unavailable"}), 503

            product = resp.json()
            total += product.get("price", 0) * qty

        except requests.Timeout:
            inventory_call_errors.labels(status_code="timeout").inc()
            checkout_errors.labels(reason="inventory_timeout").inc()
            duration = time.time() - start
            checkout_duration.observe(duration)
            http_requests.labels(endpoint="/api/checkout", method="POST", status_code="504").inc()
            http_latency.labels(endpoint="/api/checkout").observe(duration)
            logger.error("Checkout timeout waiting for inventory", extra={
                "order_id": order_id, "sku": sku, "error": "timeout"
            })
            return jsonify({"error": "Checkout timed out"}), 504

    # Simulate checkout processing delay (Black Friday chaos)
    if chaos["checkout_delay"] > 0:
        delay = random.uniform(chaos["checkout_delay"] * 0.5, chaos["checkout_delay"] * 1.5)
        time.sleep(delay)
        logger.warning("Checkout processing slow", extra={
            "order_id": order_id,
            "delay_ms": round(delay * 1000),
            "endpoint": "/api/checkout"
        })

    # Success
    checkout_total.inc()
    revenue_total.inc(int(total * 100))
    duration = time.time() - start
    checkout_duration.observe(duration)
    http_requests.labels(endpoint="/api/checkout", method="POST", status_code="200").inc()
    http_latency.labels(endpoint="/api/checkout").observe(duration)
    logger.info("Checkout completed", extra={
        "order_id": order_id,
        "duration_ms": round(duration * 1000),
        "status_code": 200,
        "endpoint": "/api/checkout"
    })
    return jsonify({
        "order_id": order_id,
        "status": "confirmed",
        "total": round(total, 2),
        "estimated_delivery": "3-5 business days"
    })


@app.route("/api/chaos/status")
def chaos_status():
    return jsonify(get_chaos_config())


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
