#!/usr/bin/env python3
"""
Ensemble Black Friday Chaos Script
====================================
Simulates realistic e-commerce load patterns against the Ensemble storefront.
Run this during the demo to generate meaningful metrics in Grafana Cloud.

Usage:
  python3 chaos.py --mode normal        # Background traffic, no issues
  python3 chaos.py --mode ramp          # Gradually increasing load
  python3 chaos.py --mode blackfriday   # Full Black Friday chaos
  python3 chaos.py --mode recovery      # Post-incident recovery

Requires: requests (pip install requests)
"""

import argparse
import time
import random
import threading
import sys
import os
import signal
from datetime import datetime

try:
    import requests
    from requests.exceptions import RequestException
except ImportError:
    print("ERROR: requests library required. Run: pip install requests")
    sys.exit(1)

# ── Config ────────────────────────────────────────────────────────────
BASE_URL = os.environ.get("STOREFRONT_URL", "http://localhost:5000")
STOP_FLAG = threading.Event()
STATS = {
    "requests": 0,
    "success": 0,
    "errors": 0,
    "timeouts": 0,
    "total_latency": 0,
}
STATS_LOCK = threading.Lock()

SKUS = ["SKU-001", "SKU-002", "SKU-003", "SKU-004",
        "SKU-005", "SKU-006", "SKU-007", "SKU-008"]

COLORS = {
    "green":  "\033[92m",
    "yellow": "\033[93m",
    "red":    "\033[91m",
    "cyan":   "\033[96m",
    "reset":  "\033[0m",
    "bold":   "\033[1m",
    "dim":    "\033[2m",
}


def c(color, text):
    return f"{COLORS.get(color,'')}{text}{COLORS['reset']}"


def log(msg, level="info"):
    ts = datetime.now().strftime("%H:%M:%S")
    color = {"info": "cyan", "warn": "yellow", "error": "red", "success": "green"}.get(level, "reset")
    print(f"{c('dim', ts)} {c(color, msg)}")


def record(success, latency_ms, is_timeout=False):
    with STATS_LOCK:
        STATS["requests"] += 1
        STATS["total_latency"] += latency_ms
        if success:
            STATS["success"] += 1
        elif is_timeout:
            STATS["timeouts"] += 1
        else:
            STATS["errors"] += 1


# ── Traffic generators ────────────────────────────────────────────────
def browse_products(session, timeout=5):
    start = time.time()
    try:
        r = session.get(f"{BASE_URL}/api/products", timeout=timeout)
        latency = (time.time() - start) * 1000
        record(r.status_code == 200, latency)
        if r.status_code != 200:
            log(f"Products endpoint returned {r.status_code}", "warn")
        return r.status_code == 200
    except requests.Timeout:
        record(False, timeout * 1000, is_timeout=True)
        log("Products request TIMED OUT", "error")
        return False
    except RequestException as e:
        record(False, (time.time() - start) * 1000)
        return False


def view_product(session, sku=None, timeout=5):
    sku = sku or random.choice(SKUS)
    start = time.time()
    try:
        r = session.get(f"{BASE_URL}/api/product/{sku}", timeout=timeout)
        latency = (time.time() - start) * 1000
        record(r.status_code in [200, 404], latency)
        return r.status_code == 200
    except requests.Timeout:
        record(False, timeout * 1000, is_timeout=True)
        log(f"Product {sku} request TIMED OUT", "error")
        return False
    except RequestException:
        record(False, (time.time() - start) * 1000)
        return False


def do_checkout(session, items=None, timeout=10):
    if items is None:
        num_items = random.choices([1, 2, 3, 4], weights=[50, 30, 15, 5])[0]
        items = [{"sku": random.choice(SKUS), "qty": random.randint(1, 3)}
                 for _ in range(num_items)]
    start = time.time()
    try:
        r = session.post(
            f"{BASE_URL}/api/checkout",
            json={"items": items},
            timeout=timeout
        )
        latency = (time.time() - start) * 1000
        success = r.status_code == 200
        record(success, latency)
        if success:
            data = r.json()
            log(f"Order {data['order_id']} confirmed — ${data['total']:.2f} in {latency:.0f}ms", "success")
        else:
            log(f"Checkout FAILED {r.status_code} in {latency:.0f}ms", "error")
        return success
    except requests.Timeout:
        latency = (time.time() - start) * 1000
        record(False, latency, is_timeout=True)
        log(f"CHECKOUT TIMED OUT after {latency:.0f}ms — customer lost!", "error")
        return False
    except RequestException as e:
        record(False, (time.time() - start) * 1000)
        log(f"Checkout connection error: {e}", "error")
        return False


