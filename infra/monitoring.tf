resource "azurerm_log_analytics_workspace" "lab" {
  name                = "log-${local.lab_name}"
  resource_group_name = azurerm_resource_group.lab.name
  location            = azurerm_resource_group.lab.location
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = local.tags
}

resource "azurerm_application_insights" "lab" {
  name                          = "appi-${local.lab_name}"
  resource_group_name           = azurerm_resource_group.lab.name
  location                      = azurerm_resource_group.lab.location
  workspace_id                  = azurerm_log_analytics_workspace.lab.id
  application_type              = "web"
  local_authentication_disabled = true
  tags                          = local.tags
}
