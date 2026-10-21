mock_provider "stackit" {}
mock_provider "kubernetes" {}
mock_provider "random" {}

# Computed values the module reads back from the cloud.
override_resource {
  target = stackit_postgresflex_instance.this
  values = {
    instance_id = "11111111-1111-1111-1111-111111111111"
    connection_info = {
      write = {
        host = "pg.example.internal"
        port = 5432
      }
    }
  }
}

override_resource {
  target = stackit_postgresflex_user.this
  values = {
    username = "oceapp"
    password = "p@ss/w:rd+1 x"
  }
}

override_resource {
  target = stackit_objectstorage_credentials_group.this
  values = {
    credentials_group_id = "22222222-2222-2222-2222-222222222222"
  }
}

override_resource {
  target = stackit_objectstorage_credential.this
  values = {
    access_key        = "AKIAEXAMPLE"
    secret_access_key = "s3-secret-example"
  }
}

override_resource {
  target = random_password.jwt
  values = {
    result = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUV"
  }
}

variables {
  slug                   = "acme"
  display_name           = "Acme Construction GmbH"
  project_id             = "00000000-0000-0000-0000-000000000001"
  base_domain            = "erp.example.com"
  image_tag              = "20.5.1"
  postgres_flavor_id     = "flavor-id-for-tests"
  postgres_allowed_cidrs = ["203.0.113.10/32"]
}

run "production_defaults" {
  command = apply

  assert {
    condition     = kubernetes_config_map_v1.this.data["SEED_DEMO"] == "false"
    error_message = "Production must not seed demo data."
  }

  assert {
    condition     = !contains(keys(kubernetes_namespace_v1.this.metadata[0].labels), "oce/expires")
    error_message = "Production must not carry an expiry label."
  }

  assert {
    condition     = kubernetes_namespace_v1.this.metadata[0].name == "oce-acme"
    error_message = "The namespace must be oce-<slug>."
  }

  assert {
    condition     = kubernetes_config_map_v1.this.data["APP_ENV"] == "production" && kubernetes_config_map_v1.this.data["STORAGE_BACKEND"] == "s3"
    error_message = "The app must run in production mode with S3 storage."
  }

  assert {
    condition     = output.sandbox_expires == null
    error_message = "Production has no expiry date."
  }
}

run "sandbox_seeds_demo_and_expires" {
  command = apply

  variables {
    mode         = "sandbox"
    sandbox_days = 14
  }

  assert {
    condition     = kubernetes_config_map_v1.this.data["SEED_DEMO"] == "true"
    error_message = "Sandbox must seed demo data."
  }

  assert {
    condition     = can(regex("^[0-9]{4}-[0-9]{2}-[0-9]{2}$", kubernetes_namespace_v1.this.metadata[0].labels["oce/expires"]))
    error_message = "Sandbox must carry an oce/expires label with an ISO date."
  }

  assert {
    condition     = kubernetes_persistent_volume_claim_v1.data.spec[0].resources[0].requests["storage"] == "10Gi"
    error_message = "Sandbox uses the small data volume."
  }
}

run "secrets_never_in_configmap" {
  command = apply

  variables {
    smtp          = { host = "smtp.example.com", from = "erp@example.com" }
    smtp_password = "smtp-secret-example"
  }

  assert {
    condition     = alltrue([for k in ["DATABASE_URL", "DATABASE_SYNC_URL", "JWT_SECRET", "S3_ACCESS_KEY", "S3_SECRET_KEY", "SMTP_PASSWORD"] : !contains(keys(kubernetes_config_map_v1.this.data), k)])
    error_message = "Credential keys must live in the Secret, never in the ConfigMap."
  }

  assert {
    condition     = alltrue([for v in values(kubernetes_config_map_v1.this.data) : !strcontains(v, "smtp-secret-example") && !strcontains(v, "s3-secret-example") && !strcontains(v, "abcdefghijklmnop")])
    error_message = "No secret value may appear in the ConfigMap."
  }

  assert {
    condition     = contains(keys(kubernetes_secret_v1.this.data), "SMTP_PASSWORD") && contains(keys(kubernetes_secret_v1.this.data), "JWT_SECRET")
    error_message = "The Secret must carry the SMTP password and the JWT secret."
  }

  assert {
    condition     = kubernetes_config_map_v1.this.data["EMAIL_BACKEND"] == "smtp"
    error_message = "SMTP settings must switch the mail backend to smtp."
  }
}

run "no_smtp_means_console_mail" {
  command = apply

  assert {
    condition     = kubernetes_config_map_v1.this.data["EMAIL_BACKEND"] == "console" && !contains(keys(kubernetes_secret_v1.this.data), "SMTP_PASSWORD")
    error_message = "Without SMTP input the console backend is used and no SMTP secret exists."
  }
}

