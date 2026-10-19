output "cluster_name" {
  description = "Name of the SKE cluster."
  value       = stackit_ske_cluster.this.name
}

output "kubeconfig" {
  description = "Kubeconfig (YAML) for the cluster. Sensitive, short lived, renewed on apply."
  value       = stackit_ske_kubeconfig.this.kube_config
  sensitive   = true
}

output "ingress_ip" {
  description = "Public address of the ingress-nginx LoadBalancer. Company DNS A records point here."
  value       = try(data.kubernetes_service.ingress.status[0].load_balancer[0].ingress[0].ip, null)
}

output "ingress_namespace" {
  description = "Namespace of ingress-nginx. Company NetworkPolicies admit traffic from it."
  value       = helm_release.ingress_nginx.namespace
}

output "cluster_issuer_name" {
  description = "ClusterIssuer that company Ingresses reference."
  value       = local.issuer_name
}

output "zone_id" {
  description = "DNS zone ID (created or supplied). Null when DNS is managed outside Terraform."
  value       = local.zone_id
}

output "egress_address_ranges" {
  description = "Public egress ranges of the cluster. Used as PostgreSQL ACL so only the cluster reaches the databases."
  value       = stackit_ske_cluster.this.egress_address_ranges
}

output "observability_instance_id" {
  description = "Observability instance ID, or null when disabled."
  value       = var.enable_observability ? stackit_observability_instance.this[0].instance_id : null
}
