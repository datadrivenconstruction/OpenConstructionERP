# OpenConstructionERP - DigitalOcean Terraform Deployment
#
# Usage:
#   cd deploy/terraform/digitalocean
#   terraform init
#   terraform apply
#
# Creates:
#   - 1x Droplet (s-2vcpu-4gb)
#   - Docker Compose with PostgreSQL + OpenConstructionERP
#     (published image from ghcr.io, no source build on the droplet)
#   - Firewall (80, 443, 22, 8080)
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

variable "app_image" {
  description = "OpenConstructionERP container image to deploy"
  type        = string
  default     = "ghcr.io/datadrivenconstruction/openconstructionerp:latest"
}

provider "digitalocean" {
  token = var.do_token
}

resource "digitalocean_droplet" "openconstructionerp" {
  image    = "docker-20-04"
  name     = "openconstructionerp"
  region   = var.region
  size     = "s-2vcpu-4gb"
  ssh_keys = [var.ssh_key_id]

  user_data = <<-CLOUDINIT
    #!/bin/bash
    set -euo pipefail

    # Create app directory
    mkdir -p /opt/openconstructionerp
    cd /opt/openconstructionerp

    # Generate secure secrets
    JWT_SECRET=$(openssl rand -hex 32)
    PG_PASSWORD=$(openssl rand -hex 16)
    PUBLIC_IP=$(hostname -I | awk '{print $1}')

    # Create .env with secure values
    cat > .env << EOF
    JWT_SECRET=$JWT_SECRET
    POSTGRES_PASSWORD=$PG_PASSWORD
    ALLOWED_ORIGINS=http://$PUBLIC_IP:8080
    EOF

    # Self-contained stack: the published unified image plus PostgreSQL 16.
    # Written inline (instead of downloaded) so the droplet never depends on
    # repository layout. The image is PostgreSQL-only, so the app container
    # always gets a DATABASE_URL pointing at the postgres service.
    cat > docker-compose.yml << 'COMPOSE'
    services:
      postgres:
        image: postgres:16-alpine
        restart: unless-stopped
        environment:
          POSTGRES_USER: oe
          POSTGRES_PASSWORD: $${POSTGRES_PASSWORD}
          POSTGRES_DB: openestimate
        volumes:
          - pg_data:/var/lib/postgresql/data
        healthcheck:
          test: ["CMD-SHELL", "pg_isready -U oe -d openestimate"]
          interval: 10s
          timeout: 5s
          retries: 5
          start_period: 10s

      app:
        image: ${var.app_image}
        restart: unless-stopped
        depends_on:
          postgres:
            condition: service_healthy
        ports:
          - "8080:8080"
        environment:
          DATABASE_URL: postgresql+asyncpg://oe:$${POSTGRES_PASSWORD}@postgres:5432/openestimate
          DATABASE_SYNC_URL: postgresql://oe:$${POSTGRES_PASSWORD}@postgres:5432/openestimate
          JWT_SECRET: $${JWT_SECRET}
          SERVE_FRONTEND: "true"
          ALLOWED_ORIGINS: $${ALLOWED_ORIGINS}
          APP_ENV: development
          APP_DEBUG: "false"
          VECTOR_BACKEND: lancedb
        volumes:
          - app_data:/data
        healthcheck:
          test: ["CMD", "curl", "-f", "http://localhost:8080/api/health"]
          interval: 30s
          timeout: 5s
          retries: 3
          start_period: 15s

    volumes:
      pg_data:
      app_data:
    COMPOSE

    # Start services
    docker compose up -d

    echo "OpenConstructionERP installed at $PUBLIC_IP:8080"
  CLOUDINIT

  tags = ["openconstructionerp"]
}

resource "digitalocean_firewall" "openconstructionerp" {
  name        = "openconstructionerp-fw"
  droplet_ids = [digitalocean_droplet.openconstructionerp.id]

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
  value       = digitalocean_droplet.openconstructionerp.ipv4_address
  description = "OpenConstructionERP server IP"
}

output "url" {
  value       = "http://${digitalocean_droplet.openconstructionerp.ipv4_address}:8080"
  description = "OpenConstructionERP URL"
}
