variable "slug" {
  description = "Short company identifier, 3 to 20 characters. Becomes the namespace (oce-<slug>), the resource names and the default host name."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,18}[a-z0-9]$", var.slug))
    error_message = "slug must be 3-20 characters: lower case letters, digits and '-', starting with a letter and not ending with '-'."
  }
}

variable "display_name" {
  description = "Human readable company name. Stored as an annotation only."
  type        = string

  validation {
    condition     = length(trimspace(var.display_name)) > 0
    error_message = "display_name must not be empty."
  }
}

variable "project_id" {
  description = "STACKIT project ID (UUID) that owns the company's database and bucket."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", var.project_id))
    error_message = "project_id must be a UUID."
  }
}

variable "mode" {
  description = "\"production\" (no demo data) or \"sandbox\" (demo data seeded, smaller sizes, expiry label)."
  type        = string
  default     = "production"

  validation {
    condition     = contains(["sandbox", "production"], var.mode)
    error_message = "mode must be \"sandbox\" or \"production\"."
  }
}

variable "sandbox_days" {
  description = "Sandbox lifetime in days. Only written as the oce/expires label, nothing is deleted automatically."
  type        = number
  default     = 30

  validation {
    condition     = var.sandbox_days >= 1 && var.sandbox_days <= 365 && floor(var.sandbox_days) == var.sandbox_days
    error_message = "sandbox_days must be a whole number between 1 and 365."
  }
}

variable "image_tag" {
  description = "Version of the OpenConstructionERP image, for example \"20.5.1\". Must be an explicit version, \"latest\" is rejected so upgrades are deliberate."
  type        = string

  validation {
    condition     = var.image_tag != "latest" && can(regex("^v?[0-9]+\\.[0-9]+(\\.[0-9]+)?([-.][0-9A-Za-z.]+)?$", var.image_tag))
    error_message = "image_tag must be a version such as \"20.5.1\" or \"20.5\"; \"latest\" is not allowed."
  }
}

variable "image_repository" {
  description = "Container image repository."
  type        = string
  default     = "ghcr.io/datadrivenconstruction/openconstructionerp"
}

# ── Networking and DNS ──────────────────────────────────────────────────────

variable "base_domain" {
  description = "Domain under which the company is published. The host name is <slug>.<base_domain> unless custom_hostname is set."
  type        = string

  validation {
    condition     = can(regex("^([a-z0-9]([-a-z0-9]*[a-z0-9])?\\.)+[a-z]{2,}$", var.base_domain))
    error_message = "base_domain must be a lower case domain name such as \"erp.example.com\"."
  }
}

variable "custom_hostname" {
  description = "Full host name that replaces <slug>.<base_domain>, for example \"erp.customer.com\". Its DNS record must then be created by the customer unless it lies inside the zone."
  type        = string
  default     = null

  validation {
    condition     = var.custom_hostname == null || can(regex("^([a-z0-9]([-a-z0-9]*[a-z0-9])?\\.)+[a-z]{2,}$", var.custom_hostname))
    error_message = "custom_hostname must be a lower case fully qualified host name."
  }
}

variable "zone_id" {
  description = "STACKIT DNS zone ID in which the A record is created. Null skips the record (manage DNS yourself)."
  type        = string
  default     = null
}

variable "create_dns_record" {
  description = "Create the A record in zone_id. Set false when custom_hostname lies outside the zone."
  type        = bool
  default     = true
}

variable "ingress_ip" {
  description = "Public address of the ingress controller (platform output ingress_ip). Target of the A record."
  type        = string
  default     = null
}

variable "ingress_namespace" {
  description = "Namespace of the ingress controller. The NetworkPolicy admits traffic from it."
  type        = string
  default     = "ingress-nginx"
}

variable "ingress_class_name" {
  description = "IngressClass used for the company Ingress."
  type        = string
  default     = "nginx"
}

variable "cluster_issuer_name" {
  description = "cert-manager ClusterIssuer that signs the TLS certificate (platform output cluster_issuer_name)."
  type        = string
  default     = "letsencrypt"
}

variable "egress_extra_cidrs" {
  description = "Private CIDRs the pod may reach in addition to the public internet (for example a private PostgreSQL address). Private ranges are otherwise blocked by the NetworkPolicy."
  type        = list(string)
  default     = []
}

variable "trusted_proxies" {
  description = "Comma separated CIDRs whose X-Forwarded-For header the app believes. Must contain the ingress controller pod network."
  type        = string
  default     = "127.0.0.0/8,10.0.0.0/8,100.64.0.0/10,172.16.0.0/12,192.168.0.0/16"
}

# ── Database ────────────────────────────────────────────────────────────────

