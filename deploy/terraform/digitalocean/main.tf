# OpenEstimate — DigitalOcean Terraform Deployment
#
# Usage:
#   cd deploy/terraform/digitalocean
#   terraform init
#   terraform apply
#
# Creates:
#   - 1x Droplet (s-2vcpu-4gb)
#   - Docker Compose with PostgreSQL + OpenEstimate
#   - Firewall (80, 443, 22)
#
# Cost: ~$24/month

terraform {
  required_providers {
    digitalocean = {
      source  = "digitalocean/digitalocean"
      version = "~> 2.0"
    }
  }
}

variable "do_token" {
  description = "DigitalOcean API token"
  type        = string
  sensitive   = true
}

variable "region" {
  description = "DigitalOcean region"
  type        = string
  default     = "fra1"
}

variable "ssh_key_id" {
  description = "SSH key ID for droplet access"
  type        = string
}

provider "digitalocean" {
  token = var.do_token
}

resource "digitalocean_droplet" "openestimate" {
  image    = "docker-20-04"
  name     = "openestimate"
  region   = var.region
  size     = "s-2vcpu-4gb"
  ssh_keys = [var.ssh_key_id]

  user_data = <<-CLOUDINIT
    #!/bin/bash
    set -euo pipefail

    # Create app directory
    mkdir -p /opt/openestimate
    cd /opt/openestimate

    # Download quickstart compose
    curl -sSL https://raw.githubusercontent.com/openestimate/openestimate/main/docker-compose.quickstart.yml \
      -o docker-compose.yml

    # Generate secure secrets
    JWT_SECRET=$(openssl rand -hex 32)
    PG_PASSWORD=$(openssl rand -hex 16)

    # Create .env with secure values
    cat > .env << EOF
    JWT_SECRET=$JWT_SECRET
    POSTGRES_PASSWORD=$PG_PASSWORD
    DATABASE_URL=postgresql+asyncpg://oe:$PG_PASSWORD@postgres:5432/openestimate
    EOF

    # Start services
    docker compose up -d

    echo "OpenEstimate installed at $(hostname -I | awk '{print $1}'):8080"
  CLOUDINIT

  tags = ["openestimate"]
}

resource "digitalocean_firewall" "openestimate" {
  name        = "openestimate-fw"
  droplet_ids = [digitalocean_droplet.openestimate.id]

  inbound_rule {
    protocol         = "tcp"
    port_range       = "22"
    source_addresses = ["0.0.0.0/0", "::/0"]
  }

  inbound_rule {
    protocol         = "tcp"
    port_range       = "80"
    source_addresses = ["0.0.0.0/0", "::/0"]
  }

  inbound_rule {
    protocol         = "tcp"
    port_range       = "443"
    source_addresses = ["0.0.0.0/0", "::/0"]
  }

  inbound_rule {
    protocol         = "tcp"
    port_range       = "8080"
    source_addresses = ["0.0.0.0/0", "::/0"]
  }

  outbound_rule {
    protocol              = "tcp"
    port_range            = "all"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }

  outbound_rule {
    protocol              = "udp"
    port_range            = "all"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }
}

output "ip_address" {
  value       = digitalocean_droplet.openestimate.ipv4_address
  description = "OpenEstimate server IP"
}

output "url" {
  value       = "http://${digitalocean_droplet.openestimate.ipv4_address}:8080"
  description = "OpenEstimate URL"
}
