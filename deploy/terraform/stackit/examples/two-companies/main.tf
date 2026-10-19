# OpenConstructionERP on STACKIT - one isolated instance per company
#
# Usage:
#   cd deploy/terraform/stackit/examples/two-companies
#   cp terraform.tfvars.example terraform.tfvars    # then edit
#   terraform init
#   terraform apply -target=module.platform         # cluster, ingress, certificates
#   terraform apply                                 # companies
#
# Creates:
#   - 1x SKE cluster with ingress-nginx and cert-manager (modules/platform)
#   - per entry of var.companies (modules/company): PostgreSQL Flex instance,
#     object storage bucket, namespace with NetworkPolicy, app, TLS ingress, DNS record

module "platform" {
  source = "../../modules/platform"

  project_id           = var.project_id
  cluster_name         = var.cluster_name
  allowed_cidrs        = var.api_allowed_cidrs
  letsencrypt_email    = var.letsencrypt_email
  create_dns_zone      = var.create_dns_zone
  dns_zone_name        = var.create_dns_zone ? var.base_domain : null
  dns_zone_id          = var.dns_zone_id
  enable_observability = var.enable_observability
}

module "company" {
  source   = "../../modules/company"
  for_each = var.companies

  slug         = each.key
  display_name = each.value.display_name
  project_id   = var.project_id
  mode         = each.value.mode
  sandbox_days = each.value.sandbox_days
  image_tag    = var.image_tag

  base_domain       = var.base_domain
  custom_hostname   = each.value.custom_hostname
  create_dns_record = each.value.create_dns_record
  zone_id           = module.platform.zone_id
  ingress_ip        = module.platform.ingress_ip

  ingress_namespace   = module.platform.ingress_namespace
  cluster_issuer_name = module.platform.cluster_issuer_name

  postgres_flavor_id     = var.postgres_flavor_id
  postgres_storage_gb    = each.value.postgres_storage_gb
  postgres_allowed_cidrs = module.platform.egress_address_ranges
  retention_days         = each.value.retention_days
  data_volume_gb         = each.value.data_volume_gb

  registration_mode    = each.value.registration_mode
  enable_model_serving = each.value.enable_model_serving
}
