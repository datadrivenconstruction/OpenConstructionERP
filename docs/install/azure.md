# OpenConstructionERP on Microsoft Azure

English | [Deutsch](azure.de.md) | [Русский](azure.ru.md)

How to run OpenConstructionERP on Azure with the data kept in the region you choose, and what works today for sign-in with Microsoft Entra ID. No Azure-specific code is involved: the platform runs as one Docker container against PostgreSQL, and everything below is configuration.

**What has been checked.** Every setting name below was checked against the source of version 18.8.2 (`backend/app/config.py`, `backend/app/modules/users/`, `deploy/docker/`). The Azure portal and CLI steps were written from the Azure documentation and have **not** been run on a live subscription. Treat the first deployment as the test, and read "Sign-in with Entra ID" before promising single sign-on to anyone.

## Choose a layout

| | Azure VM with Docker (recommended) | Azure Container Apps |
|---|---|---|
| Effort | One VM, one compose file | No VM to patch, more moving parts |
| Files in `/data` | Managed disk, bind mount | Azure Files share (network file system) |
| TLS | Reverse proxy on the VM (below) | Built into the ingress |
| Fit | Most companies | If your policy forbids VMs |

Both use **Azure Database for PostgreSQL Flexible Server** (PostgreSQL 16) and run **exactly one replica** of the application. Start-up creates about 600 tables and runs the migrations, so two instances starting together can race. Do not scale out.

The published image is built for `linux/amd64`. Pick x64 sizes, not the Arm-based ones.

## Sizing

