mock_provider "stackit" {}
mock_provider "kubernetes" {}
mock_provider "helm" {}

variables {
  project_id        = "00000000-0000-0000-0000-000000000001"
  letsencrypt_email = "ops@example.com"
}

run "defaults_are_secure_and_refreshing" {
  command = plan

  assert {
    condition     = stackit_ske_kubeconfig.this.refresh == true
    error_message = "The kubeconfig must be refreshed so expired credentials are renewed on apply."
  }

  assert {
    condition     = stackit_ske_cluster.this.extensions.acl.enabled == true
    error_message = "The API server ACL extension must be enabled."
  }

  assert {
    condition     = stackit_ske_cluster.this.extensions.observability.enabled == false
    error_message = "Observability is opt-in."
  }

  assert {
    condition     = length(stackit_observability_instance.this) == 0 && length(stackit_dns_zone.this) == 0
    error_message = "Optional resources must not be created by default."
  }
}

run "ingress_and_issuer_are_pinned" {
  command = plan

  assert {
    condition     = helm_release.ingress_nginx.version != "" && helm_release.cert_manager.version != ""
    error_message = "Helm charts must be pinned to explicit versions."
  }

  assert {
    condition     = helm_release.ingress_nginx.namespace == "ingress-nginx"
    error_message = "Company NetworkPolicies expect ingress-nginx in the ingress-nginx namespace."
  }
}

run "observability_and_zone_are_created_on_request" {
  command = plan

  variables {
    enable_observability = true
    create_dns_zone      = true
    dns_zone_name        = "erp.example.com"
  }

  assert {
    condition     = length(stackit_observability_instance.this) == 1
    error_message = "enable_observability must create the instance."
  }

  assert {
    condition     = length(stackit_dns_zone.this) == 1
    error_message = "create_dns_zone must create the zone."
  }
}

run "staging_issuer_switch" {
  command = plan

  variables {
    letsencrypt_staging = true
  }

  assert {
    condition     = strcontains(one([for s in helm_release.cluster_issuer.set : s.value if s.name == "server"]), "staging")
    error_message = "letsencrypt_staging must select the staging ACME endpoint."
  }
}

run "rejects_bad_cluster_name" {
  command = plan

  variables {
    cluster_name = "Bad_Name"
  }

  expect_failures = [var.cluster_name]
}

run "rejects_empty_node_pools" {
  command = plan

  variables {
    node_pools = []
  }

  expect_failures = [var.node_pools]
}
