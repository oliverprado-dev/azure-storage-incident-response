resource "azurerm_user_assigned_identity" "guard" {
  name                = "id-${local.lab_name}"
  resource_group_name = azurerm_resource_group.lab.name
  location            = azurerm_resource_group.lab.location
  tags                = local.tags
}

resource "azurerm_role_definition" "storage_read" {
  name              = "${local.lab_name}-storage-read"
  scope             = azurerm_resource_group.lab.id
  assignable_scopes = [azurerm_resource_group.lab.id]
  description       = "Read Azure Storage account settings for the incident response lab."

  permissions {
    actions = ["Microsoft.Storage/storageAccounts/read"]
  }
}

resource "azurerm_role_definition" "storage_write" {
  name              = "${local.lab_name}-storage-write"
  scope             = azurerm_resource_group.lab.id
  assignable_scopes = [azurerm_resource_group.lab.id]
  description       = "Update Azure Storage account settings for the incident response lab."

  permissions {
    actions = ["Microsoft.Storage/storageAccounts/write"]
  }
}

resource "azurerm_role_assignment" "storage_read" {
  scope                            = azurerm_storage_account.lab.id
  role_definition_id               = azurerm_role_definition.storage_read.role_definition_resource_id
  principal_id                     = azurerm_user_assigned_identity.guard.principal_id
  principal_type                   = "ServicePrincipal"
  skip_service_principal_aad_check = true
}

resource "azurerm_role_assignment" "storage_write" {
  count = var.remediation_enabled ? 1 : 0

  scope                            = azurerm_storage_account.lab.id
  role_definition_id               = azurerm_role_definition.storage_write.role_definition_resource_id
  principal_id                     = azurerm_user_assigned_identity.guard.principal_id
  principal_type                   = "ServicePrincipal"
  skip_service_principal_aad_check = true
}

resource "azurerm_role_assignment" "runtime_blob" {
  scope                            = azurerm_storage_account.runtime.id
  role_definition_name             = "Storage Blob Data Owner"
  principal_id                     = azurerm_user_assigned_identity.guard.principal_id
  principal_type                   = "ServicePrincipal"
  skip_service_principal_aad_check = true
}

resource "azurerm_role_assignment" "runtime_table" {
  scope                            = azurerm_storage_account.runtime.id
  role_definition_name             = "Storage Table Data Contributor"
  principal_id                     = azurerm_user_assigned_identity.guard.principal_id
  principal_type                   = "ServicePrincipal"
  skip_service_principal_aad_check = true
}

resource "azurerm_role_assignment" "telemetry" {
  scope                            = azurerm_application_insights.lab.id
  role_definition_name             = "Monitoring Metrics Publisher"
  principal_id                     = azurerm_user_assigned_identity.guard.principal_id
  principal_type                   = "ServicePrincipal"
  skip_service_principal_aad_check = true
}

resource "azurerm_service_plan" "flex" {
  name                = "plan-${local.lab_name}"
  resource_group_name = azurerm_resource_group.lab.name
  location            = azurerm_resource_group.lab.location
  os_type             = "Linux"
  sku_name            = "FC1"
  tags                = local.tags
}

resource "azurerm_function_app_flex_consumption" "guard" {
  name                = "func-${local.lab_name}"
  resource_group_name = azurerm_resource_group.lab.name
  location            = azurerm_resource_group.lab.location
  service_plan_id     = azurerm_service_plan.flex.id

  storage_container_type            = "blobContainer"
  storage_container_endpoint        = "${azurerm_storage_account.runtime.primary_blob_endpoint}${azurerm_storage_container.deployment.name}"
  storage_authentication_type       = "UserAssignedIdentity"
  storage_user_assigned_identity_id = azurerm_user_assigned_identity.guard.id

  runtime_name          = "python"
  runtime_version       = "3.12"
  instance_memory_in_mb = 512

  https_only                                     = true
  public_network_access_enabled                  = true
  ftp_publish_basic_authentication_enabled       = false
  webdeploy_publish_basic_authentication_enabled = false

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.guard.id]
  }

  app_settings = {
    AzureWebJobsStorage__accountName          = azurerm_storage_account.runtime.name
    AzureWebJobsStorage__credential           = "managedidentity"
    AzureWebJobsStorage__clientId             = azurerm_user_assigned_identity.guard.client_id
    APPLICATIONINSIGHTS_AUTHENTICATION_STRING = "ClientId=${azurerm_user_assigned_identity.guard.client_id};Authorization=AAD"
    GUARD_IDENTITY_CLIENT_ID                  = azurerm_user_assigned_identity.guard.client_id
    LAB_STORAGE_ACCOUNT_ID                    = azurerm_storage_account.lab.id
    REMEDIATION_ENABLED                       = tostring(var.remediation_enabled)
  }

  site_config {
    application_insights_connection_string = azurerm_application_insights.lab.connection_string
    minimum_tls_version                    = "1.2"
    scm_minimum_tls_version                = "1.2"
  }

  depends_on = [
    azurerm_role_assignment.runtime_blob,
    azurerm_role_assignment.runtime_table,
    azurerm_role_assignment.storage_read,
    azurerm_role_assignment.storage_write,
    azurerm_role_assignment.telemetry,
  ]

  tags = local.tags
}