The core needs **3 GB of memory on a dedicated machine**: about 800 MB for the application, 200 to 400 MB for PostgreSQL when it runs beside it, and a one-off peak of about 1.2 GB while a country cost pack is imported (version 17.7.0 or newer). The reasoning is in [INSTALL_LINUX.md](../INSTALL_LINUX.md#what-the-machine-needs). With the database on Flexible Server the VM no longer carries PostgreSQL, but keep the headroom for the import.

| Part | Starting point | Notes |
|---|---|---|
| VM | 2 vCPU, 8 GiB (for example `Standard_D2s_v5`) | Not a burstable size: the memory is only nominally yours when the import runs. Add 2 GB swap if the image has none |
| Container Apps | 2 vCPU, 4 GiB, minimum and maximum replicas 1 | Not less than 3 GiB |
| PostgreSQL Flexible Server | Burstable `Standard_B2s` to start, General Purpose `Standard_D2ds_v5` for a busy team, 64 GiB storage | Size can be changed later; storage can only grow |
| Data disk (`/data`) | 64 GiB Premium SSD | Vector store and uploaded files; about 20 modules write here |

## Region and data residency

Create the resource group, the VM, the database and the disk in **one** region (for example `germanywestcentral`, `uaenorth`, `qatarcentral`, `centralindia`). Residency is decided by these choices:

- Do not enable geo-redundant backup unless the paired region is acceptable to you; it stores copies there.
- Do not enable cross-region restore in Azure Backup for the VM, for the same reason.
- The application calls out to the internet only for features you switch on (AI providers, maps, converter downloads). See [maps.md](../maps.md) and the AI settings if outbound traffic must be limited.

## 1. Network and database

```bash
az group create -n rg-oce -l germanywestcentral
az network vnet create -g rg-oce -n vnet-oce --address-prefixes 10.20.0.0/16 \
  --subnet-name snet-vm --subnet-prefixes 10.20.1.0/24
```

Create the PostgreSQL server with private access in its own delegated subnet, so it has no public address (check `az postgres flexible-server create --help` for the current flags):

```bash
az postgres flexible-server create -g rg-oce -n oce-pg-<unique> -l germanywestcentral \
  --version 16 --tier Burstable --sku-name Standard_B2s --storage-size 64 \
  --admin-user oceadmin --admin-password '<long random password>' \
  --vnet vnet-oce --subnet snet-pg --address-prefixes 10.20.2.0/24 \
  --backup-retention 14 --geo-redundant-backup Disabled
```

Then create an application role and database from the VM (or Cloud Shell in the same network). The application creates its own tables, so the role has to own the database:

```sql
CREATE ROLE oe LOGIN PASSWORD '<another long random password>';
GRANT oe TO oceadmin;
CREATE DATABASE openestimate OWNER oe;
```

Flexible Server requires TLS by default, so the connection strings below carry `ssl=require`. If the password contains `@`, `/` or `:`, percent-encode it in the URL (`@` becomes `%40`). The `OE_DB_*` parts used by the quickstart cannot add `ssl`, so use the two URLs here.

## 2. The VM

Create an Ubuntu 24.04 LTS VM in `snet-vm`, add a managed data disk, and allow inbound 80 and 443 (and SSH only from your office addresses) in the network security group. Install Docker (https://docs.docker.com/engine/install/ubuntu/), then format the data disk and mount it at `/srv/oce-data`.

The container runs as the non-root user `oe`. Find its numeric id and give it the folder:

```bash
docker run --rm --entrypoint id ghcr.io/datadrivenconstruction/openconstructionerp:<version>
sudo chown -R <uid>:<gid> /srv/oce-data
```

Create `/srv/oce/.env` (mode 600). Generate the secret once with `openssl rand -hex 32` and never change it afterwards; every session would end.

```bash
APP_ENV=production
JWT_SECRET=<64 hex characters>
DATABASE_URL=postgresql+asyncpg://oe:<password>@oce-pg-<unique>.postgres.database.azure.com:5432/openestimate?ssl=require
DATABASE_SYNC_URL=postgresql://oe:<password>@oce-pg-<unique>.postgres.database.azure.com:5432/openestimate?sslmode=require
ALLOWED_ORIGINS=https://erp.example.com
REGISTRATION_MODE=admin-approve
```

With `APP_ENV=production` the server refuses to start on a short or well known `JWT_SECRET` (under 32 characters). `ALLOWED_ORIGINS` must contain the exact address users type; if it is wrong the page loads blank and the server log stays clean. `TRUSTED_PROXIES` already covers the Docker network, so the proxy below needs no change. Redis is not required: without it jobs run inside the application process.

`/srv/oce/docker-compose.yml`:

```yaml
services:
  app:
    image: ghcr.io/datadrivenconstruction/openconstructionerp:<version>   # pin a released version
    restart: unless-stopped
    env_file: .env
    volumes:
      - /srv/oce-data:/data
    expose: ["8080"]
  caddy:
    image: caddy:2
    restart: unless-stopped
    ports: ["80:80", "443:443"]
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
volumes:
  caddy_data:
```

`/srv/oce/Caddyfile` (point the DNS A record of `erp.example.com` at the VM first; the certificate is requested automatically):

```
erp.example.com {
    reverse_proxy app:8080
}
```

```bash
cd /srv/oce && docker compose up -d
docker compose logs -f app        # the first start takes a few minutes
```

Open `https://erp.example.com`. **The first user to register becomes the administrator**, so register yourself straight away. Later registrations follow `REGISTRATION_MODE`. Any other proxy (Application Gateway, Front Door) must keep WebSockets, large uploads and the original host name; see [deploy/docker/README.md](../../deploy/docker/README.md).

## Alternative: Container Apps

Create the environment in the same region and VNet, an Azure Files share for `/data`, and one app with:

- image `ghcr.io/datadrivenconstruction/openconstructionerp:<version>`, target port **8080**, external ingress;
- CPU 2, memory 4 Gi, **minimum and maximum replicas 1**;
- the share mounted at `/data`;
- the variables of the `.env` above, with `JWT_SECRET` and the two database URLs stored as Container Apps secrets.

Add your domain under Custom domains for a managed certificate. If you used public access for the database, allow the app's outbound address on the PostgreSQL server. How the application behaves on an SMB file share has not been tested; if you see locking errors or slowness in `/data`, use the VM layout.

## Files and object storage

Keep `STORAGE_BACKEND` at its default (`local`): files go to `/data` on the managed disk. The `s3` backend speaks the S3 protocol (`S3_ENDPOINT`, `S3_BUCKET`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_REGION`) and Azure Blob Storage does not, so it cannot be used directly. An S3-compatible service that you run yourself can.

## Sign-in with Entra ID

How sign-in works in 18.8.2: set `OIDC_ENABLED`, `OIDC_ISSUER_URL`, `OIDC_CLIENT_ID` and `OIDC_CLIENT_SECRET` (optional: `OIDC_SCOPES`, default `openid email profile`; `OIDC_AUTO_CREATE_USERS`, default true; `OIDC_GROUP_ROLE_MAP`). The login page then shows "Sign in with SSO". The browser goes to the provider and comes back to `https://<your host>/auth/oidc/callback`. The server exchanges the code, reads the provider's user info (`sub`, `email`, `name`, `groups`) and issues its own tokens.

**Direct sign-in against Entra ID does not work yet.** Two things in the code stand in the way:

1. The login page builds the authorization address as `<issuer>/protocol/openid-connect/auth`. That is the path of Keycloak. Entra ID uses `https://login.microsoftonline.com/<tenant>/oauth2/v2.0/authorize`.
2. Roles are read from a `groups` claim in the user info. The Entra user info endpoint does not return groups, so `OIDC_GROUP_ROLE_MAP` cannot be fed by Entra directly.

The server also does not validate the ID token; it relies on the user info answer fetched over TLS. Restrict who may sign in inside Entra itself (step 4 below).

**What works today: Keycloak as the broker.** Run Keycloak (separate container or VM, not covered here), add Entra ID as an identity provider in it, and point the platform at the Keycloak realm. The platform sees a standard Keycloak, Entra handles passwords and multi-factor prompts, and Keycloak's group mapper delivers the `groups` claim.

1. **Entra ID app registration** (Microsoft Entra admin center, App registrations, New registration): name `OpenConstructionERP`, supported account type "this organizational directory only", redirect URI of type **Web**: `https://<keycloak host>/realms/<realm>/broker/<alias>/endpoint`. Note the **Application (client) ID** and the **Directory (tenant) ID**.
2. Certificates and secrets, New client secret. Copy the **value** at once (it is shown only once) and note the expiry date; sign-in stops when the secret expires.
3. API permissions: `openid`, `email`, `profile` (delegated, Microsoft Graph). Under Token configuration add the optional claim `email`, and a groups claim if you want roles from groups.
4. Enterprise applications, your app, Properties: set "Assignment required" to Yes and assign the people or groups who may sign in. Without it every user of your tenant can sign in.
5. **Keycloak:** Identity providers, add "OpenID Connect v1.0" with the discovery endpoint `https://login.microsoftonline.com/<tenant id>/v2.0/.well-known/openid-configuration` and the client ID and secret from steps 1 and 2. Create a client `openconstructionerp` in the realm with the valid redirect URI `https://erp.example.com/auth/oidc/callback`, and a client scope with a group membership mapper (claim name `groups`, added to the user info).
6. **Platform:** add to `.env` and restart.

```bash
OIDC_ENABLED=true
OIDC_ISSUER_URL=https://<keycloak host>/realms/<realm>
OIDC_CLIENT_ID=openconstructionerp
OIDC_CLIENT_SECRET=<the Keycloak client secret>
OIDC_GROUP_ROLE_MAP={"oce-admins":"admin","oce-estimators":"editor","oce-viewers":"viewer"}
```

The mapped role is applied on every login; the first matching group wins. A person who arrives without a mapped group is created as `editor` (not the `viewer` default of self-registration), so keep "Assignment required" on. An existing local account with the same e-mail address is linked to the identity at the first SSO login.

**Known problems in 18.8.2 that affect any provider** (found while checking this guide, to be fixed in the code): a user who is already linked and signs in again with an unchanged role gets "403 No matching account found"; and with `OIDC_AUTO_CREATE_USERS=false` an unknown user gets a server error instead of a clean refusal. Until this is fixed, test a second login of the same person before rollout, and control access with "Assignment required" rather than with `OIDC_AUTO_CREATE_USERS`.

## Backups

- **Database:** Flexible Server makes automatic backups and supports point-in-time restore inside the retention window (7 to 35 days, set with `--backup-retention`). Restore into a new server once as a test; a restore never overwrites the original.
- **`/data`:** snapshot the managed disk on a schedule (Azure Backup for the VM, or `az snapshot create`). Restore the database and the disk to the same moment.
- **A copy you control:** a nightly `pg_dump -Fc` into a storage container in the same region. Make sure it keeps running with [backup-monitoring.md](../backup-monitoring.md).
- Keep `.env` and the `JWT_SECRET` in your password vault; they are not in the backups.

## Upgrade

1. Take a database restore point (or a `pg_dump`) and a disk snapshot.
2. Read the release notes of the new version.
3. Change `<version>` in `docker-compose.yml`, then run `docker compose pull app && docker compose up -d app`.
4. The application migrates its own schema on start; expect a short downtime. Check `https://erp.example.com/api/health`.
5. To go back, restore the pre-upgrade backup together with the old image. Never start an older image on an already migrated database.

## Problems

| Symptom | Cause |
|---|---|
| Blank page, clean server log | `ALLOWED_ORIGINS` does not match the address in the browser |
| Upload fails with 413 | A proxy in front has a body limit; Caddy has none by default |
| Server stops during a cost pack import, nothing in the log | Out of memory, see the sizing section |
| Cannot connect to the database | The server requires TLS (`ssl=require`), the VM is outside the VNet, or the password is not percent-encoded |
| Container refuses to start and names `JWT_SECRET` | Shorter than 32 characters with `APP_ENV=production` |

More: [INSTALL_LINUX.md](../INSTALL_LINUX.md), [deploy/docker/README.md](../../deploy/docker/README.md), and for a Kubernetes layout with one instance per company [deploy/terraform/stackit](../../deploy/terraform/stackit/README.md).
