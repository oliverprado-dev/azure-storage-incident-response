output "resource_group_name" {
  value       = azurerm_resource_group.lab.name
  description = "Grupo de recursos dedicado ao laboratório."
}

output "lab_storage_account_id" {
  value       = azurerm_storage_account.lab.id
  description = "Único ID ARM autorizado pela função."
}

output "lab_container_id" {
  value       = azurerm_storage_container.lab.resource_manager_id
  description = "ID ARM do contêiner privado para verificação pelo operador."
}

output "runtime_storage_account_name" {
  value       = azurerm_storage_account.runtime.name
  description = "Conta de armazenamento do host, dos pacotes e de dead-letter."
}

output "function_app_name" {
  value       = azurerm_function_app_flex_consumption.guard.name
  description = "Nome da Function App Flex Consumption."
}

output "function_principal_id" {
  value       = azurerm_user_assigned_identity.guard.principal_id
  description = "Object ID da identidade da função para investigar RBAC e Activity Log."
}

output "eventgrid_system_topic_name" {
  value       = azurerm_eventgrid_system_topic.arm.name
  description = "Nome do tópico de sistema da fonte ARM."
}

output "log_analytics_workspace_id" {
  value       = azurerm_log_analytics_workspace.lab.workspace_id
  description = "Workspace (customer ID) para consultas KQL com a CLI."
}
