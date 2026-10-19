# Secrets Manager and Observability exist in eu01 only, so the whole stack lives there.
provider "stackit" {
  default_region           = "eu01"
  service_account_key_path = var.service_account_key_path
}

# The Kubernetes and Helm providers are configured from the cluster that the platform
# module creates. On the very first run the kubeconfig does not exist yet: apply the
# platform first (terraform apply -target=module.platform), then everything else.
locals {
  kubeconfig = try(yamldecode(module.platform.kubeconfig), null)

  kube_host        = try(local.kubeconfig.clusters[0].cluster.server, null)
  kube_ca          = try(base64decode(local.kubeconfig.clusters[0].cluster["certificate-authority-data"]), null)
  kube_client_cert = try(base64decode(local.kubeconfig.users[0].user["client-certificate-data"]), null)
  kube_client_key  = try(base64decode(local.kubeconfig.users[0].user["client-key-data"]), null)
}

provider "kubernetes" {
  host                   = local.kube_host
  cluster_ca_certificate = local.kube_ca
  client_certificate     = local.kube_client_cert
  client_key             = local.kube_client_key
}

provider "helm" {
  kubernetes {
    host                   = local.kube_host
    cluster_ca_certificate = local.kube_ca
    client_certificate     = local.kube_client_cert
    client_key             = local.kube_client_key
  }
}