variable "postgres_flavor_id" {
  description = "STACKIT PostgreSQL Flex flavor ID, for example from `stackit postgresflex flavor list`. Flavor IDs depend on region and account, so there is no default."
  type        = string
}

variable "postgres_version" {
  description = "PostgreSQL major version."
  type        = string
  default     = "17"
}

variable "postgres_storage_class" {
  description = "PostgreSQL Flex storage class."
  type        = string
  default     = "premium-perf2-stackit"
}

variable "postgres_storage_gb" {
  description = "PostgreSQL storage size in GB. Null selects the default of the chosen mode."
  type        = number
  default     = null
}

variable "postgres_allowed_cidrs" {
  description = "CIDRs allowed to connect to the database. Pass the platform output egress_address_ranges so only the cluster can connect."
  type        = list(string)

  validation {
    condition     = length(var.postgres_allowed_cidrs) > 0 && alltrue([for c in var.postgres_allowed_cidrs : can(cidrhost(c, 0))])
    error_message = "postgres_allowed_cidrs must contain at least one valid CIDR."
  }
}

variable "database_ssl" {
  description = "Require TLS on the database connection."
  type        = bool
  default     = true
}

variable "backup_schedule" {
  description = "Database backup schedule as cron expression (UTC)."
  type        = string
  default     = "0 2 * * *"
}

variable "retention_days" {
  description = "Days database backups are kept (32 to 90). Null selects the default of the chosen mode."
  type        = number
  default     = null

  validation {
    condition     = var.retention_days == null ? true : (var.retention_days >= 32 && var.retention_days <= 90 && floor(var.retention_days) == var.retention_days)
    error_message = "retention_days must be a whole number between 32 and 90."
  }
}

# ── Application sizing ──────────────────────────────────────────────────────

variable "data_volume_gb" {
  description = "Size of the /data volume in GB. Null selects the default of the chosen mode."
  type        = number
  default     = null
}

variable "storage_class" {
  description = "Kubernetes StorageClass of the /data volume. Null uses the cluster default."
  type        = string
  default     = null
}

variable "cpu_request" {
  description = "CPU request of the app container."
  type        = string
  default     = "500m"
}

variable "memory_request" {
  description = "Memory request of the app container."
  type        = string
  default     = "1Gi"
}

variable "memory_limit" {
  description = "Memory limit of the app container. Null selects the default of the chosen mode."
  type        = string
  default     = null
}

variable "run_as_uid" {
  description = "Numeric user and group ID the container runs as. Kubernetes cannot verify a user name, so the numeric ID of the image user `oe` is needed."
  type        = number
  default     = 999
}

# ── Application settings ────────────────────────────────────────────────────

variable "registration_mode" {
  description = "Who may register: open, email-verify, admin-approve or closed. The first registered user always becomes administrator."
  type        = string
  default     = "admin-approve"

  validation {
    condition     = contains(["open", "email-verify", "admin-approve", "closed"], var.registration_mode)
    error_message = "registration_mode must be open, email-verify, admin-approve or closed."
  }
}

variable "log_level" {
  description = "Application log level."
  type        = string
  default     = "INFO"

  validation {
    condition     = contains(["DEBUG", "INFO", "WARNING", "ERROR"], var.log_level)
    error_message = "log_level must be DEBUG, INFO, WARNING or ERROR."
  }
}

variable "smtp" {
  description = "Outgoing mail settings. Null keeps the console mail backend (no mail is sent). The password goes in smtp_password."
  type = object({
    host = string
    port = optional(number, 587)
    user = optional(string, "")
    from = string
    tls  = optional(bool, true)
  })
  default = null
}

variable "smtp_password" {
  description = "SMTP password. Stored in the company Kubernetes Secret."
  type        = string
  default     = null
  sensitive   = true
}

variable "enable_model_serving" {
  description = "Create a STACKIT AI Model Serving token and store it in the company Secret. Prepared only: the application does not consume it yet."
  type        = bool
  default     = false
}

variable "model_serving_base_url" {
  description = "OpenAI compatible base URL of STACKIT AI Model Serving."
  type        = string
  default     = "https://api.openai-compat.model-serving.eu01.onstackit.cloud/v1"
}

variable "object_storage_endpoint" {
  description = "S3 endpoint of STACKIT Object Storage."
  type        = string
  default     = "https://object.storage.eu01.onstackit.cloud"
}

variable "object_storage_region" {
  description = "S3 region of STACKIT Object Storage."
  type        = string
  default     = "eu01"
}

variable "labels" {
  description = "Extra labels added to every Kubernetes object of the company."
  type        = map(string)
  default     = {}
}
