output "urls" {
  description = "Public URL per company. The first user to register becomes administrator."
  value       = { for slug, c in module.company : slug => c.url }
}

output "ingress_ip" {
  description = "Public address of the ingress controller."
  value       = module.platform.ingress_ip
}

output "sandbox_expires" {
  description = "Sandbox expiry dates (label only)."
  value       = { for slug, c in module.company : slug => c.sandbox_expires if c.mode == "sandbox" }
}

output "database_hosts" {
  description = "PostgreSQL host per company."
  value       = { for slug, c in module.company : slug => c.database_host }
}

output "buckets" {
  description = "Object storage bucket per company."
  value       = { for slug, c in module.company : slug => c.bucket_name }
}

output "kubeconfig" {
  description = "Kubeconfig of the cluster (short lived)."
  value       = module.platform.kubeconfig
  sensitive   = true
}
