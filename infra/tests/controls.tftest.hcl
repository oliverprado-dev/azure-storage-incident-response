mock_provider "azurerm" {}

variables {
  subscription_id = "00000000-0000-0000-0000-000000000001"
  name_suffix     = "demo1234"
}

run "defaults" {
  command = plan

  assert {
    condition = (
      !azurerm_storage_account.lab.allow_nested_items_to_be_public &&
      !azurerm_storage_account.lab.public_network_access_enabled &&
      !azurerm_storage_account.lab.shared_access_key_enabled &&
      azurerm_storage_container.lab.container_access_type == "private" &&
      azurerm_storage_account.lab.name != azurerm_storage_account.runtime.name
    )
    error_message = "A conta monitorada deve ter acesso anônimo e rede pública bloqueados e ficar separada do host."
  }

  assert {
    condition = (
      length(azurerm_role_assignment.storage_write) == 0 &&
      length(azurerm_eventgrid_system_topic_event_subscription.guard) == 0 &&
      azurerm_function_app_flex_consumption.guard.app_settings.REMEDIATION_ENABLED == "false"
    )
    error_message = "A instalação inicial deve provisionar dry-run sem escrita ARM e sem destino de eventos."
  }
}

run "explicit_enforcement" {
  command = plan

  variables {
    event_subscription_enabled = true
    remediation_enabled        = true
  }

  assert {
    condition = (
      length(azurerm_role_assignment.storage_write) == 1 &&
      toset(azurerm_role_definition.storage_write.permissions[0].actions) == toset(["Microsoft.Storage/storageAccounts/write"]) &&
      azurerm_function_app_flex_consumption.guard.app_settings.REMEDIATION_ENABLED == "true"
    )
    error_message = "A ativação deve conceder somente a ação write na conta do laboratório e habilitar o PATCH."
  }

  assert {
    condition = (
      azurerm_eventgrid_system_topic_event_subscription.guard[0].event_delivery_schema == "EventGridSchema" &&
      toset(azurerm_eventgrid_system_topic_event_subscription.guard[0].included_event_types) == toset(["Microsoft.Resources.ResourceWriteSuccess"]) &&
      toset([
        for filter in azurerm_eventgrid_system_topic_event_subscription.guard[0].advanced_filter[0].string_in : filter.key
      ]) == toset(["data.operationName", "data.resourceUri"])
    )
    error_message = "A inscrição deve usar EventGridSchema e filtrar o sucesso, a operação e a conta."
  }
}
