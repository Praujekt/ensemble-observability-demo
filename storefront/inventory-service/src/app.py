from flask import Flask, jsonify
import random
import time
import os
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST

app = Flask(__name__)

# ── Prometheus metrics ──────────────────────────────────────────────
inventory_requests = Counter(
    "inventory_requests_total",
    "Total inventory service requests",
    ["endpoint", "status"]
)
inventory_latency = Histogram(
    "inventory_request_duration_seconds",
    "Inventory request duration",
    ["endpoint"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0]
)
db_pool_available = Gauge(
    "inventory_db_pool_available",
    "Available database connections in pool"
)
db_pool_total = Gauge(
    "inventory_db_pool_total",
    "Total database connection pool size"
)
inventory_lookups_failed = Counter(
    "inventory_lookup_failures_total",
    "Failed inventory lookups"
)

# ── Chaos state (controlled by env vars at runtime) ──────────────────
POOL_SIZE = 10
db_pool_used = 0

PRODUCTS = {
    "SKU-001": {"name": "Merino Wool Sweater", "price": 89.99, "stock": 142},
    "SKU-002": {"name": "Slim Fit Chinos", "price": 64.99, "stock": 87},
    "SKU-003": {"name": "Oxford Button-Down", "price": 49.99, "stock": 203},
    "SKU-004": {"name": "Leather Derby Shoes", "price": 129.99, "stock": 34},
    "SKU-005": {"name": "Cashmere Scarf", "price": 74.99, "stock": 61},
    "SKU-006": {"name": "Trench Coat", "price": 199.99, "stock": 28},
    "SKU-007": {"name": "Linen Blazer", "price": 149.99, "stock": 45},
    "SKU-008": {"name": "Raw Denim Jeans", "price": 94.99, "stock": 118},
}


def get_chaos_config():
    return {
        "db_saturation": float(os.environ.get("CHAOS_DB_SATURATION", "0")),
        "slow_queries": float(os.environ.get("CHAOS_SLOW_QUERIES", "0")),
        "error_rate": float(os.environ.get("CHAOS_ERROR_RATE", "0")),
    }


@app.route("/health")
def health():
    return jsonify({"status": "ok", "service": "inventory"}), 200


@app.route("/metrics")
def metrics():
    chaos = get_chaos_config()
    pool_available = max(0, POOL_SIZE - int(POOL_SIZE * chaos["db_saturation"]))
    db_pool_available.set(pool_available)
    db_pool_total.set(POOL_SIZE)
    return generate_latest(), 200, {"Content-Type": CONTENT_TYPE_LATEST}


@app.route("/inventory/<sku>")
def get_inventory(sku):
    start = time.time()
    chaos = get_chaos_config()

    # Simulate DB pool saturation
    pool_available = max(0, POOL_SIZE - int(POOL_SIZE * chaos["db_saturation"]))
    db_pool_available.set(pool_available)
    db_pool_total.set(POOL_SIZE)

    # If pool is saturated, fail fast
    if pool_available == 0:
        inventory_lookups_failed.inc()
        inventory_requests.labels(endpoint="/inventory", status="503").inc()
        inventory_latency.labels(endpoint="/inventory").observe(time.time() - start)
        return jsonify({"error": "Database connection pool exhausted"}), 503

    # Simulate slow queries
    if chaos["slow_queries"] > 0:
        delay = random.uniform(chaos["slow_queries"] * 0.5, chaos["slow_queries"] * 2.0)
        time.sleep(delay)

    # Simulate error rate
    if random.random() < chaos["error_rate"]:
        inventory_lookups_failed.inc()
        inventory_requests.labels(endpoint="/inventory", status="500").inc()
        inventory_latency.labels(endpoint="/inventory").observe(time.time() - start)
        return jsonify({"error": "Internal inventory error"}), 500

    product = PRODUCTS.get(sku)
    if not product:
        inventory_requests.labels(endpoint="/inventory", status="404").inc()
        inventory_latency.labels(endpoint="/inventory").observe(time.time() - start)
        return jsonify({"error": "SKU not found"}), 404

    inventory_requests.labels(endpoint="/inventory", status="200").inc()
    inventory_latency.labels(endpoint="/inventory").observe(time.time() - start)
    return jsonify({
        "sku": sku,
        "name": product["name"],
        "price": product["price"],
        "stock": max(0, product["stock"] - random.randint(0, 5)),
        "available": pool_available > 0
    })


@app.route("/inventory/bulk", methods=["GET"])
def get_bulk_inventory():
    start = time.time()
    chaos = get_chaos_config()

    if chaos["slow_queries"] > 0:
        time.sleep(random.uniform(chaos["slow_queries"], chaos["slow_queries"] * 3))

    items = []
    for sku, product in PRODUCTS.items():
        items.append({
            "sku": sku,
            "name": product["name"],
            "price": product["price"],
            "stock": product["stock"],
        })

    inventory_requests.labels(endpoint="/inventory/bulk", status="200").inc()
    inventory_latency.labels(endpoint="/inventory/bulk").observe(time.time() - start)
    return jsonify({"products": items, "count": len(items)})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=False)
