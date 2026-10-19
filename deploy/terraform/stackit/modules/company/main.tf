# OpenConstructionERP - one isolated company on STACKIT
#
# Creates, per company:
#   - 1x PostgreSQL Flex instance with its own user and database
#   - 1x Object Storage bucket with its own credentials group and credential
#   - 1x Kubernetes namespace (quota, limits, NetworkPolicy) running the app
#     as a single replica with a persistent /data volume
#   - Ingress with a Let's Encrypt certificate and an optional DNS A record
#   - optionally an AI Model Serving token (prepared, not yet used by the app)
#
# Nothing is shared between companies except the cluster and the ingress.

locals {
  is_sandbox = var.mode == "sandbox"
  namespace  = "oce-${var.slug}"
  hostname   = coalesce(var.custom_hostname, "${var.slug}.${var.base_domain}")
  url        = "https://${local.hostname}"

  # Sizes per mode; every one can be overridden by its input.
  sizes = {
    sandbox = {
      postgres_storage_gb = 10
      data_volume_gb      = 10
      memory_limit        = "2Gi"
      retention_days      = 32
    }
    production = {
      postgres_storage_gb = 50
      data_volume_gb      = 50
      memory_limit        = "3Gi"
      retention_days      = 35
    }
  }
  size = local.sizes[var.mode]

  postgres_storage_gb = coalesce(var.postgres_storage_gb, local.size.postgres_storage_gb)
  data_volume_gb      = coalesce(var.data_volume_gb, local.size.data_volume_gb)
  memory_limit        = coalesce(var.memory_limit, local.size.memory_limit)
  retention_days      = coalesce(var.retention_days, local.size.retention_days)

  expires = local.is_sandbox ? formatdate("YYYY-MM-DD", timeadd(terraform_data.created_at.output, "${var.sandbox_days * 24}h")) : null

  labels = merge(
    var.labels,
    {
      "app.kubernetes.io/name"       = "openconstructionerp"
      "app.kubernetes.io/instance"   = var.slug
      "app.kubernetes.io/managed-by" = "terraform"
      "oce/company"                  = var.slug
      "oce/mode"                     = var.mode
    },
    local.is_sandbox ? { "oce/expires" = local.expires } : {}
  )

  selector_labels = {
    "app.kubernetes.io/name"     = "openconstructionerp"
    "app.kubernetes.io/instance" = var.slug
  }

  database_name = "oce"
  database_user = "oceapp"
  database_host = stackit_postgresflex_instance.this.connection_info.write.host
  database_port = stackit_postgresflex_instance.this.connection_info.write.port

  # urlencode turns a space into "+", which inside a URL user info is a literal plus.
  database_password_encoded = replace(urlencode(stackit_postgresflex_user.this.password), "+", "%20")
  database_authority        = "${local.database_user}:${local.database_password_encoded}@${local.database_host}:${local.database_port}/${local.database_name}"
  database_url              = "postgresql+asyncpg://${local.database_authority}${var.database_ssl ? "?ssl=require" : ""}"
  database_sync_url         = "postgresql://${local.database_authority}${var.database_ssl ? "?sslmode=require" : ""}"

  smtp_enabled = var.smtp != null

  # Non-secret settings. Anything that grants access belongs in local.secret_env.
  config_env = merge(
    {
      APP_ENV           = "production"
      SERVE_FRONTEND    = "true"
      SEED_DEMO         = local.is_sandbox ? "true" : "false"
      REGISTRATION_MODE = var.registration_mode
      FRONTEND_URL      = local.url
      ALLOWED_ORIGINS   = local.url
      TRUSTED_PROXIES   = var.trusted_proxies
      LOG_LEVEL         = var.log_level
      OE_DATA_DIR       = "/data"
      STORAGE_BACKEND   = "s3"
      S3_ENDPOINT       = var.object_storage_endpoint
      S3_BUCKET         = stackit_objectstorage_bucket.this.name
      S3_REGION         = var.object_storage_region
      EMAIL_BACKEND     = local.smtp_enabled ? "smtp" : "console"
    },
    local.smtp_enabled ? {
      SMTP_HOST = var.smtp.host
      SMTP_PORT = tostring(var.smtp.port)
      SMTP_USER = var.smtp.user
      SMTP_FROM = var.smtp.from
      SMTP_TLS  = tostring(var.smtp.tls)
    } : {}
  )

  secret_env = merge(
    {
      DATABASE_URL      = local.database_url
      DATABASE_SYNC_URL = local.database_sync_url
      JWT_SECRET        = random_password.jwt.result
      S3_ACCESS_KEY     = stackit_objectstorage_credential.this.access_key
      S3_SECRET_KEY     = stackit_objectstorage_credential.this.secret_access_key
    },
    var.smtp_password != null ? { SMTP_PASSWORD = var.smtp_password } : {},
    var.enable_model_serving ? {
      STACKIT_MODEL_SERVING_TOKEN    = stackit_modelserving_token.this[0].token
      STACKIT_MODEL_SERVING_BASE_URL = var.model_serving_base_url
    } : {}
  )
}

# Keeps the creation time in state so the sandbox expiry date does not move on every run.
resource "terraform_data" "created_at" {
  input = timestamp()

  lifecycle {
    ignore_changes = [input]
  }
}

# ── Database ────────────────────────────────────────────────────────────────

resource "stackit_postgresflex_instance" "this" {
  project_id      = var.project_id
  name            = local.namespace
  flavor_id       = var.postgres_flavor_id
  version         = var.postgres_version
  backup_schedule = var.backup_schedule
  retention_days  = local.retention_days

  storage = {
    class = var.postgres_storage_class
    size  = local.postgres_storage_gb
  }

  network = {
    acl = var.postgres_allowed_cidrs
  }
}

resource "stackit_postgresflex_user" "this" {
  project_id  = var.project_id
  instance_id = stackit_postgresflex_instance.this.instance_id
  username    = local.database_user
  roles       = ["login", "createdb"]
}

resource "stackit_postgresflex_database" "this" {
  project_id  = var.project_id
  instance_id = stackit_postgresflex_instance.this.instance_id
  name        = local.database_name
  owner       = stackit_postgresflex_user.this.username
}

# ── Object storage ──────────────────────────────────────────────────────────

resource "stackit_objectstorage_bucket" "this" {
  project_id = var.project_id
  name       = "${local.namespace}-data"
}

resource "stackit_objectstorage_credentials_group" "this" {
  project_id = var.project_id
  name       = local.namespace
}

resource "stackit_objectstorage_credential" "this" {
  project_id           = var.project_id
  credentials_group_id = stackit_objectstorage_credentials_group.this.credentials_group_id
}

# ── AI Model Serving (prepared) ─────────────────────────────────────────────

resource "stackit_modelserving_token" "this" {
  count = var.enable_model_serving ? 1 : 0

  project_id = var.project_id
  name       = local.namespace
}

# ── Secrets and DNS ─────────────────────────────────────────────────────────

# Fixed for the lifetime of the company: every session token is signed with it.
# Alphanumeric only, so it survives env files and URLs unchanged.
resource "random_password" "jwt" {
  length  = 48
  special = false
}

resource "stackit_dns_record_set" "this" {
  count = var.zone_id != null && var.create_dns_record ? 1 : 0

  project_id = var.project_id
  zone_id    = var.zone_id
  name       = "${local.hostname}."
  type       = "A"
  ttl        = 300
  records    = [var.ingress_ip]

  lifecycle {
    precondition {
      condition     = var.ingress_ip != null
      error_message = "ingress_ip is required when a DNS record is created."
    }
  }
}
