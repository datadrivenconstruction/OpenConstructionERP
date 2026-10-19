terraform {
  required_version = ">= 1.7"

  required_providers {
    stackit = {
      source  = "stackitcloud/stackit"
      version = "~> 0.120"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.35"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}
