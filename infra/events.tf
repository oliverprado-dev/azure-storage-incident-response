resource "azurerm_eventgrid_system_topic" "arm" {
  name                = "evg-${local.lab_name}"
  resource_group_name = azurerm_resource_group.lab.name
  location            = "Global"
  source_resource_id  = azurerm_resource_group.lab.id
  topic_type          = "Microsoft.Resources.ResourceGroups"
  tags                = local.tags

  identity {
    type = "SystemAssigned"
  }
}

resource "azurerm_role_assignment" "dead_letter" {
  scope                            = azurerm_storage_container.dead_letter.resource_manager_id
  role_definition_name             = "Storage Blob Data Contributor"
  principal_id                     = azurerm_eventgrid_system_topic.arm.identity[0].principal_id
  principal_type                   = "ServicePrincipal"
  skip_service_principal_aad_check = true
}

resource "azurerm_monitor_diagnostic_setting" "eventgrid" {
  name                       = "delivery-failures"
  target_resource_id         = azurerm_eventgrid_system_topic.arm.id
  log_analytics_workspace_id = azurerm_log_analytics_workspace.lab.id

  enabled_log {
    category = "DeliveryFailures"
  }
}

resource "azurerm_eventgrid_system_topic_event_subscription" "guard" {
  count = var.event_subscription_enabled ? 1 : 0

  name                  = "guard-storage"
  system_topic          = azurerm_eventgrid_system_topic.arm.name
  resource_group_name   = azurerm_resource_group.lab.name
  event_delivery_schema = "EventGridSchema"
  included_event_types  = ["Microsoft.Resources.ResourceWriteSuccess"]

  subject_filter {
    subject_begins_with = azurerm_storage_account.lab.id
    case_sensitive      = false
  }

  advanced_filter {
    string_in {
      key    = "data.operationName"
      values = ["Microsoft.Storage/storageAccounts/write"]
    }
    string_in {
      key    = "data.resourceUri"
      values = [azurerm_storage_account.lab.id]
    }
  }

  azure_function_endpoint {
    function_id          = "${azurerm_function_app_flex_consumption.guard.id}/functions/GuardStorage"
    max_events_per_batch = 1
  }

  retry_policy {
    max_delivery_attempts = 10
    event_time_to_live    = 60
  }

  dead_letter_identity {
    type = "SystemAssigned"
  }

  storage_blob_dead_letter_destination {
    storage_account_id          = azurerm_storage_account.runtime.id
    storage_blob_container_name = azurerm_storage_container.dead_letter.name
  }

  depends_on = [azurerm_role_assignment.dead_letter]
}
