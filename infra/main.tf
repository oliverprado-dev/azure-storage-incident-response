locals {
  lab_name = "asir-${var.name_suffix}"
  tags = {
    project     = "azure-storage-incident-response"
    environment = "lab"
  }
}

resource "azurerm_resource_group" "lab" {
  name     = "rg-${local.lab_name}"
  location = var.location
  tags     = local.tags
}

# No service needs to bypass the isolated lab data plane.
# trivy:ignore:AZU-0010
resource "azurerm_storage_account" "lab" {
  name                            = "asirlab${var.name_suffix}"
  resource_group_name             = azurerm_resource_group.lab.name
  location                        = azurerm_resource_group.lab.location
  account_kind                    = "StorageV2"
  account_tier                    = "Standard"
  account_replication_type        = "LRS"
  allow_nested_items_to_be_public = false
  public_network_access_enabled   = false
  shared_access_key_enabled       = false
  https_traffic_only_enabled      = true
  min_tls_version                 = "TLS1_2"
  tags                            = local.tags

  network_rules {
    default_action = "Deny"
    bypass         = ["None"]
  }
}

resource "azurerm_storage_container" "lab" {
  name                  = "private-lab"
  storage_account_id    = azurerm_storage_account.lab.id
  container_access_type = "private"
}

# The Flex host, One Deploy and Event Grid dead-lettering use authenticated endpoints.
# The lab omits VNet integration. Private containers, Entra ID and scoped RBAC gate access.
# trivy:ignore:AZU-0012
resource "azurerm_storage_account" "runtime" {
  name                            = "asirhost${var.name_suffix}"
  resource_group_name             = azurerm_resource_group.lab.name
  location                        = azurerm_resource_group.lab.location
  account_kind                    = "StorageV2"
  account_tier                    = "Standard"
  account_replication_type        = "LRS"
  allow_nested_items_to_be_public = false
  public_network_access_enabled   = true
  shared_access_key_enabled       = false
  https_traffic_only_enabled      = true
  min_tls_version                 = "TLS1_2"
  tags                            = local.tags
}

resource "azurerm_storage_container" "deployment" {
  name                  = "function-deploy"
  storage_account_id    = azurerm_storage_account.runtime.id
  container_access_type = "private"
}

resource "azurerm_storage_container" "dead_letter" {
  name                  = "eventgrid-deadletter"
  storage_account_id    = azurerm_storage_account.runtime.id
  container_access_type = "private"
}
