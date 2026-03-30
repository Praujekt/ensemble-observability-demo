from flask import Flask, jsonify, request, Response
from datetime import datetime, timezone, timedelta
import time
import json

app = Flask(__name__)

FIELDS = [
    {"name": "_time", "groupby_rank": "0"},
    {"name": "_raw"},
    {"name": "host"},
    {"name": "source"},
    {"name": "sourcetype"},
    {"name": "message"},
    {"name": "severity"},
    {"name": "count"},
]


def get_mock_events():
    now = datetime.now(timezone.utc)
    return [
        {"_time": str(int((now - timedelta(minutes=25)).timestamp() * 1000)), "_raw": "DB connection pool exhausted — 0 connections available", "host": "ensemble-prod-01", "source": "checkout", "sourcetype": "checkout", "message": "DB connection pool exhausted — 0 connections available", "severity": "CRITICAL", "count": "847"},
        {"_time": str(int((now - timedelta(minutes=20)).timestamp() * 1000)), "_raw": "Checkout timeout after 8000ms — inventory service unreachable", "host": "ensemble-prod-01", "source": "checkout", "sourcetype": "checkout", "message": "Checkout timeout after 8000ms — inventory service unreachable", "severity": "ERROR", "count": "1203"},
        {"_time": str(int((now - timedelta(minutes=15)).timestamp() * 1000)), "_raw": "inventory_db_pool_available=0 pool exhausted under Black Friday load", "host": "ensemble-prod-02", "source": "inventory", "sourcetype": "inventory", "message": "inventory_db_pool_available=0 pool exhausted under Black Friday load", "severity": "CRITICAL", "count": "2841"},
        {"_time": str(int((now - timedelta(minutes=10)).timestamp() * 1000)), "_raw": "Azure Logic App fraud-check timeout after 5000ms", "host": "ensemble-prod-01", "source": "fraud-check", "sourcetype": "checkout", "message": "Azure Logic App fraud-check timeout after 5000ms", "severity": "WARNING", "count": "412"},
        {"_time": str(int((now - timedelta(minutes=5)).timestamp() * 1000)), "_raw": "payment_declined error rate 24% — exceeds 5% SLO threshold", "host": "ensemble-prod-02", "source": "checkout", "sourcetype": "checkout", "message": "payment_declined error rate 24% — exceeds 5% SLO threshold", "severity": "CRITICAL", "count": "634"},
    ]


def make_results_response():
    events = get_mock_events()
    return jsonify({
        "results": events,
        "highlighted": {},
        "preview": False,
        "init_offset": 0,
        "messages": [],
        "fields": FIELDS,
    })


def make_ndjson_response():
    events = get_mock_events()
    lines = []
    for event in events:
        lines.append(json.dumps({"result": event, "preview": False}))
    lines.append(json.dumps({"lastrow": True}))
    return Response("\n".join(lines), mimetype="application/json")


def make_job_status(sid):
    events = get_mock_events()
    return jsonify({
        "entry": [{
            "name": sid,
            "content": {
                "dispatchState": "DONE",
                "resultCount": len(events),
                "isDone": True,
                "isFailed": False,
                "resultPreviewCount": len(events),
                "doneProgress": 1.0,
                "scanCount": len(events),
                "eventCount": len(events),
                "resultCountRelation": "eq",
            }
        }],
        "messages": []
    })


# ── Server info ───────────────────────────────────────────────────────
@app.route("/services/server/info", methods=["GET"])
def server_info():
    return jsonify({
        "links": {},
        "origin": "https://172.22.8.244:8089/services/server/info",
        "updated": "2026-03-30T00:00:00+00:00",
        "generator": {"build": "ensemble-mock", "version": "9.1.0"},
        "entry": [{
            "name": "server-info",
            "id": "https://172.22.8.244:8089/services/server/info/server-info",
            "updated": "2026-03-30T00:00:00+00:00",
            "links": {},
            "author": "system",
            "acl": {},
            "content": {
                "build": "ensemble-mock",
                "cpu_arch": "x86_64",
                "generator": "splunkd",
                "guid": "ensemble-demo-splunk",
                "isFree": 0,
                "isTrial": 0,
                "licenseState": "OK",
                "mode": "normal",
                "os": "Linux",
                "product_type": "splunk",
                "serverName": "splunk-onprem-ensemble",
                "version": "9.1.0"
            }
        }],
        "paging": {},
        "messages": []
    })


# ── Metadata endpoints ────────────────────────────────────────────────
@app.route("/services/data/indexes", methods=["GET"])
@app.route("/servicesNS/<user>/<app_name>/data/indexes", methods=["GET"])
def get_indexes(user=None, app_name=None):
    return jsonify({
        "entry": [
            {"name": "ensemble", "content": {"totalEventCount": "5", "dataType": "event"}},
            {"name": "main", "content": {"totalEventCount": "0", "dataType": "event"}},
        ],
        "paging": {}, "messages": []
    })


@app.route("/services/saved/sourcetypes", methods=["GET"])
@app.route("/servicesNS/<user>/<app_name>/saved/sourcetypes", methods=["GET"])
def get_sourcetypes(user=None, app_name=None):
    return jsonify({
        "entry": [
            {"name": "checkout", "content": {"description": "Ensemble checkout events"}},
            {"name": "inventory", "content": {"description": "Ensemble inventory events"}},
        ],
        "paging": {}, "messages": []
    })


