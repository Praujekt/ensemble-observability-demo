terraform {
  required_version = ">= 1.3"
  required_providers {
    grafana = {
      source  = "grafana/grafana"
      version = "~> 3.0"
    }
  }
}

variable "grafana_url" {
  description = "Your Grafana Cloud stack URL"
}

variable "grafana_api_key" {
  description = "Grafana Cloud API key"
  sensitive   = true
}

provider "grafana" {
  url  = var.grafana_url
  auth = var.grafana_api_key
}

# ── Folder ────────────────────────────────────────────────────────────
resource "grafana_folder" "ensemble_slos" {
  title = "Ensemble SLOs"
}

# ── Contact Point ─────────────────────────────────────────────────────
resource "grafana_contact_point" "ensemble_oncall" {
  name = "ensemble-oncall"

  email {
    addresses               = ["oncall@zachsemble.com"]
    subject                 = "{{ template \"default.title\" . }}"
    single_email            = false
    disable_resolve_message = false
  }
}

# ── Notification Policy ───────────────────────────────────────────────
resource "grafana_notification_policy" "ensemble" {
  group_by      = ["alertname", "service"]
  contact_point = grafana_contact_point.ensemble_oncall.name

  group_wait      = "30s"
  group_interval  = "5m"
  repeat_interval = "4h"

  policy {
    matcher {
      label = "severity"
      match = "="
      value = "critical"
    }
    contact_point   = grafana_contact_point.ensemble_oncall.name
    group_by        = ["alertname", "service"]
    group_wait      = "0s"
    group_interval  = "1m"
    repeat_interval = "1h"
  }
}

