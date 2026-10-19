variable "project_id" {
  description = "STACKIT project ID (UUID)."
  type        = string
}

variable "service_account_key_path" {
  description = "Path to the STACKIT service account key (JSON). Null reads STACKIT_SERVICE_ACCOUNT_KEY_PATH from the environment."
  type        = string
  default     = null
}

variable "cluster_name" {
  description = "SKE cluster name (at most 11 characters)."
  type        = string
  default     = "oce"
}

variable "letsencrypt_email" {
  description = "Contact address for Let's Encrypt."
  type        = string
}

variable "base_domain" {
  description = "Domain under which companies are published (<slug>.<base_domain>)."
  type        = string
}

variable "dns_zone_id" {
  description = "ID of an existing STACKIT DNS zone for base_domain. Leave null and set create_dns_zone to create one."
  type        = string
  default     = null
}

variable "create_dns_zone" {
  description = "Create a STACKIT DNS zone named base_domain. Delegate the domain to its name servers afterwards."
  type        = bool
  default     = false
}

variable "postgres_flavor_id" {
  description = "PostgreSQL Flex flavor ID (see `stackit postgresflex flavor list`)."
  type        = string
}

variable "image_tag" {
  description = "OpenConstructionERP version to run, for example \"20.5.1\"."
  type        = string
}

variable "api_allowed_cidrs" {
  description = "CIDRs allowed to reach the Kubernetes API."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "enable_observability" {
  description = "Create an Observability instance and wire it to the cluster."
  type        = bool
  default     = false
}

variable "companies" {
  description = "One entry per company; the key is the slug."
  type = map(object({
    display_name         = string
    mode                 = optional(string, "production")
    custom_hostname      = optional(string)
    create_dns_record    = optional(bool, true)
    sandbox_days         = optional(number, 30)
    postgres_storage_gb  = optional(number)
    data_volume_gb       = optional(number)
    retention_days       = optional(number)
    enable_model_serving = optional(bool, false)
    registration_mode    = optional(string, "admin-approve")
  }))
}