@app.route("/services/apps/local", methods=["GET"])
@app.route("/servicesNS/<user>/<app_name>/apps/local", methods=["GET"])
def get_apps(user=None, app_name=None):
    return jsonify({
        "entry": [{"name": "search", "content": {"label": "Search", "version": "9.1.0"}}],
        "paging": {}, "messages": []
    })


@app.route("/servicesNS/<user>/<app_name>/search/typeahead", methods=["GET"])
def typeahead(user, app_name):
    return jsonify({"results": []})


@app.route("/servicesNS/<user>/<app_name>/search/fields", methods=["GET"])
def get_fields(user, app_name):
    return jsonify({"entry": [], "paging": {}, "messages": []})


@app.route("/servicesNS/<user>/<app_name>/saved/searches", methods=["GET"])
def get_saved_searches(user, app_name):
    return jsonify({"entry": [], "paging": {}, "messages": []})


# ── Search jobs — non-namespaced ──────────────────────────────────────
@app.route("/services/search/jobs", methods=["POST"])
def create_search_job():
    from urllib.parse import parse_qs
    body = parse_qs(request.data.decode("utf-8"))
    exec_mode = body.get("exec_mode", ["normal"])[0]
    search = body.get("search", [""])[0]
    sid = f"1774911.{int(time.time())}"
    print(f"CREATE JOB - exec_mode={exec_mode} search={search} sid={sid}")

    if exec_mode == "oneshot":
        events = get_mock_events()
        return jsonify({
            "preview": False,
            "init_offset": 0,
            "messages": [],
            "fields": FIELDS,
            "results": events,
            "highlighted": {}
        }), 200

    return jsonify({"sid": sid}), 200


@app.route("/services/search/jobs/<sid>", methods=["GET"])
def get_job_status(sid):
    print(f"JOB STATUS POLLED: {sid}")
    return make_job_status(sid)


@app.route("/services/search/jobs/<sid>/results", methods=["GET"])
def get_results(sid):
    print(f"RESULTS HIT: {sid}")
    return make_results_response()


@app.route("/services/search/jobs/<sid>/results_preview", methods=["GET"])
def get_results_preview(sid):
    print(f"RESULTS PREVIEW HIT: {sid}")
    return make_results_response()


# ── Search jobs — namespaced ──────────────────────────────────────────
@app.route("/servicesNS/<user>/<app_name>/search/jobs", methods=["POST"])
def create_search_job_ns(user, app_name):
    from urllib.parse import parse_qs
    body = parse_qs(request.data.decode("utf-8"))
    exec_mode = body.get("exec_mode", ["normal"])[0]
    search = body.get("search", [""])[0]
    sid = f"1774911.{int(time.time())}"
    print(f"CREATE JOB NS - user={user} app={app_name} exec_mode={exec_mode} search={search} sid={sid}")

    if exec_mode == "oneshot":
        events = get_mock_events()
        return jsonify({
            "preview": False,
            "init_offset": 0,
            "messages": [],
            "fields": FIELDS,
            "results": events,
            "highlighted": {}
        }), 200

    return jsonify({"sid": sid}), 200


@app.route("/servicesNS/<user>/<app_name>/search/jobs/<sid>", methods=["GET"])
def get_job_status_ns(user, app_name, sid):
    print(f"JOB STATUS NS POLLED: user={user} app={app_name} sid={sid}")
    return make_job_status(sid)


@app.route("/servicesNS/<user>/<app_name>/search/jobs/<sid>/results", methods=["GET"])
def get_results_ns(user, app_name, sid):
    print(f"RESULTS NS HIT: user={user} app={app_name} sid={sid}")
    return make_results_response()


@app.route("/servicesNS/<user>/<app_name>/search/jobs/<sid>/results_preview", methods=["GET"])
def get_results_preview_ns(user, app_name, sid):
    print(f"RESULTS PREVIEW NS HIT: user={user} app={app_name} sid={sid}")
    return make_results_response()


# ── Export endpoints ──────────────────────────────────────────────────
@app.route("/servicesNS/<user>/<app_name>/search/jobs/export", methods=["POST", "GET"])
def export_search_ns(user, app_name):
    print(f"EXPORT NS HIT - user={user} app={app_name} form={dict(request.form)}")
    return make_ndjson_response()


@app.route("/servicesNS/admin/search/search/jobs/export", methods=["POST", "GET"])
def export_search_admin():
    print(f"EXPORT ADMIN HIT - form={dict(request.form)}")
    return make_ndjson_response()


@app.route("/services/search/jobs/export", methods=["POST", "GET"])
def export_search():
    print(f"EXPORT HIT - form={dict(request.form)}")
    return make_ndjson_response()


if __name__ == "__main__":
    print("Splunk mock running on port 8089 (HTTPS)")
    app.run(
        host="0.0.0.0",
        port=8089,
        debug=False,
        ssl_context=("/tmp/splunk-cert.pem", "/tmp/splunk-key.pem")
    )