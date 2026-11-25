# Design editor link (contract version 1)

How a design editor (the desktop app or the browser bundle) talks to the ERP's Design module.
All paths are under `/api/v1/design`. Every request may send `X-DDC-Link: 1` (or a list such as `1,2`);
every response of the module, errors included, carries `X-DDC-Link: 1`. A request offering no supported
major gets `426` with `detail.supported`.

## Linking

1. In the ERP the user clicks **Open in editor**. `POST /link/code` (ERP session) with
   `{project_id, action: "new" | "open", revision_id?}` returns a `.ddclink` file
   (`schema: "ddc-link/1"`, `erp_url`, `project_id`, `project_name`, `code`, `expires_at`, `action`, `revision_id`).
   The code lives 5 minutes and works once.
2. The editor calls `POST /link/exchange` with `{code, client: {name, version, os}}` and receives
   `{token, expires_at, project_id}`. The token starts with `ddcl_`, lives 30 days, and is stored
   as a SHA-256 hash only. A used or expired code answers `410`; more than 30 attempts a minute from
   one address answer `429` with `Retry-After`.

## Token scope

A link token is a bearer token for one project and one user:

- Any other project answers `404`, never `403`, so project ids cannot be probed.
- The user must still have ERP access to the project; the token dies when the user's password changes,
  when the user is deactivated, or when the token is unlinked in the ERP.
- A token may read the project context, take and renew the editing lock, upload revisions, and read
  revisions and their files. It may never accept or reject a revision, relink the design, link field
  reports, or read and revoke link status: those are ERP-session acts.

## Project context and lock

- `GET /projects/{id}/context` returns `schema: "ddc-context/1"`, the project, permissions, the lock,
  the latest revision, the brief and the AI profile. It is sent with `Cache-Control: no-store`.
- `POST /projects/{id}/lock` takes the editing lock for 10 minutes; `POST .../lock/heartbeat` renews a
  lock the caller still holds (`409 "lock lost"` otherwise); `DELETE .../lock` releases it. A lock held by
  someone else answers `409` with `detail.held_by` and `detail.expires_at`.

## Pushing a revision

`POST /projects/{id}/revisions`, multipart field `package` (a `.ddcrev` zip). The caller must hold the lock.

- The package names its `revision_id` and `parent_revision_id`. The parent must be the current chain tip;
  otherwise `409` with `detail.latest_published`, and the editor rebases.
- Retrying the same package after a lost answer returns the stored revision with `200` while it awaits a
  decision; once decided, or with a different package
  under a used `revision_id`, it answers `409`.
- Limits (server settings): 2 GiB upload, 8 GiB unpacked, 64 MiB per JSON member and GLB JSON chunk,
  2,000,000 element rows. Over a limit answers `413`; a malformed package answers `422`.
- A stored revision has status `shared`: it waits for a decision and changes nothing in the ERP yet.

## Review and acceptance (in the ERP)

- `GET /revisions/{id}/impact` is the preview: element diff and its effect on BOQ positions, schedule and
  take-off before anything moves.
- `POST /revisions/{id}/accept` (project manager, ERP session) publishes the revision and, in the same
  transaction, updates the estimate, schedule, take-off and element links. If another revision was accepted
  since this one was based, it answers `409` and nothing changes.
- `POST /revisions/{id}/reject` with `{comment}`.

## Link status (ERP session)

- `GET /projects/{id}/link/status` returns `editors` (live tokens: client name, version, OS, `last_used_at`,
  `expires_at`, `mine`), `pending_revisions` (shared, awaiting a decision) and `last_revision`
  (`revision_id`, `number`, `status`, `source_kind`, `package_sha256`, `author`, `received_at`).
- `DELETE /projects/{id}/link/editors/{editor_id}` unlinks one editor; its holder or a project manager may.
  The token stops working at once.

## AI and MCP

MCP tools only propose changes; a person confirms each one in the ERP before it is applied. See `mcp.md`.