# ── Alert Rules ───────────────────────────────────────────────────────
resource "grafana_rule_group" "ensemble_checkout" {
  name             = "checkout-slo"
  folder_uid       = grafana_folder.ensemble_slos.uid
  interval_seconds = 60

  # Rule 1: p95 Checkout Latency
  rule {
    name      = "Ensemble Checkout — p95 Latency Breach"
    condition = "C"

    data {
      ref_id = "B"
      relative_time_range {
        from = 300
        to   = 0
      }
      datasource_uid = "grafanacloud-prom"
      model = jsonencode({
        expr         = "histogram_quantile(0.95, sum(rate(ensemble_checkout_duration_seconds_bucket[5m])) by (le))"
        instant      = true
        intervalMs   = 1000
        maxDataPoints = 43200
        refId        = "B"
      })
    }

    data {
      ref_id = "C"
      relative_time_range {
        from = 300
        to   = 0
      }
      datasource_uid = "__expr__"
      model = jsonencode({
        type       = "threshold"
        refId      = "C"
        expression = "B"
        conditions = [{
          evaluator = { params = [2.5], type = "gt" }
          operator  = { type = "and" }
          query     = { params = ["C"] }
          reducer   = { params = [], type = "last" }
          type      = "query"
        }]
      })
    }

    for            = "2m"
    no_data_state  = "NoData"
    exec_err_state = "Error"

    labels = {
      severity = "critical"
      service  = "ensemble-checkout"
    }

    annotations = {
      summary     = "Checkout p95 latency SLO breach"
      description = "The Zachsemble checkout p95 latency has exceeded the 500ms SLO target. Investigate inventory service response times and database connection pool saturation immediately."
    }
  }

  # Rule 2: Checkout Error Rate
  rule {
    name      = "Ensemble Checkout — High Error Rate"
    condition = "C"

    data {
      ref_id = "B"
      relative_time_range {
        from = 300
        to   = 0
      }
      datasource_uid = "grafanacloud-prom"
      model = jsonencode({
        expr         = "sum(rate(ensemble_checkout_errors_total[5m])) / sum(rate(ensemble_http_requests_total{endpoint=\"/api/checkout\"}[5m]))"
        instant      = true
        intervalMs   = 1000
        maxDataPoints = 43200
        refId        = "B"
      })
    }

    data {
      ref_id = "C"
      relative_time_range {
        from = 300
        to   = 0
      }
      datasource_uid = "__expr__"
      model = jsonencode({
        type       = "threshold"
        refId      = "C"
        expression = "B"
        conditions = [{
          evaluator = { params = [0.05], type = "gt" }
          operator  = { type = "and" }
          query     = { params = ["C"] }
          reducer   = { params = [], type = "last" }
          type      = "query"
        }]
      })
    }

    for            = "2m"
    no_data_state  = "NoData"
    exec_err_state = "Error"

    labels = {
      severity = "critical"
      service  = "ensemble-checkout"
    }

    annotations = {
      summary     = "Checkout error rate exceeds 5% SLO"
      description = "Checkout error rate has exceeded 5% over the last 5 minutes. Customers are actively failing to complete purchases. Check inventory service health and database connection pool availability."
    }
  }

  # Rule 3: Logic App Failure Rate
  rule {
    name      = "Ensemble Logic Apps — High Failure Rate"
    condition = "C"

    data {
      ref_id = "B"
      relative_time_range {
        from = 300
        to   = 0
      }
      datasource_uid = "grafanacloud-prom"
      model = jsonencode({
        expr         = "sum(rate(ensemble_logic_app_failures_total[5m])) by (logic_app)"
        instant      = true
        intervalMs   = 1000
        maxDataPoints = 43200
        refId        = "B"
      })
    }

    data {
      ref_id = "C"
      relative_time_range {
        from = 300
        to   = 0
      }
      datasource_uid = "__expr__"
      model = jsonencode({
        type       = "threshold"
        refId      = "C"
        expression = "B"
        conditions = [{
          evaluator = { params = [0.1], type = "gt" }
          operator  = { type = "and" }
          query     = { params = ["C"] }
          reducer   = { params = [], type = "last" }
          type      = "query"
        }]
      })
    }

    for            = "1m"
    no_data_state  = "NoData"
    exec_err_state = "Error"

    labels = {
      severity = "warning"
      service  = "ensemble-logic-apps"
    }

    annotations = {
      summary     = "Logic App {{ $labels.logic_app }} failure rate elevated"
      description = "Azure Logic App {{ $labels.logic_app }} is failing at an elevated rate. Check Azure Monitor for detailed execution history."
    }
  }

  # Rule 4: Inventory DB Pool Saturation
  rule {
    name      = "Ensemble Inventory — Database Pool Saturation"
    condition = "C"

    data {
      ref_id = "B"
      relative_time_range {
        from = 300
        to   = 0
      }
      datasource_uid = "grafanacloud-prom"
      model = jsonencode({
        expr         = "1 - (inventory_db_pool_available / 10)"
        instant      = true
        intervalMs   = 1000
        maxDataPoints = 43200
        refId        = "B"
      })
    }

    data {
      ref_id = "C"
      relative_time_range {
        from = 300
        to   = 0
      }
      datasource_uid = "__expr__"
      model = jsonencode({
        type       = "threshold"
        refId      = "C"
        expression = "B"
        conditions = [{
          evaluator = { params = [0.8], type = "gt" }
          operator  = { type = "and" }
          query     = { params = ["C"] }
          reducer   = { params = [], type = "last" }
          type      = "query"
        }]
      })
    }

    for            = "1m"
    no_data_state  = "NoData"
    exec_err_state = "Error"

    labels = {
      severity = "critical"
      service  = "ensemble-inventory"
    }

    annotations = {
      summary     = "Inventory database connection pool over 80% saturated"
      description = "The inventory service database connection pool is critically saturated. This is the direct cause of the Black Friday outage pattern. Scale the inventory service immediately."
    }
  }

  # Rule 5: Active Users Surge
  rule {
    name      = "Ensemble — Black Friday Load Surge Detected"
    condition = "C"

    data {
      ref_id = "B"
      relative_time_range {
        from = 300
        to   = 0
      }
      datasource_uid = "grafanacloud-prom"
      model = jsonencode({
        expr         = "ensemble_active_users"
        instant      = true
        intervalMs   = 1000
        maxDataPoints = 43200
        refId        = "B"
      })
    }

    data {
      ref_id = "C"
      relative_time_range {
        from = 300
        to   = 0
      }
      datasource_uid = "__expr__"
      model = jsonencode({
        type       = "threshold"
        refId      = "C"
        expression = "B"
        conditions = [{
          evaluator = { params = [500], type = "gt" }
          operator  = { type = "and" }
          query     = { params = ["C"] }
          reducer   = { params = [], type = "last" }
          type      = "query"
        }]
      })
    }

    for            = "3m"
    no_data_state  = "NoData"
    exec_err_state = "Error"

    labels = {
      severity = "warning"
      service  = "ensemble-storefront"
    }

    annotations = {
      summary     = "Active user count {{ $value }} — potential load surge"
      description = "Active user count has exceeded 500 for 3 or more minutes. Verify Azure resource scaling and inventory service capacity before load increases further."
    }
  }
}