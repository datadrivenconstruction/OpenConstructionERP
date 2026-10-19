# OpenConstructionERP on STACKIT, one isolated instance per company

English | [Deutsch](README.de.md) | [Русский](README.ru.md)

Terraform modules that run OpenConstructionERP on [STACKIT](https://www.stackit.de), the German
cloud, with a **separate instance for every company**: its own database server, its own bucket,
its own credentials and its own namespace. Data stays in German data centres (region `eu01`).

```
deploy/terraform/stackit/
  modules/platform/   shared layer: SKE cluster, ingress-nginx, cert-manager, optional DNS zone and Observability
  modules/company/    one company: PostgreSQL Flex, bucket, namespace, app, TLS ingress, DNS record
  examples/two-companies/   ready to copy: one production and one sandbox company
```

## What is created for each company

| Resource | Purpose |
|---|---|
| PostgreSQL Flex instance, user, database | The company's own database server. Only the cluster's egress addresses may connect (ACL). Daily backups, 32 to 90 days retention |
| Object Storage bucket, credentials group, credential | Own bucket and keys for BIM/CAD files and documents |
| Kubernetes namespace `oce-<slug>` | Isolation boundary, labelled with company and mode |
| ResourceQuota and LimitRange | A company cannot starve its neighbours |
| NetworkPolicy | Ingress only from the ingress controller; egress only to DNS and the public internet, never to other namespaces or the node network |
| Secret `oce-env` | Database URL, JWT secret, S3 keys, optional SMTP password and model serving token |
| ConfigMap `oce-config` | All non-secret settings |
| PersistentVolumeClaim `oce-data` | The `/data` directory (about 20 modules write there even with S3 storage) |
| Deployment (1 replica, `Recreate`) | The application, pinned to an explicit image version |
| Service and Ingress | Public HTTPS with a Let's Encrypt certificate, uploads up to 512 MB |
| DNS A record | `<slug>.<base_domain>` to the ingress address (optional) |
| AI Model Serving token | Optional, prepared for the roadmap (see below) |

Shared once: the SKE cluster, ingress-nginx, cert-manager and an optional Observability instance.

## Prerequisites

- A STACKIT project and a **service account key** (JSON) with rights to create the resources above.
- **Object Storage enabled** in the project (once, in the STACKIT portal).
- A domain you can delegate to STACKIT DNS, or an existing STACKIT DNS zone. Without DNS automation
  set `zone_id = null` and create the A records yourself.
- Terraform 1.7 or newer (1.9 is what CI uses) and network access to `ghcr.io`.
- A PostgreSQL Flex flavor ID: `stackit postgresflex flavor list`.

## Quick start

```bash
cd deploy/terraform/stackit/examples/two-companies
export STACKIT_SERVICE_ACCOUNT_KEY_PATH=/path/to/key.json
cp terraform.tfvars.example terraform.tfvars        # edit project, domain, flavor, companies
terraform init
terraform apply -target=module.platform             # cluster, ingress, certificates (first run only)
terraform apply                                     # databases, buckets and the companies
```

`terraform output urls` lists the addresses. **Open the URL and register: the first user to
register becomes the administrator** of that instance. Registration afterwards follows
`registration_mode` (default `admin-approve`).

The first start of an instance creates about 600 tables and takes a few minutes; the startup probe
waits up to 15 minutes.

Before real use, move the state to a remote backend, see `examples/two-companies/backend.tf.example`.
The state contains database passwords and storage keys in clear text, so keep it private and
encrypted. A PostgreSQL (`pg`) backend gives state locking; the S3 backend on STACKIT Object Storage
works but has no locking.

## Adding a company

Add an entry to the `companies` map and apply:

```hcl
companies = {
  acme   = { display_name = "Acme Construction GmbH" }
  bauer  = { display_name = "Bauer Hochbau", custom_hostname = "erp.bauer.example" }
}
```

A new company gets a new database, bucket and namespace; existing companies are not touched.
With `custom_hostname` the customer must point a DNS record (A to the ingress address) at the
platform if the name is outside your zone; set `create_dns_record = false` in that case.

## Sandbox to production

A sandbox (`mode = "sandbox"`) has demo data (`SEED_DEMO=true`), smaller sizes and the label
`oce/expires=<date>` on all objects (default 30 days, `sandbox_days`). The label is information
only: **nothing is deleted automatically**. To turn a sandbox into a production company, create a
new production entry; demo data is not migrated, so sandboxes are for trials. Do not put real
project data into a sandbox.

## Removing a company

1. Remove the entry from the map. Terraform destroys the namespace, the database and the bucket.
2. A bucket that still holds objects **cannot be destroyed**. Empty it first (STACKIT portal or any
   S3 tool with the company's keys from `terraform output`), then apply again.
3. Deleting the PostgreSQL instance deletes its backups. Export what you need beforehand.

## Sizing

| | Sandbox | Production |
|---|---|---|
| App memory request / limit | 1 GiB / 2 GiB | 1 GiB / 3 GiB |
| App CPU request | 500m | 500m |
| `/data` volume | 10 GB | 50 GB |
| PostgreSQL storage | 10 GB | 50 GB |
| Backup retention | 32 days | 35 days |
| Node capacity needed | about 0.5 vCPU, 1 GiB | about 0.5 vCPU, 1 GiB, burst to 3 GiB |

All values can be overridden per company. A 4 vCPU / 8 GiB node holds roughly three companies.
Raise `minimum`/`maximum` in `node_pools` as companies are added. Choose the PostgreSQL flavor
(`postgres_flavor_id`) by company size; start small, it can be changed later.

## Security notes

- **Isolation per company:** own namespace with NetworkPolicy, own PostgreSQL instance (separate
  server, not just a separate schema), own bucket, own credentials, own JWT secret.
- The database accepts connections only from the cluster's egress addresses, and the application connects with TLS enabled.
- Secrets live in Kubernetes Secrets (base64, not encrypted by Kubernetes itself) and in the
  Terraform state. Encrypt the state at rest, restrict who can read it and the cluster.
- Restrict `api_allowed_cidrs` (the Kubernetes API ACL) to your office or CI addresses.
- The container runs as non-root with all capabilities dropped and a RuntimeDefault seccomp profile.
- The JWT secret is generated once per company and is fixed; do not delete it from the state, all
  sessions would end.
- Image versions are pinned (`latest` is rejected). Upgrade by changing `image_tag` and applying.

## Why one replica and the `Recreate` strategy

Start-up creates the schema, runs the auto-heal migrator (guarded by a database advisory lock) and
stamps the migration state without a lock. Two instances starting together, as in a rolling update,
could race. The `/data` volume is also `ReadWriteOnce`: it attaches to one node at a time. So the
module runs exactly one replica and replaces it with `Recreate`: the old pod stops, then the new
one starts. An upgrade therefore means a short downtime (typically below a minute after the first
boot). Redis and Qdrant are not deployed: the job runner falls back to in-process execution and the
image includes an embedded vector store under `/data/vectors`.

## Roadmap, not in this version

- OIDC single sign-on for company logins.
- AI Model Serving in the app: the module can create a token and stores `STACKIT_MODEL_SERVING_TOKEN`
  and `STACKIT_MODEL_SERVING_BASE_URL` in the company Secret. The application does not read an
  OpenAI-compatible base URL from the environment yet (roadmap package 4).
- A backup/export command for a whole company (database dump plus bucket plus `/data`).
- Optional pre-start migration Job (today the application migrates itself on start).

## Verify before first apply

The modules were written from the provider documentation without access to a STACKIT account. CI
checks formatting, schema validity and logic with mocked providers; it cannot confirm the
following. Check them on the first run (`terraform validate` and `plan` will point at most of them):

1. `stackit_postgresflex_instance`: attribute names `flavor_id`, `network.acl`, `storage`,
   `retention_days`, and the output path `connection_info.write.host` / `.port`.
2. PostgreSQL Flex: allowed instance name length (names are `oce-<slug>`, up to 24 characters),
   minimum storage size, whether the server requires TLS (`?ssl=require` is set by default,
   switch off with `database_ssl = false` only if the connection fails for that reason), and
   whether users with roles `login` and `createdb` can create all tables.
3. The `ssl=require` query parameter and the `DATABASE_SYNC_URL` variable name in your image
   version (settings read `database_sync_url`).
4. SKE: machine type `c1.4` and zone `eu01-1` exist in your project (change `node_pools`), the
   `kubernetes_version_min`, and that the `observability` extension block takes `instance_id`.
5. SKE kubeconfig: the module expects client certificate data (`client-certificate-data`) in the
   generated kubeconfig. If STACKIT returns an OIDC/token based config, adapt `providers.tf`.
6. `egress_address_ranges` is the address the database actually sees. If pods reach the database
   through another path, widen `postgres_allowed_cidrs`.
7. A `type: LoadBalancer` Service gets a public address from STACKIT without extra annotations
   (expected, not confirmed), and client IPs reach the app through `X-Forwarded-For`
   (`externalTrafficPolicy` is the default `Cluster`, so the app may see node addresses).
8. `TRUSTED_PROXIES` default covers the usual pod and node ranges (`10.0.0.0/8`, `100.64.0.0/10`, ...).
   Verify the pod CIDR of your cluster is inside it.
9. Container user ID: the image user `oe` is a system user; `run_as_uid` defaults to 999. Check
   with `docker run --rm --entrypoint id ghcr.io/datadrivenconstruction/openconstructionerp:<tag>`.
10. DNS record set `name` format (fully qualified with trailing dot is used) and the TTL.
11. Object storage: bucket naming rules and uniqueness (`oce-<slug>-data`), that the credential
    needs no extra permission binding, and the S3 endpoint `https://object.storage.eu01.onstackit.cloud`
    with path-style access in the application's S3 client.
12. AI Model Serving: `stackit_modelserving_token` may require a provider experiment flag in some
    provider versions; the token is only created when `enable_model_serving = true`.
13. Pinned chart versions (ingress-nginx 4.11.3, cert-manager v1.15.3) and the ingress-nginx chart
    repository are reachable from the cluster. Running a sandbox with `SEED_DEMO=true` under
    `APP_ENV=production`: check that demo accounts are created as expected in your image version.
14. The first `terraform apply -target=module.platform` is needed because the Kubernetes and Helm
    providers are configured from a cluster that does not exist yet.

## Costs

You pay for the SKE worker nodes, one PostgreSQL Flex instance and one bucket per company, the
LoadBalancer and optional Observability. The platform layer is shared, so the cost of an additional
company is mainly its PostgreSQL instance plus a fraction of a node.
