# OpenConstructionERP - STACKIT platform layer (shared by all companies)
#
# Creates:
#   - 1x SKE cluster (managed Kubernetes, ACL on the API, maintenance window)
#   - ingress-nginx (public LoadBalancer) and cert-manager with a Let's Encrypt
#     HTTP-01 ClusterIssuer
#   - optionally a STACKIT DNS zone and an Observability instance
#
# Companies are deployed on top of this with modules/company.

locals {
  create_zone    = var.create_dns_zone && var.dns_zone_name != null
  zone_id        = local.create_zone ? stackit_dns_zone.this[0].zone_id : var.dns_zone_id
  issuer_name    = "letsencrypt"
  acme_directory = var.letsencrypt_staging ? "https://acme-staging-v02.api.letsencrypt.org/directory" : "https://acme-v02.api.letsencrypt.org/directory"
}

resource "stackit_observability_instance" "this" {
  count = var.enable_observability ? 1 : 0

  project_id = var.project_id
  name       = "${var.cluster_name}-obs"
  plan_name  = var.observability_plan_name
}

resource "stackit_ske_cluster" "this" {
  project_id             = var.project_id
  name                   = var.cluster_name
  kubernetes_version_min = var.kubernetes_version_min

  node_pools = [
    for p in var.node_pools : {
      name               = p.name
      machine_type       = p.machine_type
      minimum            = p.minimum
      maximum            = p.maximum
      availability_zones = p.availability_zones
      volume_size        = p.volume_size
      os_version_min     = p.os_version_min
    }
  ]

  maintenance = {
    enable_kubernetes_version_updates    = true
    enable_machine_image_version_updates = true
    start                                = var.maintenance_start
    end                                  = var.maintenance_end
  }

  extensions = {
    acl = {
      enabled       = true
      allowed_cidrs = var.allowed_cidrs
    }
    observability = {
      enabled     = var.enable_observability
      instance_id = var.enable_observability ? stackit_observability_instance.this[0].instance_id : null
    }
  }
}

resource "stackit_ske_kubeconfig" "this" {
  project_id   = var.project_id
  cluster_name = stackit_ske_cluster.this.name
  expiration   = var.kubeconfig_expiration_seconds
  refresh      = true
}

resource "stackit_dns_zone" "this" {
  count = local.create_zone ? 1 : 0

  project_id = var.project_id
  name       = var.dns_zone_name
  dns_name   = var.dns_zone_name
}

resource "helm_release" "ingress_nginx" {
  name             = "ingress-nginx"
  namespace        = "ingress-nginx"
  create_namespace = true
  repository       = "https://kubernetes.github.io/ingress-nginx"
  chart            = "ingress-nginx"
  version          = var.ingress_nginx_chart_version
  wait             = true
  timeout          = 600

  set {
    name  = "controller.service.type"
    value = "LoadBalancer"
  }

  set {
    name  = "controller.allowSnippetAnnotations"
    value = "false"
  }

  depends_on = [stackit_ske_cluster.this]
}

resource "helm_release" "cert_manager" {
  name             = "cert-manager"
  namespace        = "cert-manager"
  create_namespace = true
  repository       = "https://charts.jetstack.io"
  chart            = "cert-manager"
  version          = var.cert_manager_chart_version
  wait             = true
  timeout          = 600

  set {
    name  = "installCRDs"
    value = "true"
  }

  depends_on = [stackit_ske_cluster.this]
}

# A tiny local chart instead of kubernetes_manifest: the manifest resource needs
# the CRD to exist at plan time, a Helm release only needs it at apply time.
resource "helm_release" "cluster_issuer" {
  name      = "cluster-issuer"
  namespace = helm_release.cert_manager.namespace
  chart     = "${path.module}/charts/cluster-issuer"
  wait      = true

  set {
    name  = "name"
    value = local.issuer_name
  }

  set {
    name  = "email"
    value = var.letsencrypt_email
  }

  set {
    name  = "server"
    value = local.acme_directory
  }

  set {
    name  = "ingressClass"
    value = "nginx"
  }

  depends_on = [helm_release.cert_manager, helm_release.ingress_nginx]
}

data "kubernetes_service" "ingress" {
  metadata {
    name      = "ingress-nginx-controller"
    namespace = helm_release.ingress_nginx.namespace
  }

  depends_on = [helm_release.ingress_nginx]
}
