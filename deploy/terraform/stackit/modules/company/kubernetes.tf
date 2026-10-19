resource "kubernetes_namespace_v1" "this" {
  metadata {
    name   = local.namespace
    labels = merge(local.labels, { "pod-security.kubernetes.io/enforce" = "baseline" })
    annotations = {
      "oce/display-name" = var.display_name
    }
  }
}

resource "kubernetes_resource_quota_v1" "this" {
  metadata {
    name      = "company"
    namespace = kubernetes_namespace_v1.this.metadata[0].name
    labels    = local.labels
  }

  spec {
    hard = {
      "requests.cpu"           = "2"
      "requests.memory"        = "4Gi"
      "limits.memory"          = "8Gi"
      "persistentvolumeclaims" = "3"
      "pods"                   = "10"
    }
  }
}

# Gives helper pods (for example certificate solvers) requests and limits, which the quota requires.
resource "kubernetes_limit_range_v1" "this" {
  metadata {
    name      = "defaults"
    namespace = kubernetes_namespace_v1.this.metadata[0].name
    labels    = local.labels
  }

  spec {
    limit {
      type = "Container"
      default = {
        memory = "256Mi"
      }
      default_request = {
        cpu    = "50m"
        memory = "64Mi"
      }
    }
  }
}

# Ingress only from the ingress controller. Egress: DNS, then the public internet
# (PostgreSQL and object storage are external). Private ranges stay blocked, so a
# pod cannot reach other companies, the node network or the metadata service.
resource "kubernetes_network_policy_v1" "this" {
  metadata {
    name      = "isolate"
    namespace = kubernetes_namespace_v1.this.metadata[0].name
    labels    = local.labels
  }

  spec {
    pod_selector {}
    policy_types = ["Ingress", "Egress"]

    ingress {
      from {
        namespace_selector {
          match_labels = {
            "kubernetes.io/metadata.name" = var.ingress_namespace
          }
        }
      }
    }

    egress {
      ports {
        port     = "53"
        protocol = "UDP"
      }
      ports {
        port     = "53"
        protocol = "TCP"
      }
    }

    egress {
      to {
        ip_block {
          cidr   = "0.0.0.0/0"
          except = ["10.0.0.0/8", "100.64.0.0/10", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16"]
        }
      }
    }

    dynamic "egress" {
      for_each = length(var.egress_extra_cidrs) > 0 ? [1] : []

      content {
        dynamic "to" {
          for_each = var.egress_extra_cidrs

          content {
            ip_block {
              cidr = to.value
            }
          }
        }
      }
    }
  }
}

resource "kubernetes_secret_v1" "this" {
  metadata {
    name      = "oce-env"
    namespace = kubernetes_namespace_v1.this.metadata[0].name
    labels    = local.labels
  }

  type = "Opaque"
  data = local.secret_env
}

resource "kubernetes_config_map_v1" "this" {
  metadata {
    name      = "oce-config"
    namespace = kubernetes_namespace_v1.this.metadata[0].name
    labels    = local.labels
  }

  data = local.config_env
}

resource "kubernetes_persistent_volume_claim_v1" "data" {
  metadata {
    name      = "oce-data"
    namespace = kubernetes_namespace_v1.this.metadata[0].name
    labels    = local.labels
  }

  spec {
    access_modes       = ["ReadWriteOnce"]
    storage_class_name = var.storage_class

    resources {
      requests = {
        storage = "${local.data_volume_gb}Gi"
      }
    }
  }

  # The volume binds when the pod is scheduled; waiting here would deadlock the apply.
  wait_until_bound = false
}

# One replica and the Recreate strategy are deliberate: start-up creates the schema and
# stamps migrations without a cross-process lock, and the ReadWriteOnce volume can be
# attached to one node only. A rolling update would run two instances side by side.
resource "kubernetes_deployment_v1" "this" {
  metadata {
    name      = "openconstructionerp"
    namespace = kubernetes_namespace_v1.this.metadata[0].name
    labels    = local.labels
  }

  spec {
    replicas = 1

    strategy {
      type = "Recreate"
    }

    selector {
      match_labels = local.selector_labels
    }

    template {
      metadata {
        labels = merge(local.labels, local.selector_labels)
        annotations = {
          "oce/config-hash" = sha256(jsonencode(local.config_env))
          "oce/secret-hash" = sha256(jsonencode(local.secret_env))
        }
      }

      spec {
        automount_service_account_token = false

        security_context {
          run_as_non_root        = true
          run_as_user            = var.run_as_uid
          run_as_group           = var.run_as_uid
          fs_group               = var.run_as_uid
          fs_group_change_policy = "OnRootMismatch"

          seccomp_profile {
            type = "RuntimeDefault"
          }
        }

        container {
          name              = "app"
          image             = "${var.image_repository}:${var.image_tag}"
          image_pull_policy = "IfNotPresent"

          port {
            name           = "http"
            container_port = 8080
          }

          env_from {
            config_map_ref {
              name = kubernetes_config_map_v1.this.metadata[0].name
            }
          }

          env_from {
            secret_ref {
              name = kubernetes_secret_v1.this.metadata[0].name
            }
          }

          resources {
            requests = {
              cpu    = var.cpu_request
              memory = var.memory_request
            }
            limits = {
              memory = local.memory_limit
            }
          }

          security_context {
            allow_privilege_escalation = false

            capabilities {
              drop = ["ALL"]
            }
          }

          # First start creates the whole schema (about 600 tables): allow 15 minutes.
          startup_probe {
            http_get {
              path = "/api/health"
              port = "http"
            }
            period_seconds    = 10
            timeout_seconds   = 5
            failure_threshold = 90
          }

          readiness_probe {
            http_get {
              path = "/api/health"
              port = "http"
            }
            period_seconds    = 10
            timeout_seconds   = 5
            failure_threshold = 3
          }

          liveness_probe {
            http_get {
              path = "/api/health"
              port = "http"
            }
            period_seconds    = 30
            timeout_seconds   = 10
            failure_threshold = 5
          }

          volume_mount {
            name       = "data"
            mount_path = "/data"
          }
        }

        volume {
          name = "data"

          persistent_volume_claim {
            claim_name = kubernetes_persistent_volume_claim_v1.data.metadata[0].name
          }
        }
      }
    }
  }

  timeouts {
    create = "20m"
    update = "20m"
  }
}

resource "kubernetes_service_v1" "this" {
  metadata {
    name      = "openconstructionerp"
    namespace = kubernetes_namespace_v1.this.metadata[0].name
    labels    = local.labels
  }

  spec {
    type     = "ClusterIP"
    selector = local.selector_labels

    port {
      name        = "http"
      port        = 80
      target_port = "http"
    }
  }
}

resource "kubernetes_ingress_v1" "this" {
  metadata {
    name      = "openconstructionerp"
    namespace = kubernetes_namespace_v1.this.metadata[0].name
    labels    = local.labels
    annotations = {
      "cert-manager.io/cluster-issuer"                 = var.cluster_issuer_name
      "nginx.ingress.kubernetes.io/proxy-body-size"    = "512m"
      "nginx.ingress.kubernetes.io/proxy-read-timeout" = "600"
      "nginx.ingress.kubernetes.io/proxy-send-timeout" = "600"
    }
  }

  spec {
    ingress_class_name = var.ingress_class_name

    tls {
      hosts       = [local.hostname]
      secret_name = "${var.slug}-tls"
    }

    rule {
      host = local.hostname

      http {
        path {
          path      = "/"
          path_type = "Prefix"

          backend {
            service {
              name = kubernetes_service_v1.this.metadata[0].name

              port {
                number = 80
              }
            }
          }
        }
      }
    }
  }
}
