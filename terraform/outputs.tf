output "grafana_tenant_id" {
  description = "Paste into Grafana Cloud Azure Monitor datasource"
  value       = data.azuread_client_config.current.tenant_id
}

output "grafana_client_id" {
  description = "Paste into Grafana Cloud Azure Monitor datasource"
  value       = azuread_application.grafana_reader.client_id
}

output "grafana_client_secret" {
  description = "Paste into Grafana Cloud Azure Monitor datasource"
  value       = azuread_service_principal_password.grafana_reader.value
  sensitive   = true
}

output "subscription_id" {
  description = "Azure Subscription ID"
  value       = data.azurerm_subscription.current.subscription_id
}

output "fraud_check_url" {
  description = "Use with chaos-control.sh wire-azure as FRAUD_URL"
  value       = azurerm_logic_app_trigger_http_request.fraud_check.callback_url
  sensitive   = true
}

output "loyalty_points_url" {
  description = "Use with chaos-control.sh wire-azure as LOYALTY_URL"
  value       = azurerm_logic_app_trigger_http_request.loyalty_points.callback_url
  sensitive   = true
}

output "order_notification_url" {
  description = "Use with chaos-control.sh wire-azure as NOTIFY_URL"
  value       = azurerm_logic_app_trigger_http_request.order_notification.callback_url
  sensitive   = true
}

output "app_insights_instrumentation_key" {
  value     = azurerm_application_insights.ensemble.instrumentation_key
  sensitive = true
}

output "resource_group_name" {
  value = azurerm_resource_group.ensemble.name
}

output "function_app_name" {
  value = azurerm_linux_function_app.ensemble.name
}