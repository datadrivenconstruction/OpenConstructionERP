variable "project_id" {
  description = "STACKIT project ID (UUID) that owns the cluster."
  type        = string
}

variable "cluster_name" {
  description = "SKE cluster name. Lower case letters, digits and hyphens, at most 11 characters (SKE limit)."
  type        = string
  default     = "oce"

  validation {
    condition     = can(regex("^[a-z]([-a-z0-9]{0,9}[a-z0-9])?$", var.cluster_name))
    error_message = "cluster_name must start with a letter, use only a-z, 0-9 and '-', and be at most 11 characters."
  }
}

variable "kubernetes_version_min" {
  description = "Minimum Kubernetes version for the cluster, for example \"1.31\". Null lets STACKIT choose its default."
  type        = string
  default     = null
}

variable "node_pools" {
  description = "Worker node pools. Each company requests about 1 GiB memory and 0.5 CPU, so one 4 vCPU / 8 GiB node holds a few companies."
  type = list(object({
    name               = string
    machine_type       = string
    minimum            = number
    maximum            = number
    availability_zones = list(string)
    volume_size        = optional(number, 50)
    os_version_min     = optional(string)
  }))
  default = [
    {
      name               = "default"
      machine_type       = "c1.4"
      minimum            = 2
      maximum            = 4
      availability_zones = ["eu01-1"]
    }
  ]

  validation {
    condition     = length(var.node_pools) > 0 && alltrue([for p in var.node_pools : p.minimum >= 1 && p.maximum >= p.minimum])
    error_message = "Provide at least one node pool, each with minimum >= 1 and maximum >= minimum."
  }
}

variable "allowed_cidrs" {
  description = "CIDRs allowed to reach the Kubernetes API (SKE ACL extension). Restrict this to your office or CI ranges in production."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "maintenance_start" {
  description = "Start of the daily maintenance window (UTC, HH:MM:SSZ)."
  type        = string
  default     = "01:00:00Z"
}

variable "maintenance_end" {
  description = "End of the daily maintenance window (UTC, HH:MM:SSZ)."
  type        = string
  default     = "03:00:00Z"
}

variable "kubeconfig_expiration_seconds" {
  description = "Lifetime of the generated kubeconfig. It is renewed on apply once expired."
  type        = number
  default     = 3600
}

variable "create_dns_zone" {
  description = "Create a STACKIT DNS zone named dns_zone_name. Set false to use an existing zone via dns_zone_id, or to manage DNS yourself."
  type        = bool
  default     = false
}

variable "dns_zone_name" {
  description = "DNS zone to create, for example \"erp.example.com\" (no trailing dot). Required when create_dns_zone is true."
  type        = string
  default     = null
}

variable "dns_zone_id" {
  description = "ID of an existing STACKIT DNS zone. Used when create_dns_zone is false."
  type        = string
  default     = null
}

variable "enable_observability" {
  description = "Create a STACKIT Observability instance and wire it to the cluster (metrics and logs)."
  type        = bool
  default     = false
}

variable "observability_plan_name" {
  description = "Observability plan name as offered by STACKIT."
  type        = string
  default     = "Observability-Starter-EU01"
}

variable "letsencrypt_email" {
  description = "Contact address for the Let's Encrypt account (expiry notices)."
  type        = string

  validation {
    condition     = can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.letsencrypt_email))
    error_message = "letsencrypt_email must be a valid e-mail address."
  }
}

variable "letsencrypt_staging" {
  description = "Use the Let's Encrypt staging endpoint (untrusted certificates, generous rate limits). Useful for first runs."
  type        = bool
  default     = false
}

variable "ingress_nginx_chart_version" {
  description = "ingress-nginx Helm chart version."
  type        = string
  default     = "4.11.3"
}

variable "cert_manager_chart_version" {
  description = "cert-manager Helm chart version."
  type        = string
  default     = "v1.15.3"
}