def simulated_user(mode, user_id):
    """Simulate one user's shopping session."""
    session = requests.Session()
    checkout_probability = {
        "normal": 0.15,
        "ramp": 0.20,
        "blackfriday": 0.35,
        "recovery": 0.10,
    }.get(mode, 0.15)

    timeout = {
        "normal": 5,
        "ramp": 4,
        "blackfriday": 8,
        "recovery": 5,
    }.get(mode, 5)

    while not STOP_FLAG.is_set():
        # Browse products
        browse_products(session, timeout=timeout)
        time.sleep(random.uniform(0.2, 1.0))

        # View a specific product
        if random.random() < 0.7:
            view_product(session, timeout=timeout)
            time.sleep(random.uniform(0.1, 0.5))

        # Maybe checkout
        if random.random() < checkout_probability:
            do_checkout(session, timeout=timeout)

        # Think time between actions
        think_time = {
            "normal": random.uniform(2, 8),
            "ramp": random.uniform(1, 4),
            "blackfriday": random.uniform(0.3, 2),
            "recovery": random.uniform(3, 10),
        }.get(mode, 3)

        STOP_FLAG.wait(think_time)


def stats_reporter():
    """Print live stats every 10 seconds."""
    while not STOP_FLAG.is_set():
        STOP_FLAG.wait(10)
        if STOP_FLAG.is_set():
            break
        with STATS_LOCK:
            total = STATS["requests"]
            if total == 0:
                continue
            success_rate = (STATS["success"] / total) * 100
            avg_latency = STATS["total_latency"] / total
            error_rate = (STATS["errors"] / total) * 100

        color = "green" if success_rate > 99 else ("yellow" if success_rate > 95 else "red")
        print(f"\n{'─'*60}")
        print(f"  {c('bold', 'LIVE STATS')}  |  {datetime.now().strftime('%H:%M:%S')}")
        print(f"  Requests:     {c('cyan', str(total))}")
        print(f"  Success rate: {c(color, f'{success_rate:.1f}%')}")
        print(f"  Avg latency:  {c('cyan', f'{avg_latency:.0f}ms')}")
        print(f"  Errors:       {c('red' if STATS['errors'] > 0 else 'dim', str(STATS['errors']))}")
        print(f"  Timeouts:     {c('red' if STATS['timeouts'] > 0 else 'dim', str(STATS['timeouts']))}")
        print(f"{'─'*60}\n")


# ── Modes ─────────────────────────────────────────────────────────────
def run_normal():
    """Normal business hours traffic — 10-20 concurrent users."""
    log("Starting NORMAL mode — steady background traffic", "info")
    log(f"Target: {BASE_URL}", "info")
    threads = []
    for i in range(15):
        t = threading.Thread(target=simulated_user, args=("normal", i), daemon=True)
        t.start()
        threads.append(t)
        time.sleep(random.uniform(0.2, 0.8))
    log(f"15 simulated users active", "success")
    return threads


def run_ramp():
    """Gradually ramp from 10 to 80 users over 3 minutes — pre-Black Friday surge."""
    log("Starting RAMP mode — gradually increasing load", "info")
    log("Watch your Grafana dashboards for the trend line building...", "dim")
    threads = []
    target = 80
    ramp_time = 180  # 3 minutes

    for i in range(target):
        if STOP_FLAG.is_set():
            break
        t = threading.Thread(target=simulated_user, args=("ramp", i), daemon=True)
        t.start()
        threads.append(t)
        sleep_per_user = ramp_time / target
        log(f"User {i+1}/{target} active ({len(threads)} concurrent)", "info")
        STOP_FLAG.wait(sleep_per_user)

    log(f"Ramp complete — {len(threads)} concurrent users", "success")
    return threads


