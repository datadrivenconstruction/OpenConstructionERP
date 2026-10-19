output "url" {
  description = "Public URL of the company instance. The first user to register becomes administrator."
  value       = local.url
}

output "hostname" {
  description = "Host name of the instance."
  value       = local.hostname
}

output "namespace" {
  description = "Kubernetes namespace of the company."
  value       = kubernetes_namespace_v1.this.metadata[0].name
}

output "mode" {
  description = "sandbox or production."
  value       = var.mode
}

output "sandbox_expires" {
  description = "Sandbox expiry date (label only, nothing is deleted automatically). Null in production."
  value       = local.expires
}

output "database_host" {
  description = "PostgreSQL host of the company."
  value       = local.database_host
}

output "database_port" {
  description = "PostgreSQL port of the company."
  value       = local.database_port
}

output "database_name" {
  description = "Database name."
  value       = local.database_name
}

output "database_user" {
  description = "Database user."
  value       = local.database_user
}

output "database_password" {
  description = "Database password."
  value       = stackit_postgresflex_user.this.password
  sensitive   = true
}

output "bucket_name" {
  description = "Object storage bucket of the company. It must be emptied before the company can be destroyed."
  value       = stackit_objectstorage_bucket.this.name
}

output "s3_access_key" {
  description = "Object storage access key."
  value       = stackit_objectstorage_credential.this.access_key
  sensitive   = true
}

output "s3_secret_key" {
  description = "Object storage secret key."
  value       = stackit_objectstorage_credential.this.secret_access_key
  sensitive   = true
}

output "jwt_secret" {
  description = "Signing secret of the instance."
  value       = random_password.jwt.result
  sensitive   = true
}
