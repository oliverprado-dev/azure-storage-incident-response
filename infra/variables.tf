variable "subscription_id" {
  description = "ID da assinatura de laboratório no Azure público."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$", var.subscription_id))
    error_message = "subscription_id deve ser um UUID."
  }
}

variable "name_suffix" {
  description = "Sufixo globalmente único para os recursos. Use 6 a 12 letras minúsculas ou dígitos."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9]{6,12}$", var.name_suffix))
    error_message = "name_suffix deve ter de 6 a 12 letras minúsculas ou dígitos."
  }
}

variable "location" {
  description = "Região com suporte a Azure Functions Flex Consumption, por exemplo westeurope."
  type        = string
  default     = "westeurope"
}

variable "event_subscription_enabled" {
  description = "Conecta o Event Grid à função após a publicação e a indexação de GuardStorage."
  type        = bool
  default     = false
}

variable "remediation_enabled" {
  description = "Concede escrita ARM na conta do laboratório e autoriza o PATCH. false mantém dry-run."
  type        = bool
  default     = false
}
