from flask import Flask, jsonify, request, Response
import time

app = Flask(__name__)

MOCK_EVENTS = [
    {"_time": "2026-03-30T13:45:00", "host": "ensemble-prod-01", "source": "checkout", "message": "DB connection pool exhausted — 0 connections available", "severity": "CRITICAL", "count": "847"},
    {"_time": "2026-03-30T13:46:00", "host": "ensemble-prod-01", "source": "checkout", "message": "Checkout timeout after 8000ms — inventory service unreachable", "severity": "ERROR", "count": "1203"},
    {"_time": "2026-03-30T13:47:00", "host": "ensemble-prod-02", "source": "inventory", "message": "inventory_db_pool_available=0 pool exhausted under Black Friday load", "severity": "CRITICAL", "count": "2841"},
    {"_time": "2026-03-30T13:48:00", "host": "ensemble-prod-01", "source": "fraud-check", "message": "Azure Logic App fraud-check timeout after 5000ms", "severity": "WARNING", "count": "412"},
    {"_time": "2026-03-30T13:49:00", "host": "ensemble-prod-02", "source": "checkout", "message": "payment_declined error rate 24% — exceeds 5% SLO threshold", "severity": "CRITICAL", "count": "634"},
]

@app.route("/services/server/info", methods=["GET"])
def server_info():
    return jsonify({
        "generator": "splunkd",
        "version": "9.1.0",
        "build": "ensemble-mock",
        "serverName": "splunk-onprem-ensemble",
        "os": "Linux",
        "cpu_arch": "x86_64",
    })

@app.route("/services/search/jobs", methods=["POST"])
def create_search_job():
    return jsonify({"sid": f"mock_search_{int(time.time())}"}), 201

@app.route("/services/search/jobs/<sid>", methods=["GET"])
def get_job_status(sid):
    return jsonify({
        "sid": sid,
        "content": {
            "dispatchState": "DONE",
            "resultCount": len(MOCK_EVENTS),
            "isDone": True,
        }
    })

@app.route("/services/search/jobs/<sid>/results", methods=["GET"])
def get_results(sid):
    query = request.args.get("search", "").lower()
    results = MOCK_EVENTS
    if "critical" in query:
        results = [e for e in MOCK_EVENTS if e["severity"] == "CRITICAL"]
    elif "error" in query:
        results = [e for e in MOCK_EVENTS if e["severity"] in ["ERROR", "CRITICAL"]]
    return jsonify({
        "results": results,
        "highlighted": {},
        "preview": False,
        "init_offset": 0,
        "messages": [],
        "fields": [
            {"name": "_time"}, {"name": "host"}, {"name": "source"},
            {"name": "message"}, {"name": "severity"}, {"name": "count"}
        ],
    })

@app.route("/servicesNS/admin/search/search/jobs/export", methods=["POST", "GET"])
def export_search():
    return jsonify({"results": MOCK_EVENTS})

if __name__ == "__main__":
    print("Splunk mock running on port 8089")
    app.run(host="0.0.0.0", port=8089, debug=False)
