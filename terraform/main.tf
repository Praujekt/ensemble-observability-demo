terraform {
  required_version = ">= 1.3"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.0"
    }
    azuread = {
      source  = "hashicorp/azuread"
      version = "~> 2.0"
    }
  }
}

provider "azurerm" {
  features {}
}

provider "azuread" {}

# ── Variables ─────────────────────────────────────────────────────────
variable "location" {
  description = "Azure region"
  default     = "East US"
}

variable "resource_group_name" {
  description = "Resource group for all demo resources"
  default     = "ensemble-demo-rg"
}

variable "environment" {
  description = "Environment tag"
  default     = "demo"
}

# ── Resource Group ────────────────────────────────────────────────────
resource "azurerm_resource_group" "ensemble" {
  name     = var.resource_group_name
  location = var.location

  tags = {
    environment = var.environment
    project     = "ensemble-observability-demo"
    managed_by  = "terraform"
  }
}

# ── Service Principal for Grafana Cloud ───────────────────────────────
data "azuread_client_config" "current" {}

resource "azuread_application" "grafana_reader" {
  display_name = "grafana-cloud-reader"
}

resource "azuread_service_principal" "grafana_reader" {
  client_id = azuread_application.grafana_reader.client_id
}

resource "azuread_service_principal_password" "grafana_reader" {
  service_principal_id = azuread_service_principal.grafana_reader.id
  end_date             = "2027-01-01T00:00:00Z"
}

data "azurerm_subscription" "current" {}

resource "azurerm_role_assignment" "grafana_monitoring_reader" {
  scope                = data.azurerm_subscription.current.id
  role_definition_name = "Monitoring Reader"
  principal_id         = azuread_service_principal.grafana_reader.object_id
}

resource "azurerm_role_assignment" "grafana_reader" {
  scope                = data.azurerm_subscription.current.id
  role_definition_name = "Reader"
  principal_id         = azuread_service_principal.grafana_reader.object_id
}

# ── Log Analytics Workspace ───────────────────────────────────────────
resource "azurerm_log_analytics_workspace" "ensemble" {
  name                = "ensemble-demo-logs"
  location            = azurerm_resource_group.ensemble.location
  resource_group_name = azurerm_resource_group.ensemble.name
  sku                 = "PerGB2018"
  retention_in_days   = 30

  tags = {
    environment = var.environment
    project     = "ensemble-observability-demo"
  }
}

# ── Application Insights ──────────────────────────────────────────────
resource "azurerm_application_insights" "ensemble" {
  name                = "ensemble-demo-insights"
  location            = azurerm_resource_group.ensemble.location
  resource_group_name = azurerm_resource_group.ensemble.name
  workspace_id        = azurerm_log_analytics_workspace.ensemble.id
  application_type    = "web"

  tags = {
    environment = var.environment
    project     = "ensemble-observability-demo"
  }
}

# ── Storage Account ───────────────────────────────────────────────────
resource "azurerm_storage_account" "ensemble" {
  name                     = "ensembledemostorage"
  resource_group_name      = azurerm_resource_group.ensemble.name
  location                 = azurerm_resource_group.ensemble.location
  account_tier             = "Standard"
  account_replication_type = "LRS"

  tags = {
    environment = var.environment
  }
}

# ── Logic App: Fraud Check ────────────────────────────────────────────
resource "azurerm_logic_app_workflow" "fraud_check" {
  name                = "ensemble-fraud-check"
  location            = azurerm_resource_group.ensemble.location
  resource_group_name = azurerm_resource_group.ensemble.name

  tags = {
    environment = var.environment
    service     = "fraud-check"
  }
}

resource "azurerm_logic_app_trigger_http_request" "fraud_check" {
  name         = "manual"
  logic_app_id = azurerm_logic_app_workflow.fraud_check.id

  schema = jsonencode({
    type = "object"
    properties = {
      order_id = { type = "string" }
      items    = { type = "array" }
    }
  })
}

resource "azurerm_logic_app_action_http" "fraud_check_response" {
  name         = "Response"
  logic_app_id = azurerm_logic_app_workflow.fraud_check.id
  method       = "GET"
  uri          = "https://httpbin.org/status/202"
  depends_on   = [azurerm_logic_app_trigger_http_request.fraud_check]
}

resource "azurerm_monitor_diagnostic_setting" "fraud_check" {
  name                       = "ensemble-fraud-check-diag"
  target_resource_id         = azurerm_logic_app_workflow.fraud_check.id
  log_analytics_workspace_id = azurerm_log_analytics_workspace.ensemble.id

  enabled_log {
    category = "WorkflowRuntime"
  }

  metric {
    category = "AllMetrics"
    enabled  = true
  }
}

# ── Logic App: Loyalty Points ─────────────────────────────────────────
resource "azurerm_logic_app_workflow" "loyalty_points" {
  name                = "ensemble-loyalty-points"
  location            = azurerm_resource_group.ensemble.location
  resource_group_name = azurerm_resource_group.ensemble.name

  tags = {
    environment = var.environment
    service     = "loyalty-points"
  }
}

resource "azurerm_logic_app_trigger_http_request" "loyalty_points" {
  name         = "manual"
  logic_app_id = azurerm_logic_app_workflow.loyalty_points.id

  schema = jsonencode({
    type = "object"
    properties = {
      order_id    = { type = "string" }
      total_cents = { type = "integer" }
    }
  })
}

resource "azurerm_logic_app_action_http" "loyalty_points_response" {
  name         = "Response"
  logic_app_id = azurerm_logic_app_workflow.loyalty_points.id
  method       = "GET"
  uri          = "https://httpbin.org/status/202"
  depends_on   = [azurerm_logic_app_trigger_http_request.loyalty_points]
}

resource "azurerm_monitor_diagnostic_setting" "loyalty_points" {
  name                       = "ensemble-loyalty-points-diag"
  target_resource_id         = azurerm_logic_app_workflow.loyalty_points.id
  log_analytics_workspace_id = azurerm_log_analytics_workspace.ensemble.id

  enabled_log {
    category = "WorkflowRuntime"
  }

  metric {
    category = "AllMetrics"
    enabled  = true
  }
}

# ── Logic App: Order Notification ─────────────────────────────────────
resource "azurerm_logic_app_workflow" "order_notification" {
  name                = "ensemble-order-notification"
  location            = azurerm_resource_group.ensemble.location
  resource_group_name = azurerm_resource_group.ensemble.name

  tags = {
    environment = var.environment
    service     = "order-notification"
  }
}

resource "azurerm_logic_app_trigger_http_request" "order_notification" {
  name         = "manual"
  logic_app_id = azurerm_logic_app_workflow.order_notification.id

  schema = jsonencode({
    type = "object"
    properties = {
      order_id = { type = "string" }
      total    = { type = "number" }
    }
  })
}

resource "azurerm_logic_app_action_http" "order_notification_response" {
  name         = "Response"
  logic_app_id = azurerm_logic_app_workflow.order_notification.id
  method       = "GET"
  uri          = "https://httpbin.org/status/202"
  depends_on   = [azurerm_logic_app_trigger_http_request.order_notification]
}

resource "azurerm_monitor_diagnostic_setting" "order_notification" {
  name                       = "ensemble-order-notification-diag"
  target_resource_id         = azurerm_logic_app_workflow.order_notification.id
  log_analytics_workspace_id = azurerm_log_analytics_workspace.ensemble.id

  enabled_log {
    category = "WorkflowRuntime"
  }

  metric {
    category = "AllMetrics"
    enabled  = true
  }
}