def run_blackfriday():
    """
    Black Friday chaos — simulates the Ensemble outage scenario:
    1. Massive user surge (200+ concurrent)
    2. Checkout delays start building
    3. Error rate climbs
    4. Inventory service starts failing
    This generates the exact metrics pattern you want to show in Grafana.
    """
    log(c("bold", "🚨 BLACK FRIDAY MODE ACTIVATED"), "warn")
    log("This will simulate the Ensemble outage scenario", "warn")
    log("Watch Grafana for: latency spike → error rate rise → cascade failure", "warn")
    print()

    threads = []

    # Phase 1: Initial surge (0-60s)
    log("PHASE 1: User surge beginning...", "warn")
    for i in range(60):
        if STOP_FLAG.is_set():
            break
        t = threading.Thread(target=simulated_user, args=("blackfriday", i), daemon=True)
        t.start()
        threads.append(t)
        STOP_FLAG.wait(0.5)

    log(f"60 users active — traffic elevated", "warn")
    STOP_FLAG.wait(30)

    # Phase 2: Ramp to peak (60-120s)
    log("PHASE 2: Traffic continuing to surge...", "error")
    for i in range(60, 150):
        if STOP_FLAG.is_set():
            break
        t = threading.Thread(target=simulated_user, args=("blackfriday", i), daemon=True)
        t.start()
        threads.append(t)
        STOP_FLAG.wait(0.3)

    log(f"150 users active — CRITICAL LOAD", "error")
    STOP_FLAG.wait(60)

    # Phase 3: Sustained peak (120s+)
    log("PHASE 3: Sustained peak load — system under maximum stress", "error")
    log("Check Grafana: checkout p95 latency and error rate should be spiking", "error")

    return threads


def run_recovery():
    """Gradual recovery after an incident — traffic drops, errors clear."""
    log("Starting RECOVERY mode — traffic tapering off post-incident", "success")
    log("Watch error rates drop and latency normalize in Grafana", "info")
    threads = []
    for i in range(20):
        if STOP_FLAG.is_set():
            break
        t = threading.Thread(target=simulated_user, args=("recovery", i), daemon=True)
        t.start()
        threads.append(t)
        STOP_FLAG.wait(1.0)
    log(f"20 users — recovery traffic active", "success")
    return threads


# ── Main ──────────────────────────────────────────────────────────────
def signal_handler(sig, frame):
    log("\nShutting down chaos script...", "warn")
    STOP_FLAG.set()
    sys.exit(0)


def main():
    parser = argparse.ArgumentParser(
        description="Ensemble Black Friday Chaos Script",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        "--mode",
        choices=["normal", "ramp", "blackfriday", "recovery"],
        default="normal",
        help="Traffic mode to simulate"
    )
    parser.add_argument(
        "--url",
        default=BASE_URL,
        help=f"Storefront base URL (default: {BASE_URL})"
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=0,
        help="Run for N seconds then stop (0 = run until Ctrl+C)"
    )
    args = parser.parse_args()

    global BASE_URL
    BASE_URL = args.url

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    print(f"""
{c('bold', '╔══════════════════════════════════════════╗')}
{c('bold', '║')}    {c('yellow', 'ENSEMBLE BLACK FRIDAY CHAOS SCRIPT')}    {c('bold', '║')}
{c('bold', '╚══════════════════════════════════════════╝')}

  Mode:    {c('cyan', args.mode.upper())}
  Target:  {c('cyan', BASE_URL)}
  Press {c('yellow', 'Ctrl+C')} to stop
""")

    # Check connectivity
    try:
        r = requests.get(f"{BASE_URL}/health", timeout=5)
        if r.status_code == 200:
            log("Storefront health check: OK", "success")
        else:
            log(f"Storefront returned {r.status_code} — proceeding anyway", "warn")
    except RequestException as e:
        log(f"Cannot reach storefront at {BASE_URL}", "error")
        log(f"Make sure the app is running: kubectl port-forward svc/ensemble-storefront 5000:5000", "warn")
        sys.exit(1)

    # Start stats reporter
    reporter = threading.Thread(target=stats_reporter, daemon=True)
    reporter.start()

    # Run selected mode
    mode_funcs = {
        "normal": run_normal,
        "ramp": run_ramp,
        "blackfriday": run_blackfriday,
        "recovery": run_recovery,
    }
    threads = mode_funcs[args.mode]()

    # Wait for duration or Ctrl+C
    if args.duration > 0:
        log(f"Running for {args.duration} seconds...", "info")
        STOP_FLAG.wait(args.duration)
        STOP_FLAG.set()
    else:
        log("Running until Ctrl+C...", "info")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass

    STOP_FLAG.set()
    log("Chaos script stopped.", "info")

    with STATS_LOCK:
        total = STATS["requests"]
        if total > 0:
            print(f"\n{c('bold', 'FINAL STATS')}")
            print(f"  Total requests: {total}")
            print(f"  Success rate:   {(STATS['success']/total)*100:.1f}%")
            print(f"  Avg latency:    {STATS['total_latency']/total:.0f}ms")
            print(f"  Errors:         {STATS['errors']}")
            print(f"  Timeouts:       {STATS['timeouts']}")


if __name__ == "__main__":
    main()