run "deployment_is_single_replica_recreate" {
  command = apply

  assert {
    condition     = tonumber(kubernetes_deployment_v1.this.spec[0].replicas) == 1
    error_message = "The app must run exactly one replica."
  }

  assert {
    condition     = kubernetes_deployment_v1.this.spec[0].strategy[0].type == "Recreate"
    error_message = "The strategy must be Recreate."
  }

  assert {
    condition     = kubernetes_deployment_v1.this.spec[0].template[0].spec[0].container[0].image == "ghcr.io/datadrivenconstruction/openconstructionerp:20.5.1"
    error_message = "The image must be pinned to the requested tag."
  }

  assert {
    condition     = kubernetes_deployment_v1.this.spec[0].template[0].spec[0].security_context[0].run_as_non_root == true
    error_message = "The pod must run as non-root."
  }

  assert {
    condition     = (kubernetes_deployment_v1.this.spec[0].template[0].spec[0].container[0].startup_probe[0].period_seconds * kubernetes_deployment_v1.this.spec[0].template[0].spec[0].container[0].startup_probe[0].failure_threshold) >= 600
    error_message = "The startup probe must allow at least ten minutes for the first boot."
  }
}

run "hostname_from_slug" {
  command = apply

  assert {
    condition     = output.hostname == "acme.erp.example.com" && output.url == "https://acme.erp.example.com"
    error_message = "The host name must be <slug>.<base_domain>."
  }

  assert {
    condition     = kubernetes_config_map_v1.this.data["FRONTEND_URL"] == "https://acme.erp.example.com" && kubernetes_config_map_v1.this.data["ALLOWED_ORIGINS"] == "https://acme.erp.example.com"
    error_message = "FRONTEND_URL and ALLOWED_ORIGINS must be the public URL."
  }
}

run "custom_hostname_wins" {
  command = apply

  variables {
    custom_hostname = "erp.customer.com"
  }

  assert {
    condition     = output.hostname == "erp.customer.com" && kubernetes_ingress_v1.this.spec[0].rule[0].host == "erp.customer.com"
    error_message = "custom_hostname must replace the derived host name."
  }
}

run "database_url_uses_instance_host_and_encoded_password" {
  command = apply

  assert {
    condition     = kubernetes_secret_v1.this.data["DATABASE_URL"] == "postgresql+asyncpg://oceapp:p%40ss%2Fw%3Ard%2B1%20x@pg.example.internal:5432/oce?ssl=require"
    error_message = "DATABASE_URL must use the instance host and the percent-encoded password."
  }

  assert {
    condition     = kubernetes_secret_v1.this.data["DATABASE_SYNC_URL"] == "postgresql://oceapp:p%40ss%2Fw%3Ard%2B1%20x@pg.example.internal:5432/oce?sslmode=require"
    error_message = "DATABASE_SYNC_URL must be the psycopg style twin of DATABASE_URL."
  }
}

run "ingress_allows_large_uploads_and_tls" {
  command = apply

  assert {
    condition     = kubernetes_ingress_v1.this.metadata[0].annotations["nginx.ingress.kubernetes.io/proxy-body-size"] == "512m"
    error_message = "BIM uploads need a large body size."
  }

  assert {
    condition     = kubernetes_ingress_v1.this.metadata[0].annotations["cert-manager.io/cluster-issuer"] == "letsencrypt"
    error_message = "The Ingress must request a certificate from the ClusterIssuer."
  }
}

run "model_serving_is_prepared_only_on_request" {
  command = apply

  variables {
    enable_model_serving = true
  }

  assert {
    condition     = contains(keys(kubernetes_secret_v1.this.data), "STACKIT_MODEL_SERVING_TOKEN") && contains(keys(kubernetes_secret_v1.this.data), "STACKIT_MODEL_SERVING_BASE_URL")
    error_message = "The token and base URL must be stored in the Secret."
  }
}

run "rejects_invalid_slug" {
  command = plan

  variables {
    slug = "Bad_Slug"
  }

  expect_failures = [var.slug]
}

run "rejects_slug_ending_with_hyphen" {
  command = plan

  variables {
    slug = "acme-"
  }

  expect_failures = [var.slug]
}

run "rejects_latest_image_tag" {
  command = plan

  variables {
    image_tag = "latest"
  }

  expect_failures = [var.image_tag]
}

run "rejects_retention_below_range" {
  command = plan

  variables {
    retention_days = 10
  }

  expect_failures = [var.retention_days]
}

run "rejects_retention_above_range" {
  command = plan

  variables {
    retention_days = 120
  }

  expect_failures = [var.retention_days]
}

run "rejects_unknown_mode" {
  command = plan

  variables {
    mode = "staging"
  }

  expect_failures = [var.mode]
}

run "rejects_empty_database_acl" {
  command = plan

  variables {
    postgres_allowed_cidrs = []
  }

  expect_failures = [var.postgres_allowed_cidrs]
}